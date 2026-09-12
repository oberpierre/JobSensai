"""The lifecycle of one adapter-learning task, from queue message to published PR."""

import json
import logging
from urllib.parse import urlsplit

from llm.adapter_files import _adapter_names, staged_paths
from llm.learning_errors import TruthAgentUnreadable, UnlearnablePage

logger = logging.getLogger(__name__)


class LearningTaskRunner:
    """Runs one learning task against the Redis client, publisher, lease methods and
    per-type learning flows its host provides.
    """

    def process_task(self, message: bytes, queue_name: str) -> bool:
        """Route a learning task to the generation flow for its adapter type.

        Returns True when the task was pushed back onto its queue rather than acted
        on, so the caller can back off instead of hammering the queue.
        """
        # Resolve the adapter type up-front so the learning lock is namespaced by it
        # and stays reachable for cleanup in the except blocks below.
        adapter_type = "discovery" if "discovery" in queue_name else "extraction"
        # One binding feeds both the already-published check and the publish that
        # follows it, so the two branch names cannot drift apart.
        kind = "adapter"
        domain: str | None = None
        lock_key: str | None = None
        # Bound early like domain and lock_key: the UnlearnablePage except clause
        # below reads it, and it must exist even if the try raises before the
        # line that would otherwise assign it.
        url: str | None = None

        try:
            task = json.loads(message)

            domain = task.get("domain") or None
            if not domain:
                url = task.get("url", "")
                domain = urlsplit(url).netloc or None
            if not domain:
                logger.error("Task has no resolvable domain: %s", task)
                return False

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
                return False

            # The lease only dedups tasks racing in one scrape run. Across runs the
            # board still has no adapter until its PR merges and the scraper redeploys,
            # so every crawl re-enqueues, because GitHub is what knows the work
            # is already done.
            names = _adapter_names(domain, adapter_type)
            pr_state = self.publisher.has_existing_pr(names.basename, kind=kind)
            if pr_state is None:
                # Undeterminable is not "already published": the task would be lost
                # for good, so it goes back on the queue instead of being dropped.
                logger.error(
                    "Could not determine PR state for %s, returning task to %s",
                    names.basename,
                    queue_name,
                )
                if not self.publisher.can_publish():
                    # A credential revoked mid-run would otherwise requeue every
                    # later task forever with no further check.
                    logger.error("Cannot publish: run `gh auth login` and restart")
                    self.running = False
                    self._publish_unavailable = True
                # Release before requeueing: lpush-then-release reopens the window a
                # second consumer could pop the message through before the lease clears.
                self.release_learning(domain, adapter_type)
                self.redis_client.lpush(queue_name, message)
                return True
            if pr_state is True:
                logger.info("Adapter %s already has a PR, skipping", names.basename)
                self.release_learning(domain, adapter_type)
                return False

            url = task.get("url") or f"https://{domain}"

            if adapter_type == "discovery":
                names, model_name = self._learn_discovery(domain, url, raw_html)
            else:
                names, model_name = self._learn_extraction(domain, url, raw_html)

            passed, test_output = self._run_adapter_tests()
            logger.info(
                "%s adapter for %s: snapshot test %s",
                adapter_type,
                domain,
                "passed" if passed else "FAILED (left for review)",
            )

            # Red runs publish too as a draft PR carrying the failure for manual fixing.
            pr_url = self.publisher.publish(
                basename=names.basename,
                domain=domain,
                adapter_type=adapter_type,
                passed=passed,
                test_output=test_output,
                model_name=model_name,
                paths=staged_paths(names.basename),
                kind=kind,
            )
            if pr_url:
                logger.info("Opened PR for %s: %s", names.basename, pr_url)
            else:
                # No PR exists, so the next crawl's gh check finds nothing and retries.
                logger.error(
                    "Publish failed for %s. Retrying with next crawl.", names.basename
                )
            self.release_learning(domain, adapter_type)
            return False

        except TruthAgentUnreadable as exc:
            # Unlike UnlearnablePage, the same page may well yield a readable answer
            # next time, since a truncated or wrongly-shaped generation is what the
            # loop already requeues elsewhere for an undeterminable has_existing_pr.
            logger.error(
                "Truth agent reply unreadable for domain=%s url=%s adapter_type=%s: %s",
                domain,
                url,
                adapter_type,
                exc,
            )
            self.release_learning(domain, adapter_type)
            self.redis_client.lpush(queue_name, message)
            return True

        except UnlearnablePage as exc:
            # Dropped rather than requeued: the same page yields the same answer, so
            # a requeue only spins, and the next crawl re-enqueues the board anyway.
            logger.error(
                "Learned nothing for domain=%s url=%s adapter_type=%s: %s",
                domain,
                url,
                adapter_type,
                exc,
            )
            # Held to its TTL rather than released: this path opens no PR, so nothing
            # else stops every other queued task for this board from each running a
            # full truth-agent call before being dropped the same way.
            return False
        except json.JSONDecodeError as exc:
            logger.error("Failed to decode task message: %s", exc)
            return False
        except Exception as exc:
            logger.error("Unexpected error processing task: %s", exc, exc_info=True)
            if lock_key:
                self.redis_client.delete(lock_key)
            return False
