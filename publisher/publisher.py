"""Publish a generated adapter to a branch and a draft/ready pull request.

Stages a single adapter's files, commits them (Arlo notation whose risk marks red vs
green), pushes, and opens a PR. Draft PR when the adapter's tests are red, ready when
green. Assumes the agent machine's clone is on a clean base branch and that ``git`` push
credentials and an authenticated ``gh`` are already configured.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Marks machine-generated commits; reserved for the agent runner.
AGENT_TRAILER = "Co-Authored-By: JobSensai Agent <agent@jobsensai.dev>"


class Publisher:
    def __init__(
        self,
        repo_root: Path,
        base_branch: str = "main",
        remote: str = "origin",
        trailer: str = AGENT_TRAILER,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.base_branch = base_branch
        self.remote = remote
        self.trailer = trailer

    def publish(
        self,
        *,
        basename: str,
        adapter_class: str,
        domain: str,
        adapter_type: str,
        passed: bool,
        test_output: str,
    ) -> str | None:
        """Branch, commit the adapter's files, push, and open a PR; return its URL.

        The PR is a draft when *passed* is False. Only this adapter's three paths are
        staged, so one branch introduces exactly one adapter. Returns None if any
        git/gh step fails (logged, never raised into the caller). The clone is left on
        the base branch either way, so a failed publish cannot strand the runner.
        """
        branch = f"feature/adapter-{basename}"
        paths = [
            f"adapters/adapters/{basename}.py",
            f"adapters/adapters/{basename}_test.py",
            f"adapters/adapters/fixtures/{basename}",
        ]
        # Risk token mirrors the gate: validated (^) when green, broken (@) when red.
        risk = "^" if passed else "@"
        subject = f"{risk} F Add a generated {adapter_type} adapter for {domain}"
        try:
            self._git("checkout", "-b", branch, self.base_branch)
            self._git("add", "--", *paths)
            self._git("commit", "-m", subject, "-m", self.trailer)
            self._git("push", "-u", self.remote, branch)
            return self._open_pr(branch, domain, adapter_type, passed, test_output)
        except subprocess.CalledProcessError as exc:
            logger.error("Publish failed for %s: %s", basename, exc)
            return None
        finally:
            self._restore_base_branch()

    def _restore_base_branch(self) -> None:
        """Return the clone to the base branch after publishing.

        The agent runner is long-lived and publishes one adapter per task; without this
        the next task would branch off the previous adapter's branch and its PR would
        carry both adapters.
        """
        try:
            self._git("checkout", self.base_branch)
        except subprocess.CalledProcessError as exc:
            logger.error("Could not return the clone to %s: %s", self.base_branch, exc)

    def _open_pr(
        self,
        branch: str,
        domain: str,
        adapter_type: str,
        passed: bool,
        test_output: str,
    ) -> str:
        title = f"Add {adapter_type} adapter for {domain}"
        state = "passing" if passed else "FAILING - needs review"
        body = (
            f"Auto-generated {adapter_type} adapter for `{domain}`.\n\n"
            f"Adapter test suite: **{state}**\n\n"
            f"```\n{test_output[-3000:]}\n```\n"
        )
        args = [
            "pr",
            "create",
            "--base",
            self.base_branch,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        ]
        if not passed:
            args.append("--draft")
        return self._gh(*args).stdout.strip()

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return self._run("git", *args)

    def _gh(self, *args: str) -> subprocess.CompletedProcess:
        return self._run("gh", *args)

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        logger.info("publisher$ %s", " ".join(args))
        return subprocess.run(
            args, cwd=str(self.repo_root), capture_output=True, text=True, check=True
        )
