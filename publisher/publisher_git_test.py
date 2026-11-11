import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from publisher.publisher import Publisher

_BASENAME = "x_index_v1"
_BRANCH = f"feature/mapping-{_BASENAME}"
_PATHS = [
    f"adapters/adapters/mappings/{_BASENAME}.json",
    f"adapters/adapters/{_BASENAME}_test.py",
    f"adapters/adapters/fixtures/{_BASENAME}",
]
_ARTIFACT_FILES = [
    f"adapters/adapters/mappings/{_BASENAME}.json",
    f"adapters/adapters/{_BASENAME}_test.py",
    f"adapters/adapters/fixtures/{_BASENAME}/index.json",
]
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Tester",
    "GIT_AUTHOR_EMAIL": "tester@example.test",
    "GIT_COMMITTER_NAME": "Tester",
    "GIT_COMMITTER_EMAIL": "tester@example.test",
}


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _commit(cwd: Path, name: str, message: str) -> str:
    (cwd / name).write_text(f"{message}\n")
    _git(cwd, "add", name)
    _git(cwd, "commit", "-q", "-m", message)
    return _git(cwd, "rev-parse", "HEAD")


class TestPublishWithRealGit(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, _GIT_ENV)
        env.start()
        self.addCleanup(env.stop)
        gh = patch.object(
            Publisher,
            "_gh",
            return_value=subprocess.CompletedProcess(
                [], 0, stdout="https://example.test/pull/1\n", stderr=""
            ),
        )
        gh.start()
        self.addCleanup(gh.stop)
        existing = patch.object(Publisher, "has_existing_pr", return_value=False)
        existing.start()
        self.addCleanup(existing.stop)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.origin = root / "origin.git"
        self.clone = root / "clone"
        seed = root / "seed"
        _git(root, "init", "-q", "--bare", "-b", "main", str(self.origin))

        _git(root, "clone", "-q", str(self.origin), str(seed))
        _git(seed, "checkout", "-q", "-b", "base")
        _commit(seed, "notes.txt", "B0")
        _git(seed, "push", "-q", "origin", "base")
        _git(seed, "checkout", "-q", "-b", _BRANCH)
        self.stale = _commit(seed, "stale.txt", "S")
        _git(seed, "push", "-q", "origin", _BRANCH)
        _git(seed, "checkout", "-q", "base")

        _git(root, "clone", "-q", "-b", "base", str(self.origin), str(self.clone))
        _git(
            self.clone,
            "config",
            "remote.origin.fetch",
            "+refs/heads/main:refs/remotes/origin/main",
        )

        self.b1 = _commit(seed, "remote.txt", "B1")
        _git(seed, "push", "-q", "origin", "base")

        self.l1 = _commit(self.clone, "local.txt", "L1")
        with (self.clone / "notes.txt").open("a") as notes:
            notes.write("appended\n")
        (self.clone / "staged.txt").write_text("staged\n")
        _git(self.clone, "add", "staged.txt")

        for rel in _ARTIFACT_FILES:
            target = self.clone / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("generated\n")

    def _publish(self) -> str | None:
        return Publisher(repo_root=self.clone, base_branch="base").publish(
            basename=_BASENAME,
            domain="x.test",
            adapter_type="index",
            passed=True,
            test_output="OK",
            model_name="m",
            paths=_PATHS,
            kind="mapping",
        )

    def test_the_pr_branch_starts_at_the_remote_base_and_replaces_a_stale_attempt(
        self,
    ):
        self.assertEqual(self._publish(), "https://example.test/pull/1")

        self.assertEqual(_git(self.origin, "rev-parse", f"{_BRANCH}^"), self.b1)
        changed = _git(self.origin, "diff", "--name-only", self.b1, _BRANCH)
        self.assertEqual(sorted(changed.splitlines()), sorted(_ARTIFACT_FILES))
        self.assertEqual(_git(self.clone, "rev-parse", "--abbrev-ref", "HEAD"), "base")
        self.assertEqual(_git(self.clone, "rev-parse", "HEAD"), self.l1)
        self.assertEqual(
            _git(self.clone, "diff", "--cached", "--name-only"), "staged.txt"
        )
        self.assertIn("appended", (self.clone / "notes.txt").read_text())
        for path in _PATHS:
            self.assertFalse((self.clone / path).exists(), path)

    def test_a_rejected_commit_leaves_nothing_of_the_artifact_staged(self):
        hooks = self.clone.parent / "hooks"
        hooks.mkdir()
        hook = hooks / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        _git(self.clone, "config", "core.hooksPath", str(hooks))

        self.assertIsNone(self._publish())

        self.assertEqual(_git(self.clone, "rev-parse", "--abbrev-ref", "HEAD"), "base")
        self.assertEqual(_git(self.clone, "rev-parse", "HEAD"), self.l1)
        self.assertEqual(
            _git(self.clone, "diff", "--cached", "--name-only"), "staged.txt"
        )
        for path in _PATHS:
            self.assertTrue((self.clone / path).exists(), path)
        self.assertEqual(_git(self.origin, "rev-parse", _BRANCH), self.stale)


if __name__ == "__main__":
    unittest.main()
