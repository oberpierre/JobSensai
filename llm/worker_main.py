#!/usr/bin/env python3
"""Entrypoint for the adapter-learning worker.

Usage:
    bazel run //llm:worker
"""

from llm.worker import main

if __name__ == "__main__":
    main()
