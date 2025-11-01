# JobSensai

A smart LLM-powered job board that helps you find jobs and optimize your CV to match job descriptions.

## Prerequisites

- **Bazelisk** (Bazel version manager): Follow the [installation instructions](https://github.com/bazelbuild/bazelisk#installation) to install Bazelisk, which manages Bazel versions automatically.

## Quick Start

### Installing dependencies

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

This project uses Bazel as its build system with Python 3.12. The `llm` module is the core component that will power the AI features for job matching and CV optimization.

## License

Licensed under the Business Source License 1.1. See [LICENSE](LICENSE) for details.

For commercial licensing inquiries, please contact the project maintainer.

