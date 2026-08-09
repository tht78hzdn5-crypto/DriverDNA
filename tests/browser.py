"""Shared Chromium discovery for the Playwright-gated UI tests.

Every browser test module needs to know, at import time, whether a real
Chromium is available so it can skip cleanly when it isn't (CI's main
`pytest` job, most local dev machines). The previous approach hardcoded the
on-disk layout Playwright happened to use (`chromium-*/chrome-linux/chrome`)
in seven separate copies of `_find_chrome()`. Playwright's own installer
changed that layout (Chrome for Testing now unpacks to `chrome-linux64/`)
and every copy silently stopped matching — the CI guard step caught it
(`grep` for the skip reason, `exit 1`), but the job was non-blocking, so it
went unnoticed. Asking Playwright for its own browser's path, instead of
guessing where it put it, cannot drift out of sync with the installer again.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def chromium_executable() -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            path = Path(p.chromium.executable_path)
    except Exception:
        return None
    return str(path) if path.exists() else None
