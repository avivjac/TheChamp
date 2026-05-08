"""
Automatic football registration for Aviv's Sunday games.

Runs every Wednesday at 20:00 Israel time (via GitHub Actions).
1. Finds the upcoming Sunday.
2. Checks Google Calendar for conflicts 21:00–23:00 local time.
3. If free: submits the Google Form, adds the event, sends a WhatsApp confirmation.
4. If busy: sends a WhatsApp message explaining the conflict.

Required .env / Railway variables:
    FORM_ENTRY_NAME   — Google Form entry ID for the name field  (e.g. entry.123456789)
    FORM_ENTRY_PHONE  — Google Form entry ID for the phone field (e.g. entry.987654321)
    MY_NAME           — Full name to submit in the form
    MY_PHONE_NUMBER   — Phone number to submit in the form (with country code, e.g. +972501234567)
"""

import os
import datetime
import logging
import requests
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ISRAEL = ZoneInfo("Asia/Jerusalem")
FORM_SUBMIT_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSf4wcVNzo3auF22PlpjfXlIq7EAy7lAvH-6Dc7_lR7dLW5qYg"
    "/formResponse"
)
GAME_TITLE = "⚽ Football with friends"
GAME_START_HOUR = 21
GAME_END_HOUR = 23


def _next_sunday() -> datetime.date:
    """Return the date of the upcoming Sunday (from today)."""
    today = datetime.date.today()
    days_until_sunday = (6 - today.weekday()) % 7  # Monday=0 … Sunday=6
    if days_until_sunday == 0:
        days_until_sunday = 7  # if today is Sunday, get next Sunday
    return today + datetime.timedelta(days=days_until_sunday)


def _is_sunday_free(sunday: datetime.date) -> tuple[bool, list]:
    """
    Check the primary Google Calendar for events that overlap 21:00–23:00 on the given Sunday.
    Returns (is_free, conflicting_events).
    """
    from real_madrid import get_calendar_service

    window_start = datetime.datetime(
        sunday.year, sunday.month, sunday.day,
        GAME_START_HOUR, 0, 0, tzinfo=ISRAEL,
    )
    window_end = datetime.datetime(
        sunday.year, sunday.month, sunday.day,
        GAME_END_HOUR, 0, 0, tzinfo=ISRAEL,
    )

    try:
        service = get_calendar_service()
        result = service.events().list(
            calendarId="primary",
            timeMin=window_start.isoformat(),
            timeMax=window_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = result.get("items", [])
        return len(events) == 0, events
    except Exception as exc:
        logger.error("Calendar check failed: %s", exc)
        # Fail safe: don't register if we can't verify the calendar
        return False, []


def _submit_form(name: str, phone: str) -> bool:
    """
    POST to the Google Form. Returns True on success.

    To find entry IDs when the form is open:
      1. Open https://forms.gle/Sg3MVCuYve1Qmw8n8 in a browser.
      2. Right-click → View Page Source.
      3. Search for 'entry.' — you'll see entry.XXXXXXXXX for each field.
      4. Set FORM_ENTRY_NAME and FORM_ENTRY_PHONE in your .env / Railway variables.
    """
    entry_name = os.environ.get("FORM_ENTRY_NAME", "")
    entry_phone = os.environ.get("FORM_ENTRY_PHONE", "")

    if not entry_name or not entry_phone:
        logger.error("FORM_ENTRY_NAME or FORM_ENTRY_PHONE not set — cannot submit form")
        return False

    payload = {
        entry_name: name,
        entry_phone: phone,
    }

    try:
        resp = requests.post(FORM_SUBMIT_URL, data=payload, timeout=10)
        # Google Forms returns 200 even on success (no redirect in headless POST)
        if resp.status_code in (200, 302):
            logger.info("Form submitted successfully (HTTP %s)", resp.status_code)
            return True
        logger.error("Unexpected form response: HTTP %s", resp.status_code)
        return False
    except Exception as exc:
        logger.error("Form submission failed: %s", exc)
        return False


def _add_to_calendar(sunday: datetime.date) -> str:
    """Add the football game to Google Calendar. Returns a status string."""
    from real_madrid import get_calendar_service

    start_local = datetime.datetime(
        sunday.year, sunday.month, sunday.day,
        GAME_START_HOUR, 0, 0, tzinfo=ISRAEL,
    )
    end_local = datetime.datetime(
        sunday.year, sunday.month, sunday.day,
        GAME_END_HOUR, 0, 0, tzinfo=ISRAEL,
    )

    try:
        service = get_calendar_service()
        event_body = {
            "summary": GAME_TITLE,
            "start": {"dateTime": start_local.isoformat()},
            "end":   {"dateTime": end_local.isoformat()},
        }
        service.events().insert(calendarId="primary", body=event_body).execute()
        logger.info("Football event added to calendar for %s", sunday)
        return f"✅ Added to calendar: {sunday.strftime('%A %d %b')}, {GAME_START_HOUR}:00–{GAME_END_HOUR}:00"
    except Exception as exc:
        logger.error("Failed to add football event to calendar: %s", exc)
        return f"⚠️ Registered but couldn't add to calendar: {exc}"


def register_for_football() -> str:
    """
    Main entry point. Checks availability, registers if free, returns a status message
    (also sent as a WhatsApp notification).
    """
    from real_madrid import send_whatsapp_notification

    name = os.environ.get("MY_NAME", "")
    phone = os.environ.get("MY_PHONE_NUMBER", "")

    if not name or not phone:
        logger.error("MY_NAME or MY_PHONE_NUMBER not set")
        return "❌ Registration failed: MY_NAME or MY_PHONE_NUMBER not configured."

    sunday = _next_sunday()
    sunday_str = sunday.strftime("%A %d %b")

    logger.info("Checking availability for Sunday %s", sunday)
    is_free, conflicts = _is_sunday_free(sunday)

    if not is_free:
        conflict_titles = ", ".join(e.get("summary", "?") for e in conflicts)
        msg = (
            f"⚽ Football registration — {sunday_str}\n"
            f"❌ You have a conflict at 21:00–23:00: {conflict_titles}\n"
            f"Skipped registration."
        )
        logger.info("Sunday busy — skipping registration. Conflicts: %s", conflict_titles)
        send_whatsapp_notification(msg)
        return msg

    # Free — register and add to calendar
    submitted = _submit_form(name, phone)
    cal_result = _add_to_calendar(sunday)

    if submitted:
        msg = (
            f"⚽ Football registration — {sunday_str}\n"
            f"✅ Registered as {name}\n"
            f"{cal_result}"
        )
    else:
        msg = (
            f"⚽ Football registration — {sunday_str}\n"
            f"❌ Form submission failed (check logs). Calendar was not updated."
        )

    send_whatsapp_notification(msg)
    return msg
