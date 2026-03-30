#!/usr/bin/env python3
"""
setup_login.py — ONE-TIME Google login setup for the Interview Bot.

Run this ONCE after docker-compose up -d:
  docker exec -it int-avatar-bot python /app/setup_login.py

Then open noVNC at http://13.126.71.22:4003/vnc.html
Sign into Google with the bot's account (same account that generated token.json).
After login is detected, the script saves the session and exits.

All future bot sessions will copy this base profile — no re-login needed.
"""

import asyncio
import os
import shutil
import sys

from playwright.async_api import async_playwright

BASE_PROFILE = "/tmp/chrome-profile"
BACKUP_PROFILE = "/tmp/chrome-profile-backup"
LOGIN_TIMEOUT = 300   # seconds to wait for manual login (5 minutes)


async def main():
    os.environ["DISPLAY"] = ":99"
    os.environ["PULSE_SERVER"] = "unix:/var/run/pulse/native"

    print("=" * 60, flush=True)
    print("  🔐 INT Bot — Google Login Setup", flush=True)
    print("=" * 60, flush=True)
    print(f"\n[SETUP] Base profile path : {BASE_PROFILE}", flush=True)
    print(f"[SETUP] Login timeout     : {LOGIN_TIMEOUT}s", flush=True)

    # Clean old profile if it exists (fresh login)
    if os.path.exists(BASE_PROFILE):
        print(f"\n[SETUP] ⚠️  Existing profile found at {BASE_PROFILE}", flush=True)
        answer = input("[SETUP] Clear it and start fresh login? (y/n): ").strip().lower()
        if answer == "y":
            shutil.rmtree(BASE_PROFILE, ignore_errors=True)
            print("[SETUP] ✅ Old profile cleared.", flush=True)
        else:
            print("[SETUP] Keeping existing profile. Will verify login state.", flush=True)

    async with async_playwright() as p:
        print("\n[SETUP] 🌐 Opening Chrome in noVNC display...", flush=True)
        print("[SETUP] 👉 Open http://13.126.71.22:4003/vnc.html to see the browser.\n", flush=True)

        context = await p.chromium.launch_persistent_context(
            user_data_dir=BASE_PROFILE,
            headless=False,
            viewport={"width": 1280, "height": 720},
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
                "--disable-default-apps",
                "--window-size=1280,720",
            ],
        )

        page = await context.new_page()

        # Navigate to Google account page
        print("[SETUP] 🔗 Navigating to Google sign-in...", flush=True)
        await page.goto("https://accounts.google.com", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # Check if already logged in
        already_logged_in = await _check_logged_in(page)
        if already_logged_in:
            email = await _get_logged_in_email(page)
            print(f"\n[SETUP] ✅ Already logged in as: {email}", flush=True)
            print("[SETUP] ✅ Base profile is ready. No login needed.\n", flush=True)
            await _verify_meet_access(page)
            await context.close()
            _save_backup()
            print("\n[SETUP] 🎉 Setup complete! You can now run the bot.", flush=True)
            return

        # Not logged in — wait for manual login in noVNC
        print("[SETUP] ⚠️  Not logged in. Please log in via noVNC now.", flush=True)
        print(f"[SETUP] ⏳ Waiting up to {LOGIN_TIMEOUT}s for login...\n", flush=True)

        elapsed = 0
        while elapsed < LOGIN_TIMEOUT:
            await asyncio.sleep(5)
            elapsed += 5

            logged_in = await _check_logged_in(page)
            if logged_in:
                email = await _get_logged_in_email(page)
                print(f"\n[SETUP] ✅ Login detected! Logged in as: {email}", flush=True)
                break

            remaining = LOGIN_TIMEOUT - elapsed
            if elapsed % 30 == 0:
                print(f"[SETUP] ⏳ Still waiting... {remaining}s remaining. Log in via noVNC.", flush=True)
        else:
            print("\n[SETUP] ❌ Login timeout. Please re-run the script and try again.", flush=True)
            await context.close()
            sys.exit(1)

        # Verify Meet access
        await asyncio.sleep(3)
        await _verify_meet_access(page)

        print("\n[SETUP] 💾 Saving browser session...", flush=True)
        await context.close()
        await asyncio.sleep(2)

        _save_backup()

        print("\n[SETUP] ✅ Base profile saved successfully!", flush=True)
        print(f"[SETUP]    Location: {BASE_PROFILE}", flush=True)
        print(f"[SETUP]    Backup  : {BACKUP_PROFILE}", flush=True)
        print("\n[SETUP] 🎉 Setup complete!", flush=True)
        print("[SETUP]    Every new bot session will copy this profile.", flush=True)
        print("[SETUP]    You don't need to log in again unless cookies expire.\n", flush=True)


async def _check_logged_in(page) -> bool:
    """Returns True if a Google account is currently logged in."""
    try:
        current_url = page.url
        # If on accounts.google.com and not on signin page, likely logged in
        if "myaccount.google.com" in current_url:
            return True
        if "accounts.google.com" in current_url and "signin" not in current_url and "v3" not in current_url:
            # Check for account menu or avatar
            body = (await page.locator("body").inner_text(timeout=3000)).lower()
            if any(hint in body for hint in ["manage your google account", "sign out", "google account"]):
                return True
        # Try navigating to myaccount to check
        body = (await page.locator("body").inner_text(timeout=3000)).lower()
        if "sign in" in body and "create account" in body:
            return False
        return False
    except Exception:
        return False


async def _get_logged_in_email(page) -> str:
    """Tries to extract the logged-in email from the page."""
    try:
        await page.goto("https://myaccount.google.com", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        # Look for email text on the page
        body = await page.locator("body").inner_text(timeout=3000)
        for line in body.splitlines():
            line = line.strip()
            if "@" in line and "." in line and len(line) < 60:
                return line
        return "(email not detected)"
    except Exception:
        return "(email not detected)"


async def _verify_meet_access(page):
    """Navigates to meet.google.com to verify the account can access Meet."""
    try:
        print("[SETUP] 🔍 Verifying Google Meet access...", flush=True)
        await page.goto("https://meet.google.com", wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(3000)
        body = (await page.locator("body").inner_text(timeout=3000)).lower()
        if "new meeting" in body or "start a meeting" in body or "join" in body:
            print("[SETUP] ✅ Google Meet access confirmed.", flush=True)
        else:
            print("[SETUP] ⚠️  Could not confirm Meet access — check noVNC manually.", flush=True)
    except Exception as e:
        print(f"[SETUP] ⚠️  Meet verification warning: {e}", flush=True)


def _save_backup():
    """Saves a backup copy of the base profile in case it gets corrupted."""
    try:
        if os.path.exists(BACKUP_PROFILE):
            shutil.rmtree(BACKUP_PROFILE, ignore_errors=True)
        shutil.copytree(BASE_PROFILE, BACKUP_PROFILE)
        print(f"[SETUP] 💾 Backup saved at {BACKUP_PROFILE}", flush=True)
    except Exception as e:
        print(f"[SETUP] ⚠️  Backup warning: {e}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())