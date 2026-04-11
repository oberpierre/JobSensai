import json
import logging
import os
import signal
import time
from dataclasses import dataclass
from typing import Optional

import redis


# Configuration
@dataclass
class SilverWorkerConfig:
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", 6379))
    queue_name: str = "silver_generation_tasks"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class SilverWorker:
    """Barebones Silver Worker that consumes silver_generation_tasks."""

    def __init__(self, config: SilverWorkerConfig):
        self.config = config
        self.should_exit = False
        self.redis: Optional[redis.Redis] = None

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        logger.info(f"Received signal {signum}. Shutting down safely...")
        self.should_exit = True

    def setup(self):
        """Initialize connections."""
        logger.info(
            f"Connecting to Redis: {self.config.redis_host}:{self.config.redis_port}..."
        )
        self.redis = redis.Redis(
            host=self.config.redis_host,
            port=self.config.redis_port,
            decode_responses=True,
        )
        logger.info("Silver Worker setup complete.")

    def run(self):
        self.setup()
        logger.info(f"Worker started. Listening on queue '{self.config.queue_name}'...")

        while not self.should_exit:
            try:
                # brpop returns a tuple (key, value)
                result = self.redis.brpop(self.config.queue_name, timeout=1)

                if not result:
                    continue

                _, message = result
                self.process_message(message)

            except redis.exceptions.ConnectionError:
                logger.error("Redis connection lost. Retrying in 5 seconds...")
                time.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                time.sleep(1)

        logger.info("Silver Worker shutdown complete.")

    def process_message(self, message: str):
        try:
            data = json.loads(message)
            url = data.get("url")

            if not url:
                logger.warning("Message missing URL, skipping.")
                return

            logger.info(f"Processing silver generation task for URL: {url}")

            # Slice 1 just acknowledges the task.
            # Slice 2 will implement domain-to-adapter matching.

        except json.JSONDecodeError:
            logger.error(f"Failed to decode message: {message[:100]}...")
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)


if __name__ == "__main__":
    config = SilverWorkerConfig()
    worker = SilverWorker(config)
    worker.run()
