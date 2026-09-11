import logging
from urllib.parse import urlsplit
from uuid import UUID

from scraper.database import SessionLocal
from scraper.models import IngestEvent

logger = logging.getLogger(__name__)

# Groups a source_url with no authority component for a screen. Cannot
# collide with a real hostname, parentheses not being legal in one.
_INGEST_DOMAIN_UNKNOWN = "(unknown)"

# A screen groups by reason. Detail only distinguishes cases inside one
# group, so it is capped rather than carrying an arbitrary message.
_INGEST_DETAIL_MAX = 500


def record_ingest_failure(
    *,
    stage: str,
    reason: str,
    source_url: str,
    posting_url: str | None = None,
    start_url_id: UUID | None = None,
    detail: str | None = None,
) -> None:
    """Record a refused posting as diagnostics, in its own session.

    A caller reaching this point has already decided not to write the
    posting, so a failure here must not raise back into that caller:
    everything, including deriving domain from a source_url that came off a
    Bronze row rather than from this process, runs inside the guard.
    """
    try:
        hostname = urlsplit(source_url).hostname
        domain = hostname or _INGEST_DOMAIN_UNKNOWN
        truncated_detail = detail[:_INGEST_DETAIL_MAX] if detail else detail

        db = SessionLocal()
        try:
            db.add(
                IngestEvent(
                    domain=domain,
                    start_url_id=start_url_id,
                    source_url=source_url,
                    posting_url=posting_url,
                    stage=stage,
                    reason=reason,
                    detail=truncated_detail,
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.error("Failed to record ingest failure", exc_info=True)
