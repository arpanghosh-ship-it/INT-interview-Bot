#!/usr/bin/env python3
"""
meet_creator.py — Creates a Google Meet link via Google Calendar API.

The bot's Google account becomes the HOST of the meeting.
No Quick Access restrictions. No admission needed. Works for every interview.

Requirements:
  - credentials.json  (OAuth2 client secret — from Google Cloud Console)
  - token.json        (pre-authorized token — generated once via get_token.py)

Both files must be placed at the path defined by:
  GOOGLE_CREDENTIALS_PATH  (default: /app/credentials.json)
  GOOGLE_TOKEN_PATH        (default: /app/token.json)
"""

import os
import json
import datetime
from typing import Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


# ── Config ────────────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/calendar"]

CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "/app/credentials.json")
TOKEN_PATH = os.getenv("GOOGLE_TOKEN_PATH", "/app/token.json")


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_credentials() -> Credentials:
    """
    Load and refresh OAuth2 credentials from token.json.
    Raises a clear error if token.json is missing or expired and can't refresh.
    """
    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError(
            f"token.json not found at '{TOKEN_PATH}'.\n"
            "Run get_token.py on your local machine to generate it, "
            "then upload it to EC2 at that path."
        )

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # Refresh if expired
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            print("[MEET_CREATOR] 🔄 Refreshing Google OAuth2 token...", flush=True)
            creds.refresh(Request())
            # Save refreshed token back to disk
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
            print("[MEET_CREATOR] ✅ Token refreshed and saved.", flush=True)
        else:
            raise RuntimeError(
                "Google OAuth2 token is expired and cannot be refreshed.\n"
                "Re-run get_token.py on your local machine to get a fresh token."
            )

    return creds


# ── Meet Creator ──────────────────────────────────────────────────────────────

def create_meet_link(
    title: str = "INT AI Interview Session",
    duration_minutes: int = 60,
    candidate_email: Optional[str] = None,
) -> str:
    """
    Creates a Google Calendar event with Meet conferencing.
    Returns the Google Meet join URL.

    Args:
        title: Calendar event title (visible to guests).
        duration_minutes: Length of the interview session.
        candidate_email: Optional — if provided, sends calendar invite to candidate.

    Returns:
        str: Google Meet URL (e.g. https://meet.google.com/abc-defg-hij)
    """
    print("[MEET_CREATOR] 📅 Creating Google Meet via Calendar API...", flush=True)

    creds = _get_credentials()
    service = build("calendar", "v3", credentials=creds)

    # Start 30 seconds from now so the meeting is immediately joinable
    start_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=30)
    end_time = start_time + datetime.timedelta(minutes=duration_minutes)

    # Format as RFC3339 with UTC timezone
    start_str = start_time.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    end_str = end_time.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    # Only add attendees if a valid non-empty email is provided
    valid_email = candidate_email.strip() if candidate_email and isinstance(candidate_email, str) else ""
    attendees = [{"email": valid_email}] if valid_email else []
    send_updates = "all" if valid_email else "none"

    event_body: dict = {
        "summary": title,
        "description": "AI-powered technical interview session by INT Interview Bot.",
        "start": {
            "dateTime": start_str,
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": end_str,
            "timeZone": "UTC",
        },
        "conferenceData": {
            "createRequest": {
                "requestId": f"int-bot-{int(start_time.timestamp())}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
        # guestsCanModify=False ensures bot stays as host
        "guestsCanModify": False,
        "guestsCanInviteOthers": False,
    }

    # Only include attendees key if there's actually someone to invite
    if attendees:
        event_body["attendees"] = attendees

    event = service.events().insert(
        calendarId="primary",
        body=event_body,
        conferenceDataVersion=1,  # Required to actually create Meet link
        sendUpdates=send_updates,
    ).execute()

    # Extract Meet link from response
    meet_link = None
    conference_data = event.get("conferenceData", {})
    for entry_point in conference_data.get("entryPoints", []):
        if entry_point.get("entryPointType") == "video":
            meet_link = entry_point.get("uri")
            break

    if not meet_link:
        # Fallback: try hangoutLink (older field)
        meet_link = event.get("hangoutLink")

    if not meet_link:
        raise RuntimeError(
            f"Calendar event created (ID: {event.get('id')}) "
            "but no Meet link was returned. "
            "Make sure your Google account has Meet enabled."
        )

    print(f"[MEET_CREATOR] ✅ Meet created  : {meet_link}", flush=True)
    print(f"[MEET_CREATOR]    Event ID      : {event.get('id')}", flush=True)
    print(f"[MEET_CREATOR]    Duration      : {duration_minutes} min", flush=True)
    if candidate_email:
        print(f"[MEET_CREATOR]    Invite sent to: {candidate_email}", flush=True)

    return meet_link


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    link = create_meet_link(
        title="Test Interview Session",
        duration_minutes=30,
    )
    print(f"\n✅ Your Meet link: {link}")