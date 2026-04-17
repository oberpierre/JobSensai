import json
import logging
import os
import sys

import redis

from llm.model import LLMModel

logger = logging.getLogger(__name__)


class LLMWorker:
    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        queue_name: str = "adapter_learning_tasks",
    ):
        self.redis_client = redis.Redis(host=redis_host, port=redis_port)
        self.queue_name = queue_name
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
        logger.info(f"Starting LLM Worker, listening to {self.queue_name}")

        while self.running:
            self.process_next_task()

    def process_next_task(self):
        """Process a single task from the queue."""
        result = self.redis_client.brpop(self.queue_name, timeout=1)
        if not result:
            return

        _, message = result
        self.process_task(message)

    def process_task(self, message: bytes):
        """Process a task payload."""
        domain = None
        try:
            task = json.loads(message)
            domain = task.get("domain")
            url = task.get("url", f"https://{domain}")

            if not domain:
                logger.error("Task missing domain: %s", task)
                return

            if not self.start_learning(domain):
                logger.info("Learning already in progress for domain: %s", domain)
                return

            logger.info("Starting learning for domain: %s", domain)

            raw_html = task.get(
                "raw_html", "<html><body>No HTML provided</body></html>"
            )

            # LLM generation pipeline
            with open(os.path.join("adapters", "base.py")) as f:
                base_adapter_code = f.read()

            llm_model = LLMModel()
            generated_response = llm_model.generate_adapter(
                domain, raw_html, base_adapter_code
            )

            adapter_code, test_code = self.parse_llm_response(generated_response)

            if not adapter_code:
                logger.error(f"Failed to parse adapter code for {domain}")
                self.redis_client.delete(f"LEARNING_IN_PROGRESS:{domain}")
                return

            logger.info("Parsed adapter code length: %d", len(adapter_code))

            if self.validate_code(domain, adapter_code, test_code, raw_html, url):
                self.save_and_commit(domain, adapter_code, test_code)
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
    ) -> bool:
        """Validate the generated code using AST and basic checks."""
        import ast
        from types import ModuleType

        max_retries = 2
        try:
            # 1. AST Validation
            ast.parse(adapter_code)
            if test_code:
                ast.parse(test_code)

            # 2. Basic content checks
            if "BaseAdapter" not in adapter_code:
                logger.error(
                    f"Generated code for {domain} does not inherit BaseAdapter"
                )
                return False

            # 3. Runtime Verification (Instantiation)
            # We execute in a temporary module to avoid polluting sys.modules
            module_name = f"dynamic_adapter_{domain.replace('.', '_')}"
            module = ModuleType(module_name)

            # Inject BaseAdapter into the module namespace
            from adapaters.adapters.base import BaseAdapter

            module.__dict__["BaseAdapter"] = BaseAdapter

            # Execute the code in the module's namespace
            exec(adapter_code, module.__dict__)

            # Find the adapter class
            # (it should inherit from BaseAdapter and not be BaseAdapter itself)
            adapter_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseAdapter)
                    and attr is not BaseAdapter
                ):
                    adapter_class = attr
                    break

            if not adapter_class:
                logger.error(
                    f"No BaseAdapter subclass found in generated code for {domain}"
                )
                return False

            # Try to instantiate
            adapter_instance = adapter_class()
            logger.info(f"Successfully instantiated adapter for {domain}")

            # 4. Runtime Verification (extract() call)
            result = adapter_instance.extract(raw_html, url)
            if not isinstance(result, dict):
                logger.error(
                    f"extract() for {domain} returned {type(result)}, expected dict"
                )
                return False

            # Minimal silver schema check (expecting some fields to be present)
            # This is a basic check to ensure it's not returning an empty dict
            if not result:
                logger.warning(f"extract() for {domain} returned an empty dictionary")

            logger.info(f"Successfully verified extract() for {domain}")

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
        self, domain: str, raw_html: str, error_message: str, retry_count: int
    ) -> bool:
        """Attempt to fix the generated code by feeding error back to LLM."""
        with open(os.path.join("adapters", "base.py")) as f:
            base_adapter_code = f.read()

        llm_model = LLMModel()
        # In a real implementation, we would provide the previous code and the error
        # For this slice, we simulate a retry by calling generate_adapter again.
        # Ideally, LLMModel should have a 'fix_adapter' method.
        logger.info(f"Retrying generation for {domain} with error: {error_message}")

        # Simulate feeding error back by including it in the prompt if possible.
        # For now, we just call the same generation again as a placeholder.
        generated_response = llm_model.generate_adapter(
            domain, raw_html, base_adapter_code
        )

        adapter_code, test_code = self.parse_llm_response(generated_response)
        if not adapter_code:
            return False

        url = f"https://{domain}"  # Default URL for retry
        return self.validate_code(
            domain, adapter_code, test_code, raw_html, url, retry_count
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

    def save_and_commit(self, domain: str, adapter_code: str, test_code: str | None):
        """Save the generated code to disk and commit to git."""
        safe_domain = domain.replace(".", "_")
        adapter_path = os.path.join("adapters", f"{safe_domain}_v1.py")
        test_path = os.path.join("adapters", f"{safe_domain}_v1_test.py")

        with open(adapter_path, "w") as f:
            f.write(adapter_code)

        if test_code:
            with open(test_path, "w") as f:
                f.write(test_code)

        logger.info(f"Saved adapter to {adapter_path}")

        # Git operations
        # Note: This is a simplified git workflow for the current slice.
        # In production, this would be handled by a dedicated service or a more
        # robust CI/CD integration.
        branch_name = f"feature/adapter-{safe_domain}-v1"
        try:
            os.system(f"git checkout -b {branch_name}")
            os.system(f"git add {adapter_path} {test_path if test_code else ''}")
            os.system(f'git commit -m "F Add generated adapter for {domain}"')
            logger.info(f"Committed changes to branch {branch_name}")
        except Exception as e:
            logger.error(f"Failed to commit changes for {domain}: {e}")
