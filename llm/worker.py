"""LLM worker: consumes adapter-learning tasks from Redis and generates new adapters."""

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

import redis
from dotenv import load_dotenv

from llm.dom import prune_to_links, resolve_hrefs
from llm.html_cleaner import clean_html
from llm.model import LLMModel
from publisher.publisher import Publisher

load_dotenv()
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Paths resolved relative to this file so they work in both bazel run and tests.
# During `bazel run`, BUILD_WORKSPACE_DIRECTORY points to the real checkout root,
# which is where generated adapter files are written.
_WORKSPACE_ROOT = Path(
    os.environ.get("BUILD_WORKSPACE_DIRECTORY", str(Path(__file__).parent.parent))
)
_ADAPTERS_DIR = _WORKSPACE_ROOT / "adapters" / "adapters"

# Ollama sizes its KV cache from num_ctx, so the window is set per adapter type.
# Discovery feeds a pruned link-only skeleton that stays small. Detail pages carry the
# full posting body (a 1 MB page cleans to ~120k chars) and need a wider window, else
# Ollama truncates the tail holding the content. Overridable per box for tuning.
_DISCOVERY_NUM_CTX = int(os.getenv("DISCOVERY_NUM_CTX", "32768"))
_EXTRACTION_NUM_CTX = int(os.getenv("EXTRACTION_NUM_CTX", "65536"))

# A requeue with nothing else in the queue would otherwise spin on the same task.
_REQUEUE_BACKOFF_SECONDS = int(os.getenv("REQUEUE_BACKOFF_SECONDS", "30"))

# A dense model reasoning over a wide context can outlive the default lease, letting a
# second learning run start on the same domain before the first releases it.
_LEASE_TTL_SECONDS = int(os.getenv("LEARNING_LEASE_TTL_SECONDS", "1800"))


def _domain_slug(domain: str) -> str:
    """Turn a domain into a valid Python module-name fragment.

    Lowercases and replaces every run of non-alphanumeric characters with a single
    underscore, e.g. ``job-boards.greenhouse.io`` -> ``job_boards_greenhouse_io``.
    ``domain.replace(".", "_")`` left hyphens in place and produced illegal module
    names for hyphenated boards.
    """
    return re.sub(r"[^a-z0-9]+", "_", domain.lower()).strip("_")


class AdapterNames(NamedTuple):
    basename: str
    module_path: str
    adapter_class: str
    test_class: str


def _adapter_names(domain: str, adapter_type: str, version: int = 1) -> AdapterNames:
    """Derive the file/module/class names for a generated adapter.

    Both agents receive these names up-front, so the generated test's import line and
    the adapter's class definition line up without either agent seeing the other.
    """
    slug = _domain_slug(domain)
    basename = f"{slug}_{adapter_type}_v{version}"
    pascal = "".join(part.capitalize() for part in slug.split("_") if part)
    adapter_class = f"{pascal}{adapter_type.capitalize()}Adapter"
    return AdapterNames(
        basename=basename,
        module_path=f"adapters.adapters.{basename}",
        adapter_class=adapter_class,
        test_class=f"Test{adapter_class}",
    )


def _parse_json_object(raw: str) -> dict:
    """Parse an LLM JSON reply into a dict, tolerating stray prose or code fences."""
    candidates = [raw]
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        candidates.append(raw[start : end + 1])
    for candidate in candidates:
        try:
            result = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(result, dict):
            return result
    return {}


def _strip_code_fences(text: str) -> str:
    """Drop a leading/trailing markdown code fence if the model wrapped its output."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip() + "\n"


# The generated test is deterministic boilerplate: all grounded assertions live in the
# snapshot base class it imports and subclasses.
_TEST_TEMPLATE = """import unittest

from adapters.adapters.snapshot import {snapshot_base}
from {module_path} import {adapter_class}


class {test_class}({snapshot_base}, unittest.TestCase):
    adapter_cls = {adapter_class}
    fixture_dir = "{basename}"
"""

# The Silver-schema keys the extraction truth agent enumerates into expected.json.
_SILVER_FIELDS = (
    "title",
    "company_name",
    "employment_type",
    "locations",
    "categories",
    "description",
    "metadata",
)


class LLMWorker:
    def __init__(
        self,
        llm_url: str = "localhost:11434",
        redis_host: str = "localhost",
        redis_port: int = 6379,
        queue_names: list[str] | None = None,
        publisher: Publisher | None = None,
    ) -> None:
        self.llm_url = llm_url
        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            username=os.getenv("REDIS_USERNAME") or None,
            password=os.getenv("REDIS_PASSWORD") or None,
        )
        self.publisher = publisher or Publisher(repo_root=_WORKSPACE_ROOT)
        self.queue_names = queue_names or [
            "discovery_learning_tasks",
            "extraction_learning_tasks",
        ]
        self.running = False
        # Separate from self.running so run()'s return value keeps reporting "could not
        # publish" even once self.running gains other, unrelated reasons to go False.
        self._publish_unavailable = False

    def is_learning_in_progress(self, domain: str, adapter_type: str) -> bool:
        return (
            self.redis_client.get(f"LEARNING_IN_PROGRESS:{adapter_type}:{domain}")
            is not None
        )

    def start_learning(
        self, domain: str, adapter_type: str, ttl: int = _LEASE_TTL_SECONDS
    ) -> bool:
        """Acquire a learning lock for *domain* + *adapter_type*.

        Discovery and extraction learn independently, so the lock is namespaced by
        adapter type to stop one type's task from blocking the other's for the same
        domain. Returns True if the lock was acquired.
        """
        return bool(
            self.redis_client.set(
                f"LEARNING_IN_PROGRESS:{adapter_type}:{domain}", "1", nx=True, ex=ttl
            )
        )

    def release_learning(self, domain: str, adapter_type: str) -> None:
        """Release the lease once the task is finished."""
        self.redis_client.delete(f"LEARNING_IN_PROGRESS:{adapter_type}:{domain}")

    def _write_fixture(self, basename: str, filename: str, content: str) -> Path:
        fixture_dir = _ADAPTERS_DIR / "fixtures" / basename
        fixture_dir.mkdir(parents=True, exist_ok=True)
        path = fixture_dir / filename
        path.write_text(content)
        return path

    def _learn_discovery(
        self, domain: str, url: str, html: str
    ) -> tuple[AdapterNames, str]:
        """Generate a discovery adapter for a listing page, test-first.

        Prune to the link-bearing skeleton, have the truth agent snapshot the
        job/next-page links from it, then have the code agent write the adapter from
        that same lean HTML rather than the snapshot. The stored ``index.html`` keeps
        the full cleaned page, catching over-selection a lean-only test would miss.
        """
        names = _adapter_names(domain, "discovery")
        cleaned = clean_html(resolve_hrefs(html, url))
        lean = prune_to_links(cleaned)
        llm = LLMModel(base_url=self.llm_url, num_ctx=_DISCOVERY_NUM_CTX)

        truth = _parse_json_object(llm.generate_expected("discovery", lean, url))
        logger.debug("Truth agent output for %s:\n%s\n", names.basename, truth)
        expected = {
            "url": url,
            "job_links": truth.get("job_links", []),
            "next_page_links": truth.get("next_page_links", []),
        }
        self._write_snapshot(
            names, "index.html", cleaned, expected, "DiscoverySnapshotTest"
        )
        self._write_adapter(names, "discovery", lean, [domain], llm)
        logger.info("Generated discovery adapter and snapshot for %s", names.basename)
        return names, llm.model_name

    def _write_snapshot(
        self,
        names: AdapterNames,
        fixture_filename: str,
        page: str,
        expected: dict,
        snapshot_base: str,
    ) -> None:
        """Write the page fixture, the grounded ``expected.json``, and the test.

        Shared by both flows: each builds its own ``expected`` dict from the HTML it
        grounded, then hands it here so the three files land the same way regardless
        of adapter type.
        """
        self._write_fixture(names.basename, fixture_filename, page)
        self._write_fixture(
            names.basename, "expected.json", json.dumps(expected, indent=2)
        )
        test_source = _TEST_TEMPLATE.format(
            module_path=names.module_path,
            adapter_class=names.adapter_class,
            test_class=names.test_class,
            basename=names.basename,
            snapshot_base=snapshot_base,
        )
        (_ADAPTERS_DIR / f"{names.basename}_test.py").write_text(test_source)

    def _learn_extraction(
        self, domain: str, url: str, html: str
    ) -> tuple[AdapterNames, str]:
        """Generate an extraction adapter for a detail page, test-first.

        Unlike discovery, the page is cleaned but never pruned, since extraction reads
        the posting's content rather than only its links. The truth agent pins only
        the Silver fields it actually reports, so the snapshot test stays silent on
        the rest.
        """
        names = _adapter_names(domain, "extraction")
        cleaned = clean_html(html)
        llm = LLMModel(base_url=self.llm_url, num_ctx=_EXTRACTION_NUM_CTX)

        truth = _parse_json_object(llm.generate_expected("extraction", cleaned, url))
        logger.debug("Truth agent output for %s:\n%s\n", names.basename, truth)
        expected = {"url": url}
        for field in _SILVER_FIELDS:
            if field in truth:
                expected[field] = truth[field]
        self._write_snapshot(
            names, "detail.html", cleaned, expected, "ExtractionSnapshotTest"
        )
        self._write_adapter(names, "extraction", cleaned, [domain], llm)
        logger.info("Generated extraction adapter and snapshot for %s", names.basename)
        return names, llm.model_name

    def _write_adapter(
        self,
        names: AdapterNames,
        adapter_type: str,
        html: str,
        domains: list[str],
        llm: LLMModel,
    ) -> None:
        """Code agent → the adapter that must satisfy the (withheld) snapshot."""
        base_code = (_ADAPTERS_DIR / "base.py").read_text()
        adapter_src = _strip_code_fences(
            llm.generate_code(
                adapter_type, html, names.adapter_class, domains, base_code
            )
        )
        (_ADAPTERS_DIR / f"{names.basename}.py").write_text(adapter_src)

    def _run_adapter_tests(self) -> tuple[bool, str]:
        """Run the adapter suite once. Return whether it passed and its output.

        The output is carried back rather than only logged because it becomes the body
        of the PR: a red run has to tell the reviewer what broke.
        """
        result = subprocess.run(
            ["bazel", "test", "//adapters:adapter_test", "--test_output=errors"],
            cwd=str(_WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout + result.stderr
        if result.returncode != 0:
            logger.error("Adapter tests failed:\n%s", output[-2000:])
        return result.returncode == 0, output

    def run(self) -> bool:
        """Consume tasks until stopped.

        Returns whether the worker could publish for its entire run. main() exits
        non-zero exactly when this is False.
        """
        if not self.publisher.can_publish():
            logger.error("Cannot publish: run `gh auth login` and restart")
            self._publish_unavailable = True
            return not self._publish_unavailable
        self.running = True
        logger.info("Starting LLM Worker, listening on %s", self.queue_names)
        while self.running:
            if self.process_next_task() and self.running:
                time.sleep(_REQUEUE_BACKOFF_SECONDS)
        return not self._publish_unavailable

    def process_next_task(self) -> bool:
        result = self.redis_client.brpop(self.queue_names, timeout=1)
        if not result:
            return False
        queue, message = result
        queue_name = queue.decode("utf-8") if isinstance(queue, bytes) else queue
        return self.process_task(message, queue_name)

    def process_task(self, message: bytes, queue_name: str) -> bool:
        """Route a learning task to the generation flow for its adapter type.

        Returns True when the task was pushed back onto its queue rather than acted
        on, so the caller can back off instead of hammering the queue.
        """
        # Resolve the adapter type up-front so the learning lock is namespaced by it
        # and stays reachable for cleanup in the except blocks below.
        adapter_type = "discovery" if "discovery" in queue_name else "extraction"
        domain: str | None = None
        lock_key: str | None = None

        try:
            task = json.loads(message)

            domain = task.get("domain") or None
            if not domain:
                url = task.get("url", "")
                domain = urlsplit(url).netloc or None
            if not domain:
                logger.error("Task has no resolvable domain: %s", task)
                return False

            lock_key = f"LEARNING_IN_PROGRESS:{adapter_type}:{domain}"

            raw_html = (
                task.get("html")
                or task.get("html_content")
                or task.get("raw_html")
                or "<html><body>No HTML provided</body></html>"
            )

            logger.info("Processing %s task for domain: %s", adapter_type, domain)

            if not self.start_learning(domain, adapter_type):
                logger.info("Learning already in progress for domain: %s", domain)
                return False

            # The lease only dedups tasks racing in one scrape run. Across runs the
            # board still has no adapter until its PR merges and the scraper redeploys,
            # so every crawl re-enqueues, because GitHub is what knows the work
            # is already done.
            names = _adapter_names(domain, adapter_type)
            pr_state = self.publisher.has_existing_pr(names.basename)
            if pr_state is None:
                # Undeterminable is not "already published": the task would be lost
                # for good, so it goes back on the queue instead of being dropped.
                logger.error(
                    "Could not determine PR state for %s, returning task to %s",
                    names.basename,
                    queue_name,
                )
                if not self.publisher.can_publish():
                    # A credential revoked mid-run would otherwise requeue every
                    # later task forever with no further check.
                    logger.error("Cannot publish: run `gh auth login` and restart")
                    self.running = False
                    self._publish_unavailable = True
                # Release before requeueing: lpush-then-release reopens the window a
                # second consumer could pop the message through before the lease clears.
                self.release_learning(domain, adapter_type)
                self.redis_client.lpush(queue_name, message)
                return True
            if pr_state is True:
                logger.info("Adapter %s already has a PR, skipping", names.basename)
                self.release_learning(domain, adapter_type)
                return False

            url = task.get("url") or f"https://{domain}"

            if adapter_type == "discovery":
                names, model_name = self._learn_discovery(domain, url, raw_html)
            else:
                names, model_name = self._learn_extraction(domain, url, raw_html)

            passed, test_output = self._run_adapter_tests()
            logger.info(
                "%s adapter for %s: snapshot test %s",
                adapter_type,
                domain,
                "passed" if passed else "FAILED (left for review)",
            )

            # Red runs publish too as a draft PR carrying the failure for manual fixing.
            pr_url = self.publisher.publish(
                basename=names.basename,
                adapter_class=names.adapter_class,
                domain=domain,
                adapter_type=adapter_type,
                passed=passed,
                test_output=test_output,
                model_name=model_name,
            )
            if pr_url:
                logger.info("Opened PR for %s: %s", names.basename, pr_url)
            else:
                # No PR exists, so the next crawl's gh check finds nothing and retries.
                logger.error(
                    "Publish failed for %s. Retrying with next crawl.", names.basename
                )
            self.release_learning(domain, adapter_type)
            return False

        except json.JSONDecodeError as exc:
            logger.error("Failed to decode task message: %s", exc)
            return False
        except Exception as exc:
            logger.error("Unexpected error processing task: %s", exc, exc_info=True)
            if lock_key:
                self.redis_client.delete(lock_key)
            return False


def _worker_from_env() -> LLMWorker:
    """Build the runner from environment variables."""
    ollama_host = os.getenv("OLLAMA_HOST", "localhost")
    ollama_port = os.getenv("OLLAMA_PORT", "11434")
    # OLLAMA_HOST is a host, but a scheme is an easy mistake to make (main.py's URL,
    # the compose value), so drop it rather than build http://http://...
    host = ollama_host.split("://", 1)[-1]
    return LLMWorker(
        llm_url=f"http://{host}:{ollama_port}",
        redis_host=os.getenv("REDIS_HOST", "localhost"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
    )


def main() -> None:
    worker = _worker_from_env()
    try:
        if not worker.run():
            raise SystemExit(1)
    except KeyboardInterrupt:
        worker.running = False
        logger.info("Interrupted, shutting down")
