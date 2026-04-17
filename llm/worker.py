import json
import logging
import os

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
        try:
            task = json.loads(message)
            domain = task.get("domain")

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
                return

            logger.info("Parsed adapter code length: %d", len(adapter_code))

            if self.validate_code(domain, adapter_code, test_code, raw_html):
                self.save_and_commit(domain, adapter_code, test_code)
                self.complete_learning(domain)
            else:
                logger.error(f"Validation failed for domain: {domain}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode task message: {e}")
        except Exception as e:
            logger.error(f"Error processing task: {e}")

    def parse_llm_response(self, response: str) -> tuple[str | None, str | None]:
        """Split the LLM response into adapter code and test code."""
        if "# --- TEST CODE ---" in response:
            parts = response.split("# --- TEST CODE ---")
            return parts[0].strip(), parts[1].strip()
        return response.strip(), None

    def validate_code(
        self, domain: str, adapter_code: str, test_code: str | None, raw_html: str
    ) -> bool:
        """Validate the generated code using AST and basic checks."""
        import ast

        try:
            ast.parse(adapter_code)
            if test_code:
                ast.parse(test_code)
        except SyntaxError as e:
            logger.error(f"Syntax error in generated code for {domain}: {e}")
            return False

        if "BaseAdapter" not in adapter_code:
            logger.error(f"Generated code for {domain} does not inherit BaseAdapter")
            return False

        return True

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
