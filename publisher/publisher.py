"""Publish a generated artifact to a branch and a draft/ready pull request.

Stages the paths it is given, commits them (Arlo notation whose risk marks red vs
green), pushes, and opens a PR. Draft PR when the artifact's tests are red, ready when
green. The checkout may hold other work, because each publish branches off the remote
base and commits only its own paths. Assumes ``git`` push credentials and an
authenticated ``gh`` are already configured.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Marks machine-generated commits. Reserved for the agent runner.
# GitHub attributes a co-author by matching this address, so the domain has to be one
# we hold: anyone who can register it can verify the address and claim every one of
# these commits, retroactively.
AGENT_TRAILER = "Co-Authored-By: JobSensai Agent <agent@jobsensai.oberpierre.com>"


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

    def branch_for(self, basename: str, kind: str) -> str:
        """The branch one artifact publishes on."""
        return f"feature/{kind}-{basename}"

    def has_existing_pr(self, basename: str, kind: str) -> bool | None:
        """Whether a PR was ever opened for *basename*, None when undeterminable.

        Closed PRs count. A human closing a generated adapter is a decision not to take
        it, and since generation is deterministic enough to produce the same adapter
        again, re-opening it would re-submit work that was already rejected.

        None (GitHub unreachable, unauthenticated, rate-limited) is deliberately
        distinct from False: unknown fails open, so the caller requeues the task
        rather than dropping it.
        """
        branch = self.branch_for(basename, kind)
        try:
            result = self._gh(
                "pr",
                "list",
                "--head",
                branch,
                "--state",
                "all",
                "--json",
                "number",
                "--limit",
                "1",
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            logger.error("Could not determine PR state for %s: %s", branch, exc)
            return None
        return result.stdout.strip() not in ("", "[]")

    def can_publish(self) -> bool:
        """Whether gh is authenticated well enough to open a PR."""
        try:
            self._gh("auth", "status")
        except (subprocess.CalledProcessError, OSError):
            return False
        return True

    def log_base_state(self) -> None:
        """Log the current branch and how HEAD stands against the remote base."""
        try:
            current = self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        except (subprocess.CalledProcessError, OSError):
            current = "unknown"
        try:
            self._fetch_base()
            counts = self._git(
                "rev-list",
                "--left-right",
                "--count",
                f"{self.remote}/{self.base_branch}...HEAD",
            ).stdout.split()
            behind, ahead = (int(count) for count in counts)
            if not behind and not ahead:
                state = "in sync"
            elif not behind:
                state = f"ahead {ahead}"
            elif not ahead:
                state = f"behind {behind}"
            else:
                state = f"ahead {ahead}, behind {behind}"
        except (subprocess.CalledProcessError, OSError, ValueError):
            state = "unknown"
        logger.info(
            "Publishing against %s/%s from branch %s, HEAD vs %s/%s: %s",
            self.remote,
            self.base_branch,
            current,
            self.remote,
            self.base_branch,
            state,
        )

    def _fetch_base(self) -> None:
        """Bring the remote-tracking base up to date, whatever refspec the clone has."""
        self._git(
            "fetch",
            self.remote,
            f"+refs/heads/{self.base_branch}:refs/remotes/{self.remote}/{self.base_branch}",
        )

    def publish(
        self,
        *,
        basename: str,
        domain: str,
        adapter_type: str,
        passed: bool,
        test_output: str,
        model_name: str,
        paths: list[str],
        kind: str,
    ) -> str | None:
        """Branch, commit the given paths, push, and open a PR, returning its URL.

        The PR is opened as a draft when *passed* is False. One branch introduces
        exactly one artifact, whose files are exactly *paths*, because a pathspec
        that matches nothing makes `git add` fail rather than no-op. Returns None if
        any git/gh step fails (logged, not raised to the caller). A red commit skips
        the clone's hooks because they reject exactly the unfinished artifact a draft
        PR exists to carry. It branches off the freshly fetched remote base, so local
        commits and edits never reach the PR, and returns to the local base branch
        with its paths unstaged.
        """
        branch = self.branch_for(basename, kind)
        # Risk token mirrors the gate: validated (^) when green, broken (@) when red.
        risk = "^" if passed else "@"
        subject = f"{risk} F Add a generated {adapter_type} {kind} for {domain}"
        try:
            self._fetch_base()
            # -B resets an existing local branch: a run that died between branching and
            # pushing leaves one behind that no remote PR check can see.
            self._git("checkout", "-B", branch, f"{self.remote}/{self.base_branch}")
            self._git("add", "--", *paths)
            # The pathspec commits only the artifact even when something else is staged.
            commit = ["commit"] if passed else ["commit", "--no-verify"]
            self._git(*commit, "-m", subject, "-m", self.trailer, "--", *paths)
            # A remote branch with no PR is an earlier attempt whose PR never opened.
            # This commit does not descend from it, so a plain push would be rejected.
            # The recheck matters because another learner may have opened a PR since.
            existing = self.has_existing_pr(basename, kind)
            if existing is not False:
                logger.warning(
                    "Not pushing %s: GitHub %s",
                    branch,
                    "already has a PR for it"
                    if existing
                    else "could not say whether a PR exists for it",
                )
                return None
            self._git("push", "--force", "-u", self.remote, branch)
            return self._open_pr(
                branch, domain, adapter_type, passed, test_output, model_name, kind
            )
        except subprocess.CalledProcessError as exc:
            logger.error(
                "Publish failed for %s: %s\nstdout:\n%s\nstderr:\n%s",
                basename,
                exc,
                exc.stdout or "",
                exc.stderr or "",
            )
            return None
        finally:
            self._restore_base_branch(paths)

    def _restore_base_branch(self, paths: list[str]) -> None:
        """Return to the local base branch with this publish's paths unstaged."""
        try:
            self._git("checkout", self.base_branch)
        except subprocess.CalledProcessError as exc:
            logger.error(
                "Could not return the clone to %s: %s\n%s",
                self.base_branch,
                exc,
                exc.stderr or "",
            )
        # A rejected commit leaves the files staged, and a checkout carries staged
        # files along, so the operator's checkout would otherwise keep them staged.
        try:
            self._git("reset", "-q", "--", *paths)
        except subprocess.CalledProcessError as exc:
            logger.error(
                "Could not unstage %s: %s\n%s", " ".join(paths), exc, exc.stderr or ""
            )

    def _open_pr(
        self,
        branch: str,
        domain: str,
        adapter_type: str,
        passed: bool,
        test_output: str,
        model_name: str,
        kind: str,
    ) -> str:
        title = f"Add {adapter_type} {kind} for {domain}"
        state = "passing" if passed else "FAILING - needs review"
        body = (
            f"Auto-generated {adapter_type} {kind} for `{domain}`.\n\n"
            f"Test suite: **{state}**\n\n"
            f"Generated by `{model_name}`.\n\n"
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
