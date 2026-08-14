import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from publisher.publisher import Publisher

_BASENAME = "acme_com_extraction_v1"


def _ok(stdout: str = "https://github.com/acme/repo/pull/7\n"):
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def _publish(passed: bool):
    pub = Publisher(repo_root=Path("/repo"))
    return pub.publish(
        basename=_BASENAME,
        adapter_class="AcmeComExtractionAdapter",
        domain="acme.com",
        adapter_type="extraction",
        passed=passed,
        test_output="TEST LOG OUTPUT",
    )


def _commands(mock_run) -> list[tuple]:
    return [tuple(call.args[0]) for call in mock_run.call_args_list]


class TestPublisher(unittest.TestCase):
    @patch("publisher.publisher.subprocess.run")
    def test_green_opens_a_ready_pr_and_returns_url(self, mock_run):
        mock_run.return_value = _ok()
        url = _publish(passed=True)
        self.assertEqual(url, "https://github.com/acme/repo/pull/7")

        cmds = _commands(mock_run)
        # Branch is taken off the base branch, one branch per adapter.
        self.assertIn(
            ("git", "checkout", "-B", f"feature/adapter-{_BASENAME}", "main"), cmds
        )
        # Only this adapter's three paths are staged — never BUILD or other adapters.
        add = next(c for c in cmds if c[:2] == ("git", "add"))
        self.assertEqual(
            add,
            (
                "git",
                "add",
                "--",
                f"adapters/adapters/{_BASENAME}.py",
                f"adapters/adapters/{_BASENAME}_test.py",
                f"adapters/adapters/fixtures/{_BASENAME}",
            ),
        )
        # Green commit carries a validated (^) risk and the agent trailer.
        commit = next(c for c in cmds if c[:2] == ("git", "commit"))
        self.assertTrue(any(part.startswith("^ F") for part in commit), commit)
        self.assertIn("Co-Authored-By: JobSensai Agent <agent@jobsensai.dev>", commit)
        # A ready PR: gh pr create WITHOUT --draft.
        gh = next(c for c in cmds if c[0] == "gh")
        self.assertNotIn("--draft", gh)

    @patch("publisher.publisher.subprocess.run")
    def test_red_opens_a_draft_pr_with_broken_risk(self, mock_run):
        mock_run.return_value = _ok()
        _publish(passed=False)

        cmds = _commands(mock_run)
        commit = next(c for c in cmds if c[:2] == ("git", "commit"))
        self.assertTrue(any(part.startswith("@ F") for part in commit), commit)
        gh = next(c for c in cmds if c[0] == "gh")
        self.assertIn("--draft", gh)

    @patch("publisher.publisher.subprocess.run")
    def test_returns_none_when_a_git_step_fails(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, ["git", "push"])
        self.assertIsNone(_publish(passed=True))

    @patch("publisher.publisher.subprocess.run")
    def test_clone_is_left_on_the_base_branch(self, mock_run):
        """The runner is long-lived: the next adapter branches off main, not this."""
        mock_run.return_value = _ok()
        _publish(passed=True)

        cmds = _commands(mock_run)
        self.assertEqual(cmds[-1], ("git", "checkout", "main"))

    @patch("publisher.publisher.subprocess.run")
    def test_base_branch_is_restored_even_when_publishing_fails(self, mock_run):
        # Every git call raises, so the restore must not turn that into an
        # escaping error.
        mock_run.side_effect = subprocess.CalledProcessError(1, ["git", "push"])
        self.assertIsNone(_publish(passed=True))
        self.assertEqual(_commands(mock_run)[-1], ("git", "checkout", "main"))


class TestHasExistingPr(unittest.TestCase):
    def setUp(self):
        self.pub = Publisher(repo_root=Path("/repo"))

    @patch("publisher.publisher.subprocess.run")
    def test_true_when_gh_reports_a_pr(self, mock_run):
        mock_run.return_value = _ok('[{"number":7}]\n')
        self.assertIs(self.pub.has_existing_pr(_BASENAME), True)

        cmd = _commands(mock_run)[0]
        self.assertEqual(cmd[:2], ("gh", "pr"))
        self.assertIn(f"feature/adapter-{_BASENAME}", cmd)
        # Includes closed PRs count
        self.assertIn("all", cmd)

    @patch("publisher.publisher.subprocess.run")
    def test_false_on_an_empty_list(self, mock_run):
        mock_run.return_value = _ok("[]\n")
        self.assertIs(self.pub.has_existing_pr(_BASENAME), False)

    @patch("publisher.publisher.subprocess.run")
    def test_none_when_gh_fails(self, mock_run):
        """Undeterminable must be distinct from absent so the caller can fail closed."""
        mock_run.side_effect = subprocess.CalledProcessError(1, ["gh"])
        self.assertIsNone(self.pub.has_existing_pr(_BASENAME))

    @patch("publisher.publisher.subprocess.run")
    def test_none_when_gh_is_not_installed(self, mock_run):
        mock_run.side_effect = FileNotFoundError("gh")
        self.assertIsNone(self.pub.has_existing_pr(_BASENAME))

    def test_branch_name_is_derived_from_the_basename(self):
        """The branch is the idempotency key, so it must match what publish() pushes."""
        self.assertEqual(self.pub.branch_for(_BASENAME), f"feature/adapter-{_BASENAME}")


if __name__ == "__main__":
    unittest.main()
