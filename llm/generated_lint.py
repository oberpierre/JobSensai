"""Brings generated Python up to the checks the repo's commit hook runs."""

import logging
import subprocess
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

RUFF_COMMAND: tuple[str, ...] = (
    "bazel",
    "run",
    "--noshow_progress",
    "--",
    "@aspect_rules_lint//format:ruff",
)


def lint_generated(
    repo_root: Path,
    staged: Sequence[str],
    ruff_command: Sequence[str] = RUFF_COMMAND,
) -> tuple[bool, str]:
    """Fix what ruff can in place, then report whether the commit hook's checks pass."""
    files = [str(repo_root / p) for p in staged if p.endswith(".py")]
    if not files:
        return True, ""
    config = str(repo_root / ".ruff.toml")

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*ruff_command, *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    try:
        run("check", "--fix", "--config", config, *files)
        run("format", "--force-exclude", "--config", config, *files)
        lint = run("check", "--config", config, *files)
        fmt = run(
            "format", "--check", "--force-exclude", "--diff", "--config", config, *files
        )
    except OSError as exc:
        logger.error("Could not run ruff: %s", exc)
        return False, f"Could not run ruff: {exc}"

    passed = lint.returncode == 0 and fmt.returncode == 0
    output = lint.stdout + lint.stderr + fmt.stdout + fmt.stderr
    if not passed:
        logger.error(
            "Generated Python fails the commit hook's checks:\n%s", output[-2000:]
        )
    return passed, output
