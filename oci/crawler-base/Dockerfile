# Chromium's headless shell and the system libraries it needs, at the revision
# playwright==1.55.0 expects, and nothing else. The crawler image layers its
# Bazel-built app, interpreter and Playwright driver on top.
# The version below must equal requirements_lock.txt's, so bump both in one PR.
FROM debian:bookworm-slim@sha256:e67eeead736ff7bbe258ef088bff683635c561b1fcfefad0806c1df4ab49ce0e

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# The Python and pip here only run `playwright install`, so they are removed in
# the same layer. The browser's own dependencies were installed explicitly, which
# keeps them out of reach of the autoremove.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates python3 python3-venv \
    && python3 -m venv /tmp/playwright \
    && /tmp/playwright/bin/pip install --no-cache-dir playwright==1.55.0 \
    && /tmp/playwright/bin/playwright install --with-deps --only-shell chromium \
    && rm -rf /tmp/playwright /root/.cache \
    && apt-get purge -y --auto-remove python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /ms-playwright
