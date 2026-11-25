#!/usr/bin/env bash
# Fails when the crawler's pinned base was built from a different Dockerfile
# than the one checked out, meaning the base was edited and not republished, or
# republished and not pinned.
set -euo pipefail

dockerfile="$(dirname "$0")/../crawler-base/Dockerfile"
expected=$(sha256sum "$dockerfile" | cut -d' ' -f1)
actual=$(docker image inspect jobsensai-crawler:latest \
  --format '{{index .Config.Labels "jobsensai.crawler-base.dockerfile-sha256"}}')

if [ "$actual" != "$expected" ]; then
  echo "The pinned crawler base was built from Dockerfile sha256 '${actual}'," \
    "but oci/crawler-base/Dockerfile is '${expected}'."
  echo "Run the 'Crawler base image' workflow on this branch, then pin the digest" \
    "from its summary in MODULE.bazel."
  exit 1
fi
echo "Crawler base matches oci/crawler-base/Dockerfile (${expected})."
