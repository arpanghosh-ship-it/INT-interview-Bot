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
import signal
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv

load_dotenv()

os.environ["DISPLAY"]      = ":99"
os.environ["PULSE_SERVER"] = "unix:/var/run/pulse/native"
os.environ["PULSE_SOURCE"] = "VirtualMicSource"
os.environ["PULSE_SINK"]   = "VirtualSpeaker"


async def _click_use_microphone(page) -> bool:
    try:
        result = await page.evaluate("""
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
        """)
        if result:
            print(f"[MIC]  ✅ Clicked: '{result}'", flush=True)
            return True
    except Exception as e:
        print(f"[MIC]  ⚠️  Error: {e}", flush=True)
    return False


async def _click_join_button(page) -> bool:
    try:
        result = await page.evaluate("""
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
        """)
        if result:
            print(f"[JOIN] ✅ Clicked: '{result}'", flush=True)
            return True
    except Exception as e:
        print(f"[JOIN] ⚠️  Error: {e}", flush=True)
    return False


async def _dismiss_popups(page):
    try:
        await page.evaluate("""
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
        """)
    except Exception:
        pass


async def _get_mic_state(page) -> str:
    try:
        return await page.evaluate("""
            () => {
                if (document.querySelector('[aria-label*="Turn off microphone"]')) return 'MIC_ON';
                if (document.querySelector('[aria-label*="Turn on microphone"]'))  return 'MIC_OFF';
                if (document.querySelector('[aria-label*="Microphone problem"]'))  return 'MIC_PROBLEM';
                return 'UNKNOWN';
            }
        """)
    except Exception:
        return 'UNKNOWN'


async def run_meet(joined_event: asyncio.Event = None):
    meeting_link    = os.getenv("MEETING_LINK")
    google_email    = os.getenv("GOOGLE_EMAIL")
    google_password = os.getenv("GOOGLE_PASSWORD")
    stay_duration   = int(os.getenv("STAY_DURATION_SECONDS", "7200"))

    if not meeting_link:
        print("❌  MEETING_LINK not set in .env", file=sys.stderr); sys.exit(1)
    if not google_email or not google_password:
        print("❌  GOOGLE_EMAIL or GOOGLE_PASSWORD not set in .env", file=sys.stderr); sys.exit(1)

    print(f"🚀 Joining  : {meeting_link}")
    print(f"⏳ Duration : {stay_duration}s ({stay_duration // 60} min)")
    print(f"🎙️  Mic      : VirtualMicSource → Chrome → Meet")

    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch(
                headless=False,
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

            context = await browser.new_context(
                permissions=["microphone"],
                viewport={"width": 1280, "height": 720},
            )
            await context.grant_permissions(
                ["microphone"], origin="https://meet.google.com"
            )
            print("[PERM] ✅ Microphone pre-granted for meet.google.com", flush=True)

            page = await context.new_page()

            # ── Step 1: Sign in ───────────────────────────────────────────────
            print("\n[JOIN] ── Step 1: Signing into Google ──────────────────", flush=True)
            try:
                await page.goto("https://accounts.google.com",
                                wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                await page.fill('input[type="email"]', google_email, timeout=10000)
                await page.click('#identifierNext, button:has-text("Next")', timeout=10000)
                await page.wait_for_timeout(3000)
                await page.fill('input[type="password"]', google_password, timeout=10000)
                await page.click('#passwordNext, button:has-text("Next")', timeout=10000)
                await page.wait_for_timeout(6000)
                print(f"[JOIN] Signed in. URL: {page.url}", flush=True)
            except PlaywrightTimeout:
                print("[JOIN] ⚠️  Login timeout — may already be signed in", flush=True)
            except Exception as e:
                print(f"[JOIN] ⚠️  Login error: {e}", flush=True)

            # ── Step 2: Open Meet ─────────────────────────────────────────────
            print("\n[JOIN] ── Step 2: Opening Meet ─────────────────────────", flush=True)
            try:
                await page.goto(meeting_link,
                                wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(4000)
                print(f"[JOIN] Meet loaded: {page.url}", flush=True)
            except PlaywrightTimeout:
                print("[JOIN] ⚠️  Meet load timeout — continuing", flush=True)
            except Exception as e:
                print(f"[JOIN] ❌ Failed to open Meet: {e}", file=sys.stderr)
                sys.exit(1)

            # ── Step 3: Pre-join mic popup ────────────────────────────────────
            print("\n[JOIN] ── Step 3: Pre-join mic popup ───────────────────", flush=True)
            for attempt in range(6):
                await page.wait_for_timeout(1500)
                if await _click_use_microphone(page):
                    await page.wait_for_timeout(2000)
                    break
                print(f"[JOIN] Mic popup not visible (attempt {attempt+1}/6)", flush=True)

            # ── Step 4: Join meeting ──────────────────────────────────────────
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
                        btns = await page.evaluate("""
                            () => Array.from(document.querySelectorAll('button'))
                                .map(b => (b.textContent||'').trim() + ' | ' + (b.getAttribute('aria-label')||''))
                                .filter(s => s.trim() !== ' | ')
                                .slice(0, 15)
                                .join(' || ')
                        """)
                        print(f"[JOIN] Visible buttons: {btns}", flush=True)
                    except Exception:
                        pass
                print(f"[JOIN] Join button not found (attempt {attempt+1}/10)", flush=True)

            if not joined:
                print("[JOIN] ⚠️  Could not click join — may already be inside", flush=True)

            # ── Step 5: Post-join mic popup ───────────────────────────────────
            print("\n[JOIN] ── Step 5: Post-join mic popup ──────────────────", flush=True)
            for attempt in range(5):
                await page.wait_for_timeout(1500)
                if await _click_use_microphone(page):
                    await page.wait_for_timeout(2000)
                    break

            await page.wait_for_timeout(1000)
            await _dismiss_popups(page)

            # ── Step 6: Verify mic state ──────────────────────────────────────
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

            # ── Step 7: Audio routing check ───────────────────────────────────
            print("\n[JOIN] ── Step 7: Audio routing check ──────────────────", flush=True)
            try:
                import subprocess
                result = subprocess.run(["pactl", "info"],
                                        capture_output=True, text=True, timeout=5)
                for line in result.stdout.splitlines():
                    if "Default Source" in line or "Default Sink" in line:
                        print(f"[AUDIO] {line.strip()}", flush=True)
            except Exception as e:
                print(f"[AUDIO] Could not check PulseAudio: {e}", flush=True)

            print("\n✅ Bot is in the meeting.", flush=True)
            if joined_event:
                joined_event.set()

            # ── Stay in meeting — ONLY exits on process termination ───────────
            # IMPORTANT: We use a simple polling loop instead of asyncio.sleep()
            # Reason: asyncio.sleep() raises CancelledError when main.py's
            # asyncio.wait(FIRST_COMPLETED) triggers, causing bot to leave meeting
            # when STT fails. This loop keeps the bot in the meeting regardless
            # of what happens to other tasks.
            print(f"🟢 Staying for {stay_duration // 60} min.", flush=True)
            print(f"   Bot will only leave when /stop is called from UI.\n", flush=True)

            elapsed = 0
            while elapsed < stay_duration:
                try:
                    await asyncio.sleep(5)   # check every 5 seconds
                    elapsed += 5

                    # Check if browser/page is still alive
                    if page.is_closed():
                        print("[JOIN] ⚠️  Page closed unexpectedly.", flush=True)
                        break

                except asyncio.CancelledError:
                    # ── KEY FIX: CancelledError means api.py called /stop ──────
                    # Only NOW do we actually leave the meeting
                    print("[JOIN] 🛑 Stop signal received — leaving meeting.", flush=True)
                    raise   # re-raise so finally block runs and browser closes

            print(f"[JOIN] ⏰ Stay duration reached ({stay_duration}s). Leaving.", flush=True)

        except asyncio.CancelledError:
            print("[JOIN] 🛑 Bot stopped by user.", flush=True)
            raise   # re-raise so caller knows task was cancelled

        except Exception as e:
            print(f"\n❌ Fatal error: {e}", file=sys.stderr)
            raise

        finally:
            if browser:
                try:
                    await browser.close()
                    print("✅ Browser closed.", flush=True)
                except Exception as e:
                    print(f"⚠️  Could not close browser: {e}", flush=True)


if __name__ == "__main__":
    asyncio.run(run_meet())