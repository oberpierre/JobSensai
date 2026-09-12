"""LLM worker: consumes adapter-learning tasks from Redis and generates new adapters."""

import logging
import os
import subprocess
import time

import redis
from dotenv import load_dotenv

from llm.adapter_files import (
    _WORKSPACE_ROOT,
    AdapterNames,
    _adapter_names,
    _read_base_code,
    _write_adapter,
    _write_snapshot,
)
from llm.dom import prune_to_links, resolve_hrefs
from llm.html_cleaner import clean_html
from llm.learning_errors import TruthAgentUnreadable, UnlearnablePage
from llm.learning_task import LearningTaskRunner
from llm.model import (
    LLMModel,
    discovery_num_ctx,
    extraction_num_ctx,
    html_char_budget,
    parse_json_object,
    strip_code_fences,
)
from publisher.publisher import Publisher

load_dotenv()
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# A requeue with nothing else in the queue would otherwise spin on the same task.
_REQUEUE_BACKOFF_SECONDS = int(os.getenv("REQUEUE_BACKOFF_SECONDS", "30"))

# A dense model reasoning over a wide context can outlive the default lease, letting a
# second learning run start on the same domain before the first releases it.
_LEASE_TTL_SECONDS = int(os.getenv("LEARNING_LEASE_TTL_SECONDS", "1800"))


def _is_grounded_text(value: object) -> bool:
    """True when *value* is non-blank text, matching ExtractionSnapshotTest's rule.

    A list or other non-string survives ``str(...).strip()`` as truthy, so this check
    has to reject it the same way the snapshot base does rather than stringify it into
    passing.
    """
    return isinstance(value, str) and bool(value.strip())


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


class LLMWorker(LearningTaskRunner):
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
        lean = prune_to_links(cleaned)[: html_char_budget()]
        llm = LLMModel(base_url=self.llm_url, num_ctx=discovery_num_ctx())

        truth = parse_json_object(llm.generate_expected("discovery", lean, url))
        logger.debug("Truth agent output for %s:\n%s\n", names.basename, truth)
        if truth == {}:
            raise TruthAgentUnreadable("truth agent reply could not be parsed")
        job_links = truth.get("job_links", [])
        if not job_links:
            raise UnlearnablePage("truth agent grounded no job links")
        expected = {
            "url": url,
            "job_links": job_links,
            "next_page_links": truth.get("next_page_links", []),
        }
        _write_snapshot(names, "index.html", cleaned, expected, "DiscoverySnapshotTest")
        adapter_src = strip_code_fences(
            llm.generate_code(
                "discovery", lean, names.adapter_class, [domain], _read_base_code()
            )
        )
        _write_adapter(names, adapter_src)
        logger.info("Generated discovery adapter and snapshot for %s", names.basename)
        return names, llm.model_name

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
        sized = cleaned[: html_char_budget()]
        llm = LLMModel(base_url=self.llm_url, num_ctx=extraction_num_ctx())

        truth = parse_json_object(llm.generate_expected("extraction", sized, url))
        logger.debug("Truth agent output for %s:\n%s\n", names.basename, truth)
        if truth == {}:
            raise TruthAgentUnreadable("truth agent reply could not be parsed")
        if not _is_grounded_text(truth.get("title")) or not _is_grounded_text(
            truth.get("description")
        ):
            raise UnlearnablePage("truth agent grounded no title or description")
        expected = {"url": url}
        for field in _SILVER_FIELDS:
            if field in truth:
                expected[field] = truth[field]
        _write_snapshot(
            names, "detail.html", cleaned, expected, "ExtractionSnapshotTest"
        )
        adapter_src = strip_code_fences(
            llm.generate_code(
                "extraction", sized, names.adapter_class, [domain], _read_base_code()
            )
        )
        _write_adapter(names, adapter_src)
        logger.info("Generated extraction adapter and snapshot for %s", names.basename)
        return names, llm.model_name

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
