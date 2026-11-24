#!/usr/bin/env bash
# Fails when a loaded image exceeds its uncompressed size budget in MB, which
# means it gained a dependency or an interpreter file it did not need.
set -euo pipefail

budgets=(
  "jobsensai-crawler:3000"
  "jobsensai-bronze-worker:130"
  "jobsensai-silver-worker:160"
  "jobsensai-web:150"
)

fail=0
for budget in "${budgets[@]}"; do
  image="${budget%%:*}:latest"
  limit_mb="${budget##*:}"
  size_mb=$(( $(docker image inspect --format '{{.Size}}' "$image") / 1000000 ))
  echo "$image: ${size_mb} MB (budget ${limit_mb} MB)"
  if [ "$size_mb" -gt "$limit_mb" ]; then
    fail=1
  fi
done
exit "$fail"
