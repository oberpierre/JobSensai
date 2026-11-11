"""Brings generated Python up to the checks the repo's commit hook runs."""

import logging
import subprocess
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

# The commit hook's own commands, so the gate cannot drift from what it enforces.
RUFF_COMMAND: tuple[str, ...] = (
    "bazel",
    "run",
    "--noshow_progress",
    "--",
    "@aspect_rules_lint//format:ruff",
)
FORMAT_COMMAND: tuple[str, ...] = (
    "bazel",
    "run",
    "--noshow_progress",
    "--",
    "//tools/format",
)
FORMAT_CHECK_COMMAND: tuple[str, ...] = (
    "bazel",
    "run",
    "--noshow_progress",
    "--",
    "//tools/format:format.check",
)


def lint_generated(
    repo_root: Path,
    staged: Sequence[str],
    ruff_command: Sequence[str] = RUFF_COMMAND,
    format_command: Sequence[str] = FORMAT_COMMAND,
    format_check_command: Sequence[str] = FORMAT_CHECK_COMMAND,
) -> tuple[bool, str]:
    """Fix what ruff can in place, then report whether the formatting check passes.

    What ruff cannot fix is left in the files for the gate's own lint verdict.
    """
    relative = [p for p in staged if p.endswith(".py")]
    if not relative:
        return True, ""
    absolute = [str(repo_root / p) for p in relative]
    config = str(repo_root / ".ruff.toml")

    def run(command: Sequence[str], *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*command, *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    # Ruff is handed absolute paths, because `bazel run` executes from the runfiles
    # tree, whereas the format targets resolve paths against the workspace.
    fixes = (
        (
            ruff_command,
            ("check", "--fix", "--exit-zero", "--config", config, *absolute),
        ),
        (format_command, tuple(relative)),
    )
    try:
        for command, args in fixes:
            fixed = run(command, *args)
            if fixed.returncode != 0:
                output = fixed.stdout + fixed.stderr
                logger.error("Could not fix generated Python:\n%s", output[-2000:])
                return False, f"Could not fix generated Python:\n{output}"
        checked = run(format_check_command, *relative)
    except OSError as exc:
        logger.error("Could not run ruff: %s", exc)
        return False, f"Could not run ruff: {exc}"

    output = checked.stdout + checked.stderr
    if checked.returncode != 0:
        logger.error("Generated Python is not formatted:\n%s", output[-2000:])
    return checked.returncode == 0, output
