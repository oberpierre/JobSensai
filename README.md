# JobSensai &middot; [![Build & Test](https://github.com/oberpierre/JobSensai/actions/workflows/build.yaml/badge.svg)](https://github.com/oberpierre/JobSensai/actions/workflows/build.yaml)

A smart LLM-powered job board that helps you find jobs and optimize your CV to match job descriptions.

## Prerequisites

### Required
- **[Ollama](https://ollama.com/download/)**: Required for the LLM components.
- **[Docker Desktop](https://www.docker.com/products/docker-desktop/)**: Required for database infrastructure (PostgreSQL, Redis) and Devcontainers.

### Manual Setup Only (Not required for Devcontainer)
- **[Bazel](https://bazel.build/install)**:
  - Recommended: Use [Bazelisk](https://github.com/bazelbuild/bazelisk?tab=readme-ov-file#installation) to manage Bazel versions automatically.
  - Refer to [.bazelversion](./.bazelversion) for the exact version to use.
- **[Aspect CLI](https://github.com/aspect-build/aspect-cli/releases)**: Enhances Bazel with better developer experience and plugins.
  - MacOS: `brew install aspect-build/aspect/aspect`

> **Note:** Python and dependencies are managed by Bazel. You do **not** need to manually install Python or manage virtual environments to run the application.

## Development Setup

### Option 1: Devcontainer (Recommended)

This project is configured with a **Dev Container** for VS Code, which provides a pre-configured environment with all necessary tools (Bazel, Python, etc.) installed.

1. Install the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) in VS Code.
2. Open the project folder in VS Code.
3. Click **"Reopen in Container"** when prompted, or run the command via the Command Palette (`Cmd+Shift+P` -> `Dev Containers: Reopen in Container`).

### Option 2: Manual Setup

1. Install all [Prerequisites](#prerequisites) listed above.
2. Start the infrastructure services (PostgreSQL + Redis):
    ```bash
    docker-compose -f .build/docker-compose.yml up -d
    ```

## Environment Configuration

Before running the application, you need to set up your environment variables:

1. **Copy the example environment file:**
    ```bash
    cp .env.example .env
    ```

2. **Review and adjust the values in `.env` as needed:**
    - **For Devcontainer users:** The default values in `.env.example` are pre-configured for the containerized environment and should work out of the box.
    - **For Manual Setup users:** Update the following settings to connect to your local infrastructure:
        - Uncomment and use `POSTGRES_HOST=localhost` and `POSTGRES_PORT=20001`
        - Uncomment and use `REDIS_HOST=localhost` and `REDIS_PORT=20002`
        - Set `OLLAMA_HOST=localhost` (instead of `host.docker.internal`)

3. **Key configuration sections:**
    - **Database:** PostgreSQL connection settings
    - **Redis:** Cache and task queue connection settings
    - **LLM (Ollama):** Connection to the Ollama service for LLM features
    - **Scraper settings:** Control download delays and concurrent requests

> **Note:** The `.env` file is required for all services to run successfully.

## Managing Dependencies

Python dependencies are managed via `requirements.in`.

1. **Update dependencies:** Edit [`requirements.in`](./requirements.in).
2. **Lock dependencies:** Run the following command to update `requirements_lock.txt`:
    ```bash
    bazel run //:requirements.update
    ```

## Running the Application

### 1. LLM Service
The LLM service handles CV optimization and job analysis.

**Prerequisite:** Ensure Ollama is running (`ollama serve`) and you have pulled the required model.
> **Note:** The default model is `qwen3:4b` (see `llm/model.py`). You can customize this by modifying the `LLMModel` initialization.

```bash
ollama pull qwen3:4b # Pull the model(s) you intend to use
```

**Run the service:**
```bash
bazel run //llm:main
```

### 2. Scraper Service
The scraper aggregates job listings from various sources.

**Run the scraper:**
```bash
bazel run //scraper:main
```

**Run the scraper worker:**
```bash
bazel run //scraper:worker
```

## Code Quality

We enforce code quality using **Ruff** for both formatting and linting, integrated via Bazel with [aspect_rules_lint](https://github.com/aspect-build/rules_lint). This approach provides incremental, cacheable builds and hermetic test environments.

### Configuration
- **`.ruff.toml`**: Central Ruff configuration
- **`tools/lint/linters.bzl`**: Defines the aspect rules and test macro for linters
- **`tools/lint/BUILD.bazel`**: Instantiates lint tests for specific targets
- **`tools/format/BUILD.bazel`**: Defines the aspect rules and test macros for formatters

### Commands

**Formatting:**
```bash
aspect format             # Auto-format all files in workspace
bazel run format          # Auto-format all files in workspace
bazel run format.check    # Check formatting without modifying files
aspect test format_tests  # Run formatting checks as tests (CI-friendly)
```

**Linting with Aspect CLI (Recommended):**
```bash
aspect lint                   # Lint all targets recursively
aspect lint //llm:main        # Lint specific target
aspect lint --fix //llm:main  # Auto-fix linting issues where possible
```

**Linting as Bazel Tests:**
```bash
aspect test lint_tests        # Run all lint tests defined in root BUILD.bazel
aspect test //tools/lint/...  # Run all lint tests in tools/lint
```

### Adding Linting to New Targets

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

> **Important:** Lint tests use Bazel aspects and require explicit target references—they do **not** support glob patterns like `//...`. Always update `srcs` when adding new code to ensure comprehensive linting or use `aspect lint` instead.

## License

Licensed under the Business Source License 1.1. See [LICENSE](LICENSE) for details.

For commercial licensing inquiries, please contact the project maintainer.

