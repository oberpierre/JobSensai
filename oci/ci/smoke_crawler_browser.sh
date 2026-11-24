#!/usr/bin/env bash
# Launches Chromium in the loaded crawler image through its own Playwright
# driver. The crawler's log marker fires before any browser exists, so this is
# what proves the base's browser stack works.
set -uo pipefail

python3_path=/app/main.runfiles/rules_python++python+python_3_12_x86_64-unknown-linux-gnu/bin/python3

# A bare -c script gets none of the stub's sys.path setup, hence the glob.
read -r -d '' script <<'PY'
import glob, sys
sys.path[:0] = glob.glob("/app/main.runfiles/*/site-packages")
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_content('<a href="/job">job</a>')
    assert page.locator("a").count() == 1
    browser.close()
print("chromium launched")
PY

out=$(timeout 60 docker run --rm --network none --entrypoint "$python3_path" \
  jobsensai-crawler:latest -c "$script" 2>&1)
echo "$out"
if ! grep -q "chromium launched" <<<"$out"; then
  echo "crawler image could not launch Chromium"
  exit 1
fi
