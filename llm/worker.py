"""LLM worker: consumes adapter-learning tasks from Redis and generates new adapters."""

import ast
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import NamedTuple, cast
from urllib.parse import urlsplit

import redis
from dotenv import load_dotenv

from llm.dom import prune_to_links, resolve_hrefs
from llm.html_cleaner import clean_html
from llm.model import LLMModel

load_dotenv()
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Paths resolved relative to this file so they work in both bazel run and tests.
# During `bazel run`, BUILD_WORKSPACE_DIRECTORY points to the real checkout root,
# which is where we need to write generated adapter files and patch BUILD.bazel.
_WORKSPACE_ROOT = Path(
    os.environ.get("BUILD_WORKSPACE_DIRECTORY", str(Path(__file__).parent.parent))
)
_ADAPTERS_DIR = _WORKSPACE_ROOT / "adapters" / "adapters"
_BUILD_BAZEL = _WORKSPACE_ROOT / "adapters" / "BUILD.bazel"

_MAX_REPAIR_ITERATIONS = 3


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


# The discovery test is deterministic boilerplate: all grounded assertions live in the
# snapshot the DiscoverySnapshotTest base compares against.
_DISCOVERY_TEST_TEMPLATE = '''import unittest

from adapters.adapters.snapshot import DiscoverySnapshotTest
from {module_path} import {adapter_class}


class {test_class}(DiscoverySnapshotTest, unittest.TestCase):
    adapter_cls = {adapter_class}
    fixture_dir = "{basename}"
'''


class LLMWorker:
    def __init__(
        self,
        llm_url: str = "localhost:11434",
        redis_host: str = "localhost",
        redis_port: int = 6379,
        queue_names: list[str] | None = None,
    ) -> None:
        self.llm_url = llm_url
        self.redis_client = redis.Redis(host=redis_host, port=redis_port)
        self.queue_names = queue_names or [
            "discovery_learning_tasks",
            "extraction_learning_tasks",
        ]
        self.running = False

    def is_learning_in_progress(self, domain: str, adapter_type: str) -> bool:
        return (
            self.redis_client.get(f"LEARNING_IN_PROGRESS:{adapter_type}:{domain}")
            is not None
        )

    def start_learning(self, domain: str, adapter_type: str, ttl: int = 1800) -> bool:
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

    def complete_learning(self, domain: str, adapter_type: str) -> None:
        self.redis_client.delete(f"LEARNING_IN_PROGRESS:{adapter_type}:{domain}")
        self.redis_client.set(f"LEARNING_COMPLETE:{adapter_type}:{domain}", "1")

    def _write_fixture(self, basename: str, filename: str, content: str) -> Path:
        fixture_dir = _ADAPTERS_DIR / "fixtures" / basename
        fixture_dir.mkdir(parents=True, exist_ok=True)
        path = fixture_dir / filename
        path.write_text(content)
        return path

    def _write_discovery_snapshot(
        self, domain: str, url: str, html: str
    ) -> AdapterNames:
        """Run the truth agent for a listing page and write its snapshot + test.

        The truth agent sees the page pruned to its link-bearing skeleton (small enough
        to reason over), while the stored ``index.html`` is the full cleaned page, so an
        adapter's selectors are later tested against everything a real page holds. The
        adapter is produced by the code agent afterwards.
        """
        names = _adapter_names(domain, "discovery")
        cleaned = clean_html(resolve_hrefs(html, url))
        lean = prune_to_links(cleaned)

        llm = LLMModel(base_url=self.llm_url)
        truth = _parse_json_object(llm.generate_expected("discovery", lean, url))
        logger.debug("Truth agent output for %s:\n%s\n", domain, truth)
        expected = {
            "url": url,
            "job_links": truth.get("job_links", []),
            "next_page_links": truth.get("next_page_links", []),
        }

        self._write_fixture(names.basename, "index.html", cleaned)
        self._write_fixture(
            names.basename, "expected.json", json.dumps(expected, indent=2)
        )
        test_source = _DISCOVERY_TEST_TEMPLATE.format(
            module_path=names.module_path,
            adapter_class=names.adapter_class,
            test_class=names.test_class,
            basename=names.basename,
        )
        (_ADAPTERS_DIR / f"{names.basename}_test.py").write_text(test_source)
        logger.info("Wrote discovery snapshot and test for %s", names.basename)
        return names

    def run(self) -> None:
        self.running = True
        logger.info("Starting LLM Worker, listening on %s", self.queue_names)
        while self.running:
            self.process_next_task()

    def process_next_task(self) -> None:
        result = self.redis_client.brpop(self.queue_names, timeout=1)
        if not result:
            return
        queue, message = result
        queue_name = queue.decode("utf-8") if isinstance(queue, bytes) else queue
        self.process_task(message, queue_name)

    def process_task(self, message: bytes, queue_name: str = "") -> None:
        """Parse a Redis message and run the full adapter-generation pipeline."""
        # Resolve the adapter type up-front so the learning lock is namespaced by it
        # and stays reachable for cleanup in the except blocks below.
        adapter_type = "discovery" if "discovery" in queue_name else "extraction"
        domain: str | None = None
        lock_key: str | None = None
        adapter_code: str | None = None
        test_code: str | None = None

        try:
            task = json.loads(message)

            domain = task.get("domain") or None
            if not domain:
                url = task.get("url", "")
                domain = urlsplit(url).netloc or None
            if not domain:
                logger.error("Task has no resolvable domain: %s", task)
                return

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
                return

            # -- Read base files -----------------------------------------------
            base_code = (_ADAPTERS_DIR / "base.py").read_text()
            test_base_code = (_ADAPTERS_DIR / "base_test.py").read_text()

            # -- Generate initial adapter code ---------------------------------
            llm = LLMModel(base_url=self.llm_url)
            response = llm.generate_adapter(
                domain, raw_html, adapter_type, base_code, test_base_code
            )
            logger.debug("Initial LLM response for %s:\n%s", domain, response)

            adapter_code, test_code = self.parse_llm_response(response)
            if not adapter_code:
                logger.error(
                    "Failed to parse adapter code from LLM response for %s", domain
                )
                self.redis_client.delete(lock_key)
                return

            if not self._quick_validate(
                domain,
                adapter_code,
                raw_html,
                task.get("url", f"https://{domain}"),
                adapter_type,
            ):
                self.redis_client.delete(lock_key)
                return

            # -- Write files + BUILD.bazel patch + bazel test loop -------------
            success = self._write_test_and_verify(
                domain,
                adapter_code,
                test_code,
                adapter_type,
                raw_html,
                task.get("url", f"https://{domain}"),
                base_code,
                test_base_code,
                llm,
            )

            if success:
                self._commit(domain, adapter_type)
                self.complete_learning(domain, adapter_type)
            else:
                logger.error("Permanent failure generating adapter for %s", domain)
                self._cleanup_files(domain, adapter_type)
                self.redis_client.delete(lock_key)

        except json.JSONDecodeError as exc:
            logger.error("Failed to decode task message: %s", exc)
        except Exception as exc:
            logger.error("Unexpected error processing task: %s", exc, exc_info=True)
            if lock_key:
                self.redis_client.delete(lock_key)

    def _write_test_and_verify(
        self,
        domain: str,
        adapter_code: str,
        test_code: str | None,
        adapter_type: str,
        raw_html: str,
        _url: str,
        base_code: str,
        test_base_code: str,
        llm: LLMModel,
    ) -> bool:
        """Write adapter files, patch BUILD.bazel, then verify with `bazel test`.

        Retries up to _MAX_REPAIR_ITERATIONS times, feeding bazel stderr back to
        the LLM for self-correction.
        """
        for attempt in range(1, _MAX_REPAIR_ITERATIONS + 1):
            self._write_adapter_files(domain, adapter_code, test_code, adapter_type)
            self._patch_build_bazel(domain, adapter_type)

            stderr = self._run_bazel_test()
            if stderr is None:
                logger.info("bazel test passed on attempt %d for %s", attempt, domain)
                return True

            logger.warning(
                "bazel test failed (attempt %d/%d) for %s:\n%s",
                attempt,
                _MAX_REPAIR_ITERATIONS,
                domain,
                stderr,
            )

            if attempt == _MAX_REPAIR_ITERATIONS:
                break

            # Feed error back to LLM for repair
            logger.info("Requesting LLM repair for %s (attempt %d)", domain, attempt)
            response = llm.generate_adapter(
                domain,
                raw_html,
                adapter_type,
                base_code,
                test_base_code,
                previous_code=adapter_code
                + "\n\n# --- TEST CODE ---\n\n"
                + (test_code or ""),
                error_message=stderr,
            )
            new_adapter, new_test = self.parse_llm_response(response)
            if new_adapter:
                adapter_code = new_adapter
                test_code = new_test
            else:
                logger.error("LLM repair produced no parseable code for %s", domain)

        return False

    def _write_adapter_files(
        self,
        domain: str,
        adapter_code: str,
        test_code: str | None,
        adapter_type: str,
    ) -> tuple[Path, Path | None]:
        safe = _domain_slug(domain)
        stem = f"{safe}_{adapter_type}_v1"

        adapter_path = _ADAPTERS_DIR / f"{stem}.py"
        adapter_path.write_text(adapter_code)
        logger.info("Wrote adapter to %s", adapter_path)

        test_path: Path | None = None
        if test_code:
            test_path = _ADAPTERS_DIR / f"{stem}_test.py"
            test_path.write_text(test_code)
            logger.info("Wrote test to %s", test_path)

        return adapter_path, test_path

    def _patch_build_bazel(self, domain: str, adapter_type: str) -> None:
        """Append a dedicated py_test target to adapters/BUILD.bazel."""
        safe = _domain_slug(domain)
        stem = f"{safe}_{adapter_type}_v1"
        target_name = f"{stem}_test"

        content = _BUILD_BAZEL.read_text()
        if target_name in content:
            return  # already patched

        new_target = (
            f"\npy_test(\n"
            f'    name = "{target_name}",\n'
            f'    srcs = ["adapters/{stem}_test.py"],\n'
            f"    deps = [\n"
            f'        ":adapters",\n'
            f'        ":adapters_base",\n'
            f"    ],\n"
            f")\n"
        )
        _BUILD_BAZEL.write_text(content + new_target)
        logger.info("Patched BUILD.bazel with target %s", target_name)

    def _run_bazel_test(self) -> str | None:
        """Run adapter tests. Returns None on success, stderr on failure."""
        try:
            result = subprocess.run(
                ["bazel", "test", "//adapters/..."],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(_WORKSPACE_ROOT),
            )
            if result.returncode == 0:
                return None
            return (result.stdout + "\n" + result.stderr).strip()
        except FileNotFoundError:
            logger.error("bazel not found in PATH; falling back to pytest")
            return self._run_pytest_fallback()

    def _run_pytest_fallback(self) -> str | None:
        """Quick fallback when bazel is not available (e.g. inside unit tests)."""
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(_ADAPTERS_DIR), "-q"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(_WORKSPACE_ROOT),
        )
        if result.returncode == 0:
            return None
        return (result.stdout + "\n" + result.stderr).strip()

    def _cleanup_files(self, domain: str, adapter_type: str) -> None:
        safe = _domain_slug(domain)
        stem = f"{safe}_{adapter_type}_v1"
        for suffix in [".py", "_test.py"]:
            p = _ADAPTERS_DIR / f"{stem}{suffix}"
            if p.exists():
                p.unlink()
                logger.info("Cleaned up %s", p)

    def _commit(self, domain: str, adapter_type: str) -> None:
        safe = _domain_slug(domain)
        stem = f"{safe}_{adapter_type}_v1"
        adapter_path = _ADAPTERS_DIR / f"{stem}.py"
        test_path = _ADAPTERS_DIR / f"{stem}_test.py"

        branch = f"feature/{adapter_type}-adapter-{safe}-v1"
        files = [str(adapter_path)]
        if test_path.exists():
            files.append(str(test_path))
        files.append(str(_BUILD_BAZEL))

        try:
            subprocess.run(
                ["git", "checkout", "-b", branch], cwd=str(_WORKSPACE_ROOT), check=False
            )
            subprocess.run(["git", "add"] + files, cwd=str(_WORKSPACE_ROOT), check=True)
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    f"feat: add generated {adapter_type} adapter for {domain}",
                ],
                cwd=str(_WORKSPACE_ROOT),
                check=True,
            )
            logger.info("Committed adapter for %s on branch %s", domain, branch)
        except Exception as exc:
            logger.error("Git commit failed for %s: %s", domain, exc)

    def parse_llm_response(self, response: str) -> tuple[str | None, str | None]:
        """Split LLM output on the canonical separator."""
        if "# --- TEST CODE ---" in response:
            parts = response.split("# --- TEST CODE ---", maxsplit=1)
            return parts[0].strip() or None, parts[1].strip() or None
        return response.strip() or None, None

    def _quick_validate(
        self,
        domain: str,
        adapter_code: str,
        raw_html: str,
        url: str,
        adapter_type: str = "extraction",
    ) -> bool:
        """AST parse + runtime instantiation check before touching the filesystem."""
        from adapters.adapters.base import DiscoveryAdapter, ExtractionAdapter

        is_discovery = adapter_type == "discovery"
        base_class = DiscoveryAdapter if is_discovery else ExtractionAdapter
        base_class_name = "DiscoveryAdapter" if is_discovery else "ExtractionAdapter"

        try:
            ast.parse(adapter_code)

            if base_class_name not in adapter_code:
                logger.error(
                    "Generated code for %s does not inherit %s", domain, base_class_name
                )
                return False

            # Execute in an isolated module namespace
            mod_name = f"_dynamic_{_domain_slug(domain)}"
            mod = ModuleType(mod_name)
            mod.__dict__["DiscoveryAdapter"] = DiscoveryAdapter
            mod.__dict__["ExtractionAdapter"] = ExtractionAdapter
            exec(adapter_code, mod.__dict__)  # noqa: S102

            adapter_cls = next(
                (
                    v
                    for v in mod.__dict__.values()
                    if isinstance(v, type)
                    and issubclass(v, base_class)
                    and v is not base_class
                ),
                None,
            )
            if not adapter_cls:
                logger.error(
                    "No %s subclass found in generated code for %s",
                    base_class_name,
                    domain,
                )
                return False

            if is_discovery:
                disc = cast(DiscoveryAdapter, adapter_cls())
                if not isinstance(disc.get_job_links(raw_html, url), list):
                    logger.error("get_job_links() for %s did not return list", domain)
                    return False
                if not isinstance(disc.get_next_page_links(raw_html, url), list):
                    logger.error(
                        "get_next_page_links() for %s did not return list", domain
                    )
                    return False
            else:
                extr = cast(ExtractionAdapter, adapter_cls())
                if not isinstance(extr.extract(raw_html, url), dict):
                    logger.error("extract() for %s did not return dict", domain)
                    return False

            logger.info("Quick validation passed for %s", domain)
            return True

        except Exception as exc:
            logger.error("Quick validation error for %s: %s", domain, exc)
            return False

    # ------------------------------------------------------------------
    # Legacy aliases kept for backward-compat with existing tests
    # ------------------------------------------------------------------

    def validate_code(
        self,
        domain: str,
        adapter_code: str,
        _test_code: str | None,
        raw_html: str,
        url: str,
        _retry_count: int = 0,
        adapter_type: str = "extraction",
    ) -> bool:
        return self._quick_validate(domain, adapter_code, raw_html, url, adapter_type)

    def run_generated_tests(
        self, domain: str, adapter_code: str, test_code: str
    ) -> bool:
        """Run generated pytest tests in a temp directory (used by tests)."""
        import tempfile

        safe = _domain_slug(domain)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / f"adapter_{safe}.py").write_text(adapter_code)
            full_test = (
                f"import sys\nsys.path.insert(0, '{tmpdir}')\n"
                f"from adapter_{safe} import *\n\n{test_code}"
            )
            (tmp / f"test_{safe}.py").write_text(full_test)

            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(tmp / f"test_{safe}.py")],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                logger.error(
                    "Pytest failed for %s:\n%s\n%s",
                    domain,
                    result.stdout,
                    result.stderr,
                )
                return False
            return True

    def save_and_commit(
        self,
        domain: str,
        adapter_code: str,
        test_code: str | None,
        adapter_type: str = "extraction",
    ) -> None:
        """Write files and commit (used by tests; production uses _commit)."""
        self._write_adapter_files(domain, adapter_code, test_code, adapter_type)
        self._commit(domain, adapter_type)

    def retry_generation(
        self,
        domain: str,
        raw_html: str,
        error_message: str,
        _retry_count: int,
        adapter_type: str = "extraction",
    ) -> bool:
        base_code = (_ADAPTERS_DIR / "base.py").read_text()
        test_base_code = (_ADAPTERS_DIR / "base_test.py").read_text()

        llm = LLMModel(base_url=self.llm_url)
        response = llm.generate_adapter(
            domain,
            raw_html,
            adapter_type,
            base_code,
            test_base_code,
            error_message=error_message,
        )
        adapter_code, _test_code = self.parse_llm_response(response)
        if not adapter_code:
            return False
        url = f"https://{domain}"
        return self._quick_validate(domain, adapter_code, raw_html, url, adapter_type)


if __name__ == "__main__":
    llm_url = (
        f"http://{os.getenv('OLLAMA_HOST', 'localhost')}:"
        f"{os.getenv('OLLAMA_PORT', '11434')}"
    )
    worker = LLMWorker(
        llm_url=llm_url,
        redis_host=os.getenv("REDIS_HOST", "localhost"),
        redis_port=int(os.getenv("REDIS_PORT", 6379)),
    )

    while True:
        try:
            worker.run()
        except redis.exceptions.ConnectionError:
            logger.error("Redis connection lost. Retrying in 5 seconds...")
            time.sleep(5)
