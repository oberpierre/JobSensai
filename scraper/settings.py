# See https://docs.scrapy.org/en/latest/topics/settings.html#project-settings
import os

LOG_LEVEL = "INFO"

BOT_NAME = "jobsensai"
USER_AGENT = "JobSensaiBot/1.0 (+https://github.com/oberpierre/JobSensai)"
ROBOTSTXT_OBEY = True
ROBOTSTXT_USER_AGENT = "JobSensaiBot"
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 10.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

# Off by default as in production, a scheduled run is expected to be a fresh pod,
# so the cache is written and never read. Opt in by setting SCRAPY_HTTPCACHE.
HTTPCACHE_ENABLED = os.getenv("SCRAPY_HTTPCACHE", "").lower() in {"1", "true", "yes"}
HTTPCACHE_EXPIRATION_SECS = 86400  # 1 day
# Absolute so Scrapy's data_path() skips joining under .scrapy: the image's
# non-root user can't create that directory under workdir /app.
HTTPCACHE_DIR = "/tmp/jobsensai-httpcache"
HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

ITEM_PIPELINES = {
    "scraper.pipelines.BronzeLayerPipeline": 300,
}

# Redis
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
