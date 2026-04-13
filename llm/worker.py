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
            generated_code = llm_model.generate_adapter(
                domain, raw_html, base_adapter_code
            )

            logger.info("Generated adapter code length: %d", len(generated_code))

            # TODO: Validate and save generated code

            # self.complete_learning(domain) # Only call when successful

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode task message: {e}")
        except Exception as e:
            logger.error(f"Error processing task: {e}")
