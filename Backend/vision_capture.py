#!/usr/bin/env python3
"""
vision_capture.py — Screen capture via Playwright page screenshot.

Uses the existing Playwright page object that join_meet.py already owns.
No new capture tool, no X11 dependencies — the bot already runs Chrome inside
the container, so we simply screenshot the page we already have.

Called by vision_worker.py in a tight async loop.
"""

import base64
from typing import Optional


async def capture_frame(page) -> Optional[bytes]:
    """
    Takes a screenshot of the currently visible Playwright viewport.

    Returns:
        PNG bytes on success.
        None on failure (page closed, navigation in progress, etc.).

    Notes:
        - full_page=False: only the visible 1280x720 viewport, not the scrollable page.
          Faster and more relevant — we care about what the candidate is presenting now.
        - timeout=5000ms: long enough to survive a momentary page load, short enough
          not to stall the vision loop.
    """
    try:
        if page is None or page.is_closed():
            return None

        screenshot_bytes = await page.screenshot(
            type="png",
            full_page=False,
            timeout=5000,
        )
        return screenshot_bytes

    except Exception as e:
        # Don't crash the worker — just skip this frame silently
        # (common during page navigation, Meet reconnects, etc.)
        print(f"[VISION_CAPTURE] ⚠️  Screenshot failed: {e}", flush=True)
        return None


def to_base64(image_bytes: bytes) -> str:
    """Convert raw PNG bytes to base64 string for OpenAI vision API."""
    return base64.b64encode(image_bytes).decode("utf-8")