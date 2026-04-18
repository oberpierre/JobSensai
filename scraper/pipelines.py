import json
import logging
import time
import uuid

import redis

from scraper.items import RawJobItem


class BronzeLayerPipeline:
    """
    Pushes items and run events to Redis for asynchronous processing.
    """

    def __init__(self, redis_host, redis_port):
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_client = None
        self.run_id = str(uuid.uuid4())
        self.logger = logging.getLogger(__name__)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            redis_host=crawler.settings.get("REDIS_HOST", "localhost"),
            redis_port=crawler.settings.get("REDIS_PORT", 6379),
        )

    def open_spider(self, spider):
        self.redis_client = redis.Redis(host=self.redis_host, port=self.redis_port)

        # Signal Start of Run
        event = {
            "type": "START_RUN",
            "run_id": self.run_id,
            "spider_name": spider.name,
            "timestamp": time.time(),
        }
        self.redis_client.lpush("raw_job_items", json.dumps(event))
        self.logger.info(f"Started Scraper Run ID: {self.run_id} (Pushed to Redis)")

    def close_spider(self, spider):
        # Signal End of Run
        event = {
            "type": "END_OF_RUN",
            "run_id": self.run_id,
            "spider_name": spider.name,
            "timestamp": time.time(),
        }
        self.redis_client.lpush("raw_job_items", json.dumps(event))
        self.logger.info(f"Ended Scraper Run ID: {self.run_id} (Pushed to Redis)")

    def process_item(self, item, spider):
        if not isinstance(item, RawJobItem):
            return item

        # Serialize item for Redis
        data = dict(item)
        # Handle non-serializable fields if any (Scrapy Item is usually fine)

        event = {"type": "ITEM", "run_id": self.run_id, "item": data}

        try:
            self.redis_client.lpush("raw_job_items", json.dumps(event))
        except Exception as e:
            self.logger.error(f"Failed to push item to Redis: {e}")

        return item
