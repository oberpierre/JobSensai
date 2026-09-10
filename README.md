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
> **Note:** The default model is `qwen3-coder:30b` (see `llm/model.py`). Set the `OLLAMA_MODEL` environment variable to use a different one.

```bash
ollama pull qwen3-coder:30b # Pull the model(s) you intend to use
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

### 3. Adapter Learning Worker

The learning worker consumes the two adapter-learning queues from Redis, generates a parsing adapter with the LLM, gates it with `bazel test //adapters:adapter_test`, and opens a pull request for it. Unlike the services above it writes to your clone and pushes from it, so treat it as an operator task rather than something to leave running unattended.

**Prerequisites:**

- Ollama running with the model pulled, as in section 1.
- An authenticated `gh`. The worker runs `gh auth status` before it consumes anything and exits non-zero with `Cannot publish` when that fails, so a missing credential costs a restart rather than a half-finished run.
- **A clean clone on `main`.** Publishing runs `git checkout -B feature/adapter-<name> main` in the checkout you started it from, commits the generated adapter, pushes to `origin` and returns to `main`. Uncommitted work in that clone is at risk, and starting from another branch publishes against the wrong base.

**Run it:**

```bash
bazel run //llm:worker
```

It reads `.env` for Redis and Ollama exactly as the scraper does, and logs `Starting LLM Worker, listening on [...]` as soon as the `gh` check passes, so the absence of that line points at the credential rather than at Redis. The Redis client connects lazily, which means a wrong host or password surfaces a moment later on the first poll instead of at startup.

**With a different model:**

```bash
OLLAMA_MODEL=qwen3.8:27b-mlx bazel run //llm:worker
```

`bazel run` hands the binary your shell's environment, and `.env` is loaded without overriding what is already set, so a variable supplied this way wins over the file without editing it. That holds for every knob `.env.example` documents, not just this one.

**Against a remote Redis, keeping the password out of your shell history and out of `.env`:**

```bash
read -rs -p 'Redis password: ' REDIS_PASSWORD && export REDIS_PASSWORD && echo
export REDIS_USERNAME=<acl-user> REDIS_HOST=<host> REDIS_PORT=<port>
bazel run //llm:worker
```

`read -rs` prints nothing as you type, and history records only the `read` line rather than what you typed into it. Writing `REDIS_PASSWORD=... bazel run ...` as one line does the opposite, storing the password in history verbatim. The export lives as long as the shell, so run `unset REDIS_PASSWORD` when you are done with it. This keeps the value off your terminal and out of the file, though it stays readable in the process environment to anyone already on the machine as your user.

**While it runs:** a domain being learned is leased for 30 minutes by default, so a second task for the same board and adapter type is dropped rather than queued behind the first. A model slow enough to outlive that lease learns one domain twice. You may set the lease duration by setting `LEARNING_LEASE_TTL_SECONDS` in `.env` or the shell.

### 4. Database Migrations

`init_db`, run at startup by `scraper/worker.py` and `scraper/silver_worker.py`, applies the chain under `scraper/migrations/versions/` while holding a Postgres advisory lock, so several workloads starting at once serialise instead of racing. Authoring a revision is a separate step, through `scraper/migrations_cli.py`, behind `bazel run //scraper:migrate`.

**Generate a revision after changing a model in `scraper/models.py`:**

```bash
bazel run //scraper:migrate -- revision -m "add company size"
```

This never touches your own database. It builds a scratch one from the migration chain, diffs the models against that, writes the new file into `scraper/migrations/versions/`, and drops the scratch database whether or not the diff found anything. Review what it wrote, then run `aspect format` before committing it: autogenerate's raw output is unwrapped, and the `op.add_column(..., sa.Column(...))` boilerplate alone is enough to push essentially every generated line over this repo's limit, not just an unusual column or table name, which is a formatting gap rather than a broken tool. A **rename is always hand-written**: autogenerate has no notion of a rename, and renders one as a `drop_column` paired with an `add_column`, which loses the column's data rather than carrying it forward the way a real rename would.

**Check that the models and the migration chain still agree:**

```bash
bazel run //scraper:migrate -- check
```

Exits non-zero, naming the column or table it found, when a model changed with no matching revision. Nothing else in the build catches that gap. Both subcommands read `.env` for the same Postgres connection settings the rest of the scraper uses.

## Running it locally

The API and the built web frontend ship in one image, `jobsensai-web`, containing `//api:server` with the `//web:dist` build mounted as its SPA. Build and load it into the local Docker daemon:

```bash
bazel build //oci:web_image
bazel run //oci:web_load
```

The API only queries tables and never creates them. `init_db` lives in `scraper/worker.py` and `scraper/silver_worker.py`, so pointed at a Postgres that has never run either, it answers `500` with `relation "start_urls" does not exist`. Run the worker once against that Postgres first and stop it once it logs "Worker started", which it does after `init_db` and therefore after the tables exist:

```bash
bazel run //scraper:worker
```

That reads `.env` for its host, so it reaches whichever Postgres the setup above configured. Manual-setup readers need `docker-compose -f .build/docker-compose.yml up -d` running first, whereas the devcontainer already composes it.

Then run the image against that same Postgres:

```bash
docker run --rm -p 8000:8000 \
  -e POSTGRES_HOST=host.docker.internal \
  -e POSTGRES_PORT=20001 \
  jobsensai-web:latest
```

Open `http://localhost:8000`: the API answers under `/api`, and every other path serves the SPA. The image carries no `.env`, so any credential that is not the default in `.env.example` (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`) has to be passed as its own `-e` flag.

This devcontainer and Apple Silicon are both arm64, while the image is built for linux/amd64, so build and run it there only to inspect the image, not to serve traffic.

## Releasing

Pushing a tag matching `v*` is what deploys. Merging to `main` builds, tests and publishes the four images but does not deploy them, so nothing reaches the cluster until someone tags. The tag may sit on any branch, so a branch can be released before it merges.

One release run, in order: builds and tests everything, smoke-tests the four images, publishes them as `sha-<short>` and as the tag itself, deploys, then opens the GitHub release whose notes GitHub generates from the pull requests merged since the previous release.

```bash
git tag v1.2.0
git push origin v1.2.0
```

A tag whose name contains a hyphen, such as `v1.2.0-rc.1`, is published as a prerelease.

A failed deploy leaves the tag and the images in place with no release. Re-running the workflow from the Actions tab is the repair.

A published tag is cut once and never moved. The deployed image is named by the tag itself, so force-pushing a tag onto a different commit rebuilds and overwrites its images while the workload's image reference stays the same string, and a cluster that sees no change in that string keeps running what it already pulled. Cut a new version instead.

Keep the tag to `v`, digits and dots, with an optional hyphenated prerelease suffix. It becomes an image tag verbatim, so a character a registry rejects, `+` among them, fails the run only after the whole build and smoke-test suite has already passed.

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

### Git Hooks

The repository ships hooks in `.githooks/`. Git does not pick up a hooks directory on its own, so each clone points itself at this one once:

```bash
git config core.hooksPath .githooks
```

`pre-commit` formats and lints only what the commit touches: a formatting check over every staged file Prettier or Ruff knows how to format, `ruff check` over every staged Python file, and, whenever a `BUILD.bazel` is staged, a check that no Python target has been left out of `//tools/lint:ruff_test`. It does not run tests, because a hook slow enough to be worth bypassing stops being a hook.

`commit-msg` checks the message the commit is about to record.

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

> **Important:** Lint tests use Bazel aspects and require explicit target references, which means they do **not** support glob patterns like `//...`. Always update `srcs` when adding new code to ensure comprehensive linting or use `aspect lint` instead.

## License

Licensed under the Business Source License 1.1. See [LICENSE](LICENSE) for details.

For commercial licensing inquiries, please contact the project maintainer.

