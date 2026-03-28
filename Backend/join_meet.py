#!/usr/bin/env python3
"""
join_meet.py — Google Meet joiner using Raw Playwright (mic only, no camera)

EXIT POLICY:
  The bot ONLY leaves the meeting when:
    1. api.py calls /stop → terminates main.py process → SIGTERM received
    2. stay_duration seconds have elapsed (safety timeout)

  The bot does NOT exit due to:
    - asyncio.CancelledError from task management
    - STT failures or restarts
    - Any internal errors
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()

os.environ["DISPLAY"] = ":99"
os.environ["PULSE_SERVER"] = "unix:/var/run/pulse/native"
os.environ["PULSE_SOURCE"] = "VirtualMicSource"
os.environ["PULSE_SINK"] = "VirtualSpeaker"


async def _click_use_microphone(page) -> bool:
    try:
        result = await page.evaluate(
            """
            () => {
                const buttons = Array.from(document.querySelectorAll('button'));
                for (const btn of buttons) {
                    const txt = (btn.textContent || '').trim().toLowerCase();
                    if (txt.includes('microphone') &&
                        !txt.includes('camera') &&
                        !txt.includes('without')) {
                        btn.click();
                        return btn.textContent.trim();
                    }
                }
                return null;
            }
        """
        )
        if result:
            print(f"[MIC]  ✅ Clicked: '{result}'", flush=True)
            return True
    except Exception as e:
        print(f"[MIC]  ⚠️  Error: {e}", flush=True)
    return False


async def _click_join_button(page) -> bool:
    try:
        result = await page.evaluate(
            """
            () => {
                const buttons = Array.from(document.querySelectorAll('button'));
                for (const btn of buttons) {
                    const txt = (btn.textContent || '').trim().toLowerCase();
                    if (txt.includes('without')) continue;
                    if (txt.includes('leave call') || txt.includes('call_end')) continue;
                    if (txt === 'ask to join') { btn.click(); return 'Ask to join'; }
                    if (txt === 'join now')    { btn.click(); return 'Join now'; }
                }
                return null;
            }
        """
        )
        if result:
            print(f"[JOIN] ✅ Clicked: '{result}'", flush=True)
            return True
    except Exception as e:
        print(f"[JOIN] ⚠️  Error: {e}", flush=True)
    return False


async def _click_switch_here(page) -> bool:
    try:
        result = await page.evaluate(
            """
            () => {
                const buttons = Array.from(document.querySelectorAll('button'));
                for (const btn of buttons) {
                    const txt = (btn.textContent || '').trim().toLowerCase();
                    if (txt.includes('switch here') || txt.includes('switch the call here')) {
                        btn.click();
                        return btn.textContent.trim();
                    }
                }
                return null;
            }
        """
        )
        if result:
            print(f"[JOIN] 🔁 Clicked: '{result}'", flush=True)
            return True
    except Exception as e:
        print(f"[JOIN] ⚠️  Switch click error: {e}", flush=True)
    return False


async def _dismiss_popups(page):
    try:
        await page.evaluate(
            """
            () => {
                for (const sel of [
                    '[aria-label="Close dialog"]',
                    '[aria-label="Close"]',
                    'button[aria-label="Dismiss"]'
                ]) {
                    const btn = document.querySelector(sel);
                    if (btn) btn.click();
                }
            }
        """
        )
    except Exception:
        pass


async def _get_mic_state(page) -> str:
    try:
        return await page.evaluate(
            """
            () => {
                if (document.querySelector('[aria-label*="Turn off microphone"]')) return 'MIC_ON';
                if (document.querySelector('[aria-label*="Turn on microphone"]'))  return 'MIC_OFF';
                if (document.querySelector('[aria-label*="Microphone problem"]'))  return 'MIC_PROBLEM';
                return 'UNKNOWN';
            }
        """
        )
    except Exception:
        return "UNKNOWN"


async def _google_login_required(page) -> bool:
    try:
        url = (page.url or "").lower()
        if "accounts.google.com" in url or "servicelogin" in url or "challenge" in url:
            return True

        if await page.locator('input[type="email"]').count() > 0:
            return True
        if await page.locator('input[type="password"]').count() > 0:
            return True

        body_text = ""
        try:
            body_text = (await page.locator("body").inner_text(timeout=3000)).lower()
        except Exception:
            pass

        hints = [
            "sign in",
            "verify",
            "challenge",
            "2-step",
            "two-step",
            "use your phone",
            "tap yes",
        ]
        return any(h in body_text for h in hints)
    except Exception:
        return False


async def _wait_for_manual_login(page, timeout_seconds: int) -> None:
    if timeout_seconds <= 0:
        return

    print("\n[LOGIN] ── Manual login window ─────────────────────────", flush=True)
    print("[LOGIN] Use the VNC browser to sign in to Google manually.", flush=True)
    print("[LOGIN] Complete 2-Step Verification on your phone if prompted.", flush=True)
    print(f"[LOGIN] Waiting up to {timeout_seconds}s before continuing...", flush=True)

    elapsed = 0
    while elapsed < timeout_seconds:
        if not await _google_login_required(page):
            print("[LOGIN] ✅ Login no longer required. Continuing.", flush=True)
            return

        await asyncio.sleep(5)
        elapsed += 5
        remaining = max(timeout_seconds - elapsed, 0)
        print(f"[LOGIN]   {remaining}s remaining...", flush=True)

    print("[LOGIN] ⚠️  Login wait timeout reached. Continuing anyway.", flush=True)


async def run_meet(joined_event: asyncio.Event = None):
    meeting_link = os.getenv("MEETING_LINK", "").strip()
    stay_duration = int(os.getenv("STAY_DURATION_SECONDS", "7200"))
    chrome_user_data_dir = os.getenv("CHROME_USER_DATA_DIR", "/tmp/chrome-profile")
    manual_login_wait = int(os.getenv("MANUAL_LOGIN_WAIT_SECONDS", "0"))

    if not meeting_link:
        print("❌  MEETING_LINK not set in .env", file=sys.stderr)
        sys.exit(1)

    if not meeting_link.startswith("http://") and not meeting_link.startswith("https://"):
        meeting_link = "https://" + meeting_link

    print(f"🚀 Joining  : {meeting_link}")
    print(f"⏳ Duration : {stay_duration}s ({stay_duration // 60} min)")
    print(f"🎙️  Mic      : VirtualMicSource → Chrome → Meet")
    print(f"👤 Profile  : {chrome_user_data_dir}")

    async with async_playwright() as p:
        context = None
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=chrome_user_data_dir,
                headless=False,
                viewport={"width": 1280, "height": 720},
                args=[
                    "--use-fake-ui-for-media-stream",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--alsa-input-device=pulse",
                    "--alsa-output-device=pulse",
                    "--no-first-run",
                    "--disable-default-apps",
                    "--window-size=1280,720",
                ],
            )

            await context.grant_permissions(
                ["microphone"], origin="https://meet.google.com"
            )
            print("[PERM] ✅ Microphone pre-granted for meet.google.com", flush=True)

            page = await context.new_page()

            # Open Meet first.
            print("\n[JOIN] ── Step 1: Opening Meet ─────────────────────────", flush=True)
            try:
                await page.goto(
                    meeting_link,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                await page.wait_for_timeout(4000)
                print(f"[JOIN] Meet loaded: {page.url}", flush=True)
            except PlaywrightTimeout:
                print("[JOIN] ⚠️  Meet load timeout — continuing", flush=True)
            except Exception as e:
                print(f"[JOIN] ❌ Failed to open Meet: {e}", file=sys.stderr)
                sys.exit(1)

            # If Google login/challenge appears, wait only as long as needed.
            if await _google_login_required(page):
                print("\n[LOGIN] Google sign-in/challenge detected.", flush=True)
                await _wait_for_manual_login(page, manual_login_wait)

                print("\n[JOIN] ── Re-opening Meet after login ───────────────────", flush=True)
                try:
                    await page.goto(
                        meeting_link,
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    await page.wait_for_timeout(4000)
                    print(f"[JOIN] Meet loaded after login: {page.url}", flush=True)
                except Exception as e:
                    print(f"[JOIN] ❌ Failed to reopen Meet after login: {e}", file=sys.stderr)
                    sys.exit(1)

            # If Meet shows switch prompt, handle it.
            print("\n[JOIN] ── Step 2: Checking for switch prompt ───────────", flush=True)
            for attempt in range(4):
                await page.wait_for_timeout(1500)
                if await _click_switch_here(page):
                    await page.wait_for_timeout(3000)
                    break
                print(f"[JOIN] Switch prompt not visible (attempt {attempt+1}/4)", flush=True)

            # Pre-join mic popup.
            print("\n[JOIN] ── Step 3: Pre-join mic popup ───────────────────", flush=True)
            for attempt in range(6):
                await page.wait_for_timeout(1500)
                if await _click_use_microphone(page):
                    await page.wait_for_timeout(2000)
                    break
                print(f"[JOIN] Mic popup not visible (attempt {attempt+1}/6)", flush=True)

            # Join meeting.
            print("\n[JOIN] ── Step 4: Joining meeting ──────────────────────", flush=True)
            joined = False
            for attempt in range(10):
                await page.wait_for_timeout(2000)

                if await _click_join_button(page):
                    joined = True
                    await page.wait_for_timeout(3000)
                    break

                if attempt == 2:
                    try:
                        btns = await page.evaluate(
                            """
                            () => Array.from(document.querySelectorAll('button'))
                                .map(b => (b.textContent||'').trim() + ' | ' + (b.getAttribute('aria-label')||''))
                                .filter(s => s.trim() !== ' | ')
                                .slice(0, 15)
                                .join(' || ')
                        """
                        )
                        print(f"[JOIN] Visible buttons: {btns}", flush=True)
                    except Exception:
                        pass

                print(f"[JOIN] Join button not found (attempt {attempt+1}/10)", flush=True)

            if not joined:
                print("[JOIN] ⚠️  Could not click join — may already be inside", flush=True)

            # Post-join mic popup.
            print("\n[JOIN] ── Step 5: Post-join mic popup ──────────────────", flush=True)
            for attempt in range(5):
                await page.wait_for_timeout(1500)
                if await _click_use_microphone(page):
                    await page.wait_for_timeout(2000)
                    break

            await page.wait_for_timeout(1000)
            await _dismiss_popups(page)

            # Verify mic state.
            print("\n[JOIN] ── Step 6: Verifying mic state ──────────────────", flush=True)
            await page.wait_for_timeout(2000)
            state = await _get_mic_state(page)
            print(f"[JOIN] Mic state: {state}", flush=True)

            if state == "MIC_OFF":
                try:
                    await page.keyboard.press("Control+d")
                    await page.wait_for_timeout(1000)
                    print("[JOIN] Toggled mic ON with Ctrl+D", flush=True)
                except Exception as e:
                    print(f"[JOIN] Ctrl+D failed: {e}", flush=True)

            final = await _get_mic_state(page)
            if final == "MIC_ON":
                print("[JOIN] ══════════════════════════════════════════", flush=True)
                print("[JOIN] ✅ MIC IS ON — Alex's voice will be heard!", flush=True)
                print("[JOIN] ══════════════════════════════════════════", flush=True)
            else:
                print(f"[JOIN] ⚠️  Mic state: {final} — check noVNC", flush=True)

            # Audio routing check.
            print("\n[JOIN] ── Step 7: Audio routing check ──────────────────", flush=True)
            try:
                import subprocess

                result = subprocess.run(
                    ["pactl", "info"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in result.stdout.splitlines():
                    if "Default Source" in line or "Default Sink" in line:
                        print(f"[AUDIO] {line.strip()}", flush=True)
            except Exception as e:
                print(f"[AUDIO] Could not check PulseAudio: {e}", flush=True)

            print("\n✅ Bot is in the meeting.", flush=True)
            if joined_event:
                joined_event.set()

            print(f"🟢 Staying for {stay_duration // 60} min.", flush=True)
            print("   Bot will only leave when /stop is called from UI.\n", flush=True)

            elapsed = 0
            while elapsed < stay_duration:
                try:
                    await asyncio.sleep(5)
                    elapsed += 5

                    if page.is_closed():
                        print("[JOIN] ⚠️  Page closed unexpectedly.", flush=True)
                        break

                except asyncio.CancelledError:
                    print("[JOIN] 🛑 Stop signal received — leaving meeting.", flush=True)
                    raise

            print(f"[JOIN] ⏰ Stay duration reached ({stay_duration}s). Leaving.", flush=True)

        except asyncio.CancelledError:
            print("[JOIN] 🛑 Bot stopped by user.", flush=True)
            raise

        except Exception as e:
            print(f"\n❌ Fatal error: {e}", file=sys.stderr)
            raise

        finally:
            if context:
                try:
                    await context.close()
                    print("✅ Browser context closed.", flush=True)
                except Exception as e:
                    print(f"⚠️  Could not close browser context: {e}", flush=True)


if __name__ == "__main__":
    asyncio.run(run_meet())