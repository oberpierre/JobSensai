#!/usr/bin/env python3
"""uvicorn entrypoint.

Usage:
    bazel run //api:server
"""

import os

import uvicorn

from api.app import create_app


def server_config() -> tuple[str, int]:
    """The port is the only override; the host is always the wildcard bind a
    published container port needs to be reachable at all."""
    return "0.0.0.0", int(os.environ.get("API_PORT", "8000"))


def main() -> None:
    host, port = server_config()
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
