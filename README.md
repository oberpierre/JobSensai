# JobSensai &middot; [![Build & Test](https://github.com/oberpierre/JobSensai/actions/workflows/build.yaml/badge.svg)](https://github.com/oberpierre/JobSensai/actions/workflows/build.yaml)

A smart LLM-powered job board that helps you find jobs and optimize your CV to match job descriptions.

## Prerequisites

- **[Install Aspect CLI](https://github.com/aspect-build/aspect-cli)** providing the `aspect` binary with improvements like the `aspect lint` command for linting.

> **Note:** On MacOS you may install Aspect CLI via Homebrew: `brew install aspect-build/aspect/aspect`

## Quick Start

### Installing dependencies

First update your dependencies in [`requirements.in`](./requirements.in), then run the following command to update the requirement lock file:

```bash
bazel run //:requirements.update
```

### Build the project

```bash
bazel build //llm:main
```

### Run the application

```bash
bazel run //llm:main
```

## Development

This project uses Bazel as its build system with Python 3.12. 

**Modules:**
- `llm/`: LLM integration for CV optimization and job analysis
- `scraper/`: Web scraping infrastructure for job aggregation (see `scraper/README.md`)

**Infrastructure:**
```bash
# Start PostgreSQL + Redis for development
docker-compose up -d
```

### Code Quality

We enforce code quality using **Ruff** for both formatting and linting, integrated via Bazel with [aspect_rules_lint](https://github.com/aspect-build/rules_lint). This approach provides incremental, cacheable builds and hermetic test environments.

#### Architecture Overview

**Configuration:**
- **`.ruff.toml`**: Central Ruff configuration
- **`tools/lint/linters.bzl`**: Defines the aspect rules and test macro for linters
- **`tools/lint/BUILD.bazel`**: Instantiates lint tests for specific targets
- **`tools/format/BUILD.bazel`**: Defines the aspect rules and test macros for formatters

**Key Design Decisions:**
1. **Formatting**: Runs workspace-wide without explicit `srcs` (uses `no_sandbox=True`) for simplicity, assuming fast formatting
2. **Linting**: Requires explicit target declarations per the Bazel aspect model to ensure incremental builds and caching

#### Commands

**Formatting:**
```bash
bazel run format         # Auto-format all files in workspace
bazel run format.check   # Check formatting without modifying files
aspect test format_tests  # Run formatting checks as tests (CI-friendly)
```

**Linting with Aspect CLI (Recommended):**
```bash
aspect lint //...             # Lint all targets recursively
aspect lint //llm:main        # Lint specific target
aspect lint --fix //llm:main  # Auto-fix linting issues where possible
```

**Linting as Bazel Tests:**
```bash
aspect test lint_tests        # Run all lint tests defined in root BUILD.bazel
aspect test //tools/lint/...  # Run all lint tests in tools/lint
```

#### Adding Linting to New Targets

When you create new targets, add them to the corresponding linting suite:

1. **Add target to the appropriate lint test** in `tools/lint/BUILD.bazel`:
   ```bazel
   ruff_test(
       name = "ruff_test",
       srcs = [
           "//llm:main",
           "//your_new_package:target",  # Add here (for a target to be linted with ruff in this example)
       ],
   )
   ```

2. When creating a new test suite, ensure you extend the `lint_tests` suite in root `BUILD.bazel`
   ```bazel
    test_suite(
        name = "lint_tests",
        tests = [
            "//tools/lint:ruff_test",
            "//tools/lint:your_new_lint_test",  # Add here
        ],
    )
   ```

> **Important:** Lint tests use Bazel aspects and require explicit target references—they do **not** support glob patterns like `//...`. Always update `srcs` when adding new code to ensure comprehensive linting.

## License

Licensed under the Business Source License 1.1. See [LICENSE](LICENSE) for details.

For commercial licensing inquiries, please contact the project maintainer.

