"""Linting aspects for the project.

This file defines:
1. ruff: A Bazel aspect that runs Ruff linter on Python targets
2. ruff_test: A macro that creates lint test rules using the ruff aspect

The aspect model allows Bazel to:
- Analyze dependencies transitively
- Cache lint results per target
- Run linting incrementally only on changed targets
"""

load("@aspect_rules_lint//lint:ruff.bzl", "lint_ruff_aspect")
load("@aspect_rules_lint//lint:lint_test.bzl", "lint_test")

# Ruff aspect configuration
# Runs Ruff linter with config from .ruff.toml on Python targets
ruff = lint_ruff_aspect(
    binary = Label("@aspect_rules_lint//lint:ruff_bin"),
    configs = [
        Label("@//:.ruff.toml"),  # Central Ruff configuration
    ],
)

# Macro to create lint tests using the ruff aspect
# Usage in BUILD.bazel: ruff_test(name = "...", srcs = ["//target:label"])
ruff_test = lint_test(aspect = ruff)