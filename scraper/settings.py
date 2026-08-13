# See https://docs.scrapy.org/en/latest/topics/settings.html#project-settings
import os

LOG_LEVEL = "INFO"

HTTPCACHE_ENABLED = True
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
