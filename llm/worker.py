import json
import logging
import os
import sys
from urllib.parse import urlsplit

import redis

from llm.model import LLMModel

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class LLMWorker:
    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        queue_names: list[str] | None = None,
    ):
        self.redis_client = redis.Redis(host=redis_host, port=redis_port)
        self.queue_names = queue_names or [
            "discovery_learning_tasks",
            "extraction_learning_tasks",
        ]
        self.running = False

    def is_learning_in_progress(self, domain: str) -> bool:
        """Check if learning is already in progress for a domain."""
        return self.redis_client.get(f"LEARNING_IN_PROGRESS:{domain}") is not None

    def start_learning(self, domain: str, ttl: int = 1800) -> bool:
        """Set a learning lock for a domain. Returns True if lock acquired."""
        return bool(
            self.redis_client.set(
                f"LEARNING_IN_PROGRESS:{domain}", "1", nx=True, ex=ttl
            )
        )

    def complete_learning(self, domain: str):
        """Remove the learning lock for a domain and mark as complete."""
        self.redis_client.delete(f"LEARNING_IN_PROGRESS:{domain}")
        self.redis_client.set(f"LEARNING_COMPLETE:{domain}", "1")

    def run(self):
        """Run the worker loop."""
        self.running = True
        logger.info(f"Starting LLM Worker, listening to {self.queue_names}")

        while self.running:
            self.process_next_task()

    def process_next_task(self):
        """Process a single task from the queue."""
        result = self.redis_client.brpop(self.queue_names, timeout=1)
        if not result:
            return

        queue, message = result
        queue_name = queue.decode("utf-8") if isinstance(queue, bytes) else queue
        self.process_task(message, queue_name)

    def process_task(self, message: bytes, queue_name: str):
        """Process a task payload."""
        domain = None
        try:
            task = json.loads(message)
            url = task.get("url")

            if not url:
                logger.error("Task missing URL: %s", task)
                return

            domain = urlsplit(url).netloc
            logger.info(
                f"Processing task for domain: {domain} from queue: {queue_name}"
            )

            if not self.start_learning(domain):
                logger.info("Learning already in progress for domain: %s", domain)
                return

            logger.info("Starting learning for domain: %s", domain)

            raw_html = task.get(
                "raw_html", "<html><body>No HTML provided</body></html>"
            )

            # Determine adapter type from queue name
            adapter_type = "discovery" if "discovery" in queue_name else "extraction"

            # LLM generation pipeline
            with open(os.path.join("adapters", "adapters", "base.py")) as f:
                base_code_full = f.read()
            with open(os.path.join("adapters", "adapters", "base_test.py")) as f:
                test_base_code_full = f.read()

            # We pass the full base file contents to provide context about
            # what to import
            llm_model = LLMModel()
            generated_response = llm_model.generate_adapter(
                domain, raw_html, adapter_type, base_code_full, test_base_code_full
            )

            adapter_code, test_code = self.parse_llm_response(generated_response)

            if not adapter_code:
                logger.error(f"Failed to parse adapter code for {domain}")
                self.redis_client.delete(f"LEARNING_IN_PROGRESS:{domain}")
                return

            logger.info("Parsed adapter code length: %d", len(adapter_code))

            if self.validate_code(
                domain,
                adapter_code,
                test_code,
                raw_html,
                url,
                adapter_type=adapter_type,
            ):
                self.save_and_commit(domain, adapter_code, test_code, adapter_type)
                self.complete_learning(domain)
            else:
                logger.error(f"Validation failed for domain: {domain}")
                # Cleanup lock on failure so we can retry later
                self.redis_client.delete(f"LEARNING_IN_PROGRESS:{domain}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode task message: {e}")
        except Exception as e:
            logger.error(f"Error processing task: {e}")
            # Ensure lock is released even on unexpected errors
            if domain:
                self.redis_client.delete(f"LEARNING_IN_PROGRESS:{domain}")

    def parse_llm_response(self, response: str) -> tuple[str | None, str | None]:
        """Split the LLM response into adapter code and test code."""
        if "# --- TEST CODE ---" in response:
            parts = response.split("# --- TEST CODE ---")
            return parts[0].strip(), parts[1].strip()
        return response.strip(), None

    def validate_code(
        self,
        domain: str,
        adapter_code: str,
        test_code: str | None,
        raw_html: str,
        url: str,
        retry_count: int = 0,
        adapter_type: str = "extraction",
    ) -> bool:
        """Validate the generated code using AST and basic checks."""
        import ast
        from types import ModuleType

        max_retries = 2
        base_class_name = (
            "DiscoveryAdapter" if adapter_type == "discovery" else "ExtractionAdapter"
        )

        try:
            # 1. AST Validation
            ast.parse(adapter_code)
            if test_code:
                ast.parse(test_code)

            # 2. Basic content checks
            if base_class_name not in adapter_code:
                logger.error(
                    f"Generated code for {domain} does not inherit {base_class_name}"
                )
                return False

            # 3. Runtime Verification (Instantiation)
            # We execute in a temporary module to avoid polluting sys.modules
            module_name = f"dynamic_adapter_{domain.replace('.', '_')}"
            module = ModuleType(module_name)

            # Inject base classes into the module namespace
            from adapters.adapters.base import DiscoveryAdapter, ExtractionAdapter

            if adapter_type == "discovery":
                module.__dict__["DiscoveryAdapter"] = DiscoveryAdapter
                base_class = DiscoveryAdapter
            else:
                module.__dict__["ExtractionAdapter"] = ExtractionAdapter
                base_class = ExtractionAdapter

            # Execute the code in the module's namespace
            exec(adapter_code, module.__dict__)

            # Find the adapter class
            adapter_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, base_class)
                    and attr is not base_class
                ):
                    adapter_class = attr
                    break

            if not adapter_class:
                logger.error(
                    f"No {base_class_name} subclass found in generated code for"
                    f" {domain}"
                )
                return False

            # Try to instantiate
            adapter_instance = adapter_class()
            logger.info(f"Successfully instantiated adapter for {domain}")

            # 4. Runtime Verification
            if adapter_type == "discovery":
                result = adapter_instance.get_job_links(raw_html, url)  # type: ignore
                if not isinstance(result, list):
                    logger.error(
                        f"get_job_links() for {domain} returned"
                        f" {type(result)}, expected list"
                    )
                    return False
                next_page = adapter_instance.get_next_page_links(raw_html, url)  # type: ignore
                if not isinstance(next_page, list):
                    logger.error(
                        f"get_next_page_links() for {domain} returned"
                        f" {type(next_page)}, expected list"
                    )
                    return False
            else:
                result = adapter_instance.extract(raw_html, url)  # type: ignore
                if not isinstance(result, dict):
                    logger.error(
                        f"extract() for {domain} returned {type(result)}, expected dict"
                    )
                    return False
                if not result:
                    logger.warning(
                        f"extract() for {domain} returned an empty dictionary"
                    )

            logger.info(f"Successfully verified methods for {domain}")

            # 5. Runtime Verification (LLM-generated Tests)
            if test_code:
                if self.run_generated_tests(domain, adapter_code, test_code):
                    logger.info(f"Successfully ran generated tests for {domain}")
                else:
                    logger.error(f"Generated tests failed for {domain}")
                    return False

        except (SyntaxError, Exception) as e:
            logger.error(f"Validation failed for {domain}: {e}")
            if retry_count < max_retries:
                logger.info(
                    f"Retrying generation for {domain} (attempt {retry_count + 1})"
                )
                return self.retry_generation(domain, raw_html, str(e), retry_count + 1)
            return False

        return True

    def retry_generation(
        self,
        domain: str,
        raw_html: str,
        error_message: str,
        retry_count: int,
        adapter_type: str = "extraction",
    ) -> bool:
        """Attempt to fix the generated code by feeding error back to LLM."""
        with open(os.path.join("adapters", "adapters", "base.py")) as f:
            base_code_full = f.read()
        with open(os.path.join("adapters", "adapters", "base_test.py")) as f:
            test_base_code_full = f.read()

        llm_model = LLMModel()
        # In a real implementation, we would provide the previous code and the error
        # For this slice, we simulate a retry by calling generate_adapter again.
        logger.info(f"Retrying generation for {domain} with error: {error_message}")

        generated_response = llm_model.generate_adapter(
            domain, raw_html, adapter_type, base_code_full, test_base_code_full
        )

        adapter_code, test_code = self.parse_llm_response(generated_response)
        if not adapter_code:
            return False

        url = f"https://{domain}"  # Default URL for retry
        return self.validate_code(
            domain, adapter_code, test_code, raw_html, url, retry_count, adapter_type
        )

    def run_generated_tests(
        self, domain: str, adapter_code: str, test_code: str
    ) -> bool:
        """Run the generated pytest tests in a temporary file."""
        import subprocess
        import tempfile

        safe_domain = domain.replace(".", "_")
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter_path = os.path.join(tmpdir, f"adapter_{safe_domain}.py")
            test_path = os.path.join(tmpdir, f"test_{safe_domain}.py")

            with open(adapter_path, "w") as f:
                f.write(adapter_code)

            # Prepend import for the adapter in the test code
            # We assume the LLM might need to import the class it just wrote
            # but it might also just write it in the same file or use relative imports.
            # To be safe, we'll try to make the adapter available.
            full_test_code = (
                f"import sys\nimport os\nsys.path.insert(0, '{tmpdir}')\n"
                f"from adapter_{safe_domain} import *\n\n{test_code}"
            )

            with open(test_path, "w") as f:
                f.write(full_test_code)

            try:
                # Run pytest on the temporary test file.
                # Use -v for verbose output and --rootdir to avoid project config.
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", test_path],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                if result.returncode != 0:
                    logger.error(
                        f"Pytest failed for {domain}:\n{result.stdout}\n{result.stderr}"
                    )
                    return False

                return True
            except Exception as e:
                logger.error(f"Error running pytest for {domain}: {e}")
                return False

    def save_and_commit(
        self,
        domain: str,
        adapter_code: str,
        test_code: str | None,
        adapter_type: str = "extraction",
    ):
        """Save the generated code to disk and commit to git."""
        safe_domain = domain.replace(".", "_")
        adapter_prefix = "discovery" if adapter_type == "discovery" else "extraction"
        adapter_path = os.path.join(
            "adapters", "adapters", f"{safe_domain}_{adapter_prefix}_v1.py"
        )
        test_path = os.path.join(
            "adapters", "adapters", f"{safe_domain}_{adapter_prefix}_v1_test.py"
        )

        with open(adapter_path, "w") as f:
            f.write(adapter_code)

        if test_code:
            with open(test_path, "w") as f:
                f.write(test_code)

        logger.info(f"Saved adapter to {adapter_path}")

        branch_name = f"feature/{adapter_prefix}-adapter-{safe_domain}-v1"
        try:
            os.system(f"git checkout -b {branch_name}")
            os.system(f"git add {adapter_path} {test_path if test_code else ''}")
            os.system(
                f'git commit -m "F Add generated {adapter_prefix} adapter for {domain}"'
            )
            logger.info(f"Committed changes to branch {branch_name}")
        except Exception as e:
            logger.error(f"Failed to commit changes for {domain}: {e}")


if __name__ == "__main__":
    worker = LLMWorker()
    worker.run()
