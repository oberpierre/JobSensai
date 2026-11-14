"""The lifecycle of one adapter- or mapping-learning task, from queue message to PR."""

import json
import logging
from urllib.parse import urlsplit

from llm.adapter_files import _adapter_names, _mapping_names, staged_paths
from llm.learning_errors import TruthAgentUnreadable, UnlearnablePage
from llm.mapping_learning import budget_chars, learn_mapping
from llm.model import LLMModel, extraction_num_ctx, index_num_ctx

logger = logging.getLogger(__name__)


class LearningTaskRunner:
    """Runs one learning task against the Redis client, publisher, lease methods,
    per-type learning flows and llm_url its host provides.
    """

    def process_task(self, message: bytes, queue_name: str) -> bool:
        """Route a learning task to the generation flow for its artifact and type.

        Returns True when the task was pushed back onto its queue rather than acted
        on, so the caller can back off instead of hammering the queue.
        """
        # Resolved up-front so the learning lock is namespaced by it and stays
        # reachable for cleanup in the except blocks below, on every path.
        adapter_type = "discovery" if "discovery" in queue_name else "extraction"
        # One binding feeds both the already-published check and the publish that
        # follows it, so the two branch names cannot drift apart.
        kind = "adapter"
        mapping_type: str | None = None
        # mapping_type on the mapping path, adapter_type otherwise: every lease
        # site reads this one binding rather than picking its own.
        lease_type = adapter_type
        domain: str | None = None
        lock_key: str | None = None
        # Bound early like domain and lock_key: the UnlearnablePage except clause
        # below reads it, and it must exist even if the try raises before the
        # line that would otherwise assign it.
        url: str | None = None

        try:
            task = json.loads(message)
            document: dict | list | None = None
            raw_html: str | None = None

            if "artifact" in task:
                # A JSON null is a present key with a wrong value, and must be
                # dropped here: task.get() would return None for this and for an
                # absent key alike, routing a null artifact to the adapter path.
                if task["artifact"] != "mapping":
                    logger.error(
                        "Dropping mapping task on %s: artifact=%r is not 'mapping'"
                        " (domain=%s url=%s)",
                        queue_name,
                        task.get("artifact"),
                        task.get("domain"),
                        task.get("url"),
                    )
                    return False

                # Never the netloc fallback below: the registry looks up by
                # hostname, and a raw netloc can carry a port the registry
                # never registered a mapping under.
                domain = task.get("domain") or None
                if not domain:
                    logger.error(
                        "Dropping mapping task on %s: no domain (url=%s)",
                        queue_name,
                        task.get("url"),
                    )
                    return False

                url = task.get("url") or None
                if not url:
                    logger.error(
                        "Dropping mapping task on %s: no url (domain=%s)",
                        queue_name,
                        domain,
                    )
                    return False

                body = task.get("body") or None
                if not body:
                    logger.error(
                        "Dropping mapping task on %s: no body (domain=%s url=%s)",
                        queue_name,
                        domain,
                        url,
                    )
                    return False

                if queue_name == "discovery_learning_tasks":
                    mapping_type = "index"
                elif queue_name == "extraction_learning_tasks":
                    mapping_type = "detail"
                else:
                    # LLMWorker consumes only those two queues, so this is a
                    # guard against a caller's bug rather than a real path.
                    logger.error(
                        "Dropping mapping task for %s: %s is not a learning queue",
                        domain,
                        queue_name,
                    )
                    return False

                # Knowable without inspecting the task, so it runs here rather
                # than at the top of process_task, where it would drop every
                # HTML discovery and extraction task too on a misconfigured knob.
                knob = (
                    "INDEX_NUM_CTX" if mapping_type == "index" else "EXTRACTION_NUM_CTX"
                )
                budget = budget_chars(mapping_type)
                if budget <= 0:
                    logger.error(
                        "Dropping mapping task for %s: %s yields a budget of %d "
                        "chars; fix %s",
                        domain,
                        knob,
                        budget,
                        knob,
                    )
                    return False

                # The data axis, separate from the configuration checks above:
                # a producer that already parsed the body lands here rather than
                # in the generic handler, which would report "Unexpected error".
                try:
                    document = json.loads(body)
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.error(
                        "Dropping mapping task for %s: body is not JSON: %s",
                        domain,
                        exc,
                    )
                    return False
                if not isinstance(document, (dict, list)):
                    logger.error(
                        "Dropping mapping task for %s: body is %s, not an object "
                        "or array",
                        domain,
                        type(document).__name__,
                    )
                    return False

                kind = "mapping"
                lease_type = mapping_type
            else:
                domain = task.get("domain") or None
                if not domain:
                    url = task.get("url", "")
                    domain = urlsplit(url).netloc or None
                if not domain:
                    logger.error("Task has no resolvable domain: %s", task)
                    return False

                raw_html = (
                    task.get("html")
                    or task.get("html_content")
                    or task.get("raw_html")
                    or "<html><body>No HTML provided</body></html>"
                )
                url = task.get("url") or f"https://{domain}"
                lease_type = adapter_type

            lock_key = f"LEARNING_IN_PROGRESS:{lease_type}:{domain}"
            logger.info("Processing %s task for domain: %s", lease_type, domain)

            if not self.start_learning(domain, lease_type):
                logger.info("Learning already in progress for domain: %s", domain)
                return False

            # The lease only dedups tasks racing in one scrape run. Across runs the
            # board still has no adapter until its PR merges and the scraper redeploys,
            # so every crawl re-enqueues, because GitHub is what knows the work
            # is already done.
            names = (
                _mapping_names(domain, mapping_type)
                if kind == "mapping"
                else _adapter_names(domain, adapter_type)
            )
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
                self.release_learning(domain, lease_type)
                self.redis_client.lpush(queue_name, message)
                return True
            if pr_state is True:
                logger.info("Adapter %s already has a PR, skipping", names.basename)
                self.release_learning(domain, lease_type)
                return False

            if kind == "mapping":
                num_ctx = (
                    index_num_ctx() if mapping_type == "index" else extraction_num_ctx()
                )
                model = LLMModel(base_url=self.llm_url, num_ctx=num_ctx)
                names, model_name = learn_mapping(
                    model, domain, url, document, mapping_type
                )
            elif adapter_type == "discovery":
                names, model_name = self._learn_discovery(domain, url, raw_html)
            else:
                names, model_name = self._learn_extraction(domain, url, raw_html)
            resolved_type = mapping_type if kind == "mapping" else adapter_type

            staged = staged_paths(names.basename, kind)
            passed, test_output = self._run_adapter_tests(staged)
            logger.info(
                "%s %s for %s: gate %s",
                resolved_type,
                kind,
                domain,
                "passed" if passed else "FAILED (left for review)",
            )

            # Red runs publish too as a draft PR carrying the failure for manual fixing.
            pr_url = self.publisher.publish(
                basename=names.basename,
                domain=domain,
                adapter_type=resolved_type,
                passed=passed,
                test_output=test_output,
                model_name=model_name,
                paths=staged,
                kind=kind,
            )
            if pr_url:
                logger.info("Opened PR for %s: %s", names.basename, pr_url)
            else:
                # No PR exists, so the next crawl's gh check finds nothing and retries.
                logger.error(
                    "Publish failed for %s. Retrying with next crawl.", names.basename
                )
            self.release_learning(domain, lease_type)
            return False

        except TruthAgentUnreadable as exc:
            # Unlike UnlearnablePage, the same page may well yield a readable answer
            # next time, since a truncated or wrongly-shaped generation is what the
            # loop already requeues elsewhere for an undeterminable has_existing_pr.
            if kind == "mapping":
                logger.error(
                    "Truth agent reply unreadable for domain=%s url=%s artifact=%s"
                    " mapping_type=%s: %s",
                    domain,
                    url,
                    kind,
                    mapping_type,
                    exc,
                )
            else:
                logger.error(
                    "Truth agent reply unreadable for domain=%s url=%s"
                    " adapter_type=%s: %s",
                    domain,
                    url,
                    adapter_type,
                    exc,
                )
            self.release_learning(domain, lease_type)
            self.redis_client.lpush(queue_name, message)
            return True

        except UnlearnablePage as exc:
            # Dropped rather than requeued: the same page yields the same answer, so
            # a requeue only spins, and the next crawl re-enqueues the board anyway.
            if kind == "mapping":
                logger.error(
                    "Learned nothing for domain=%s url=%s artifact=%s"
                    " mapping_type=%s: %s",
                    domain,
                    url,
                    kind,
                    mapping_type,
                    exc,
                )
            else:
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
