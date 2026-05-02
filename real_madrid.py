import os
import logging
import datetime
import requests

from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

# Google Calendar imports (re-uses the same token.json as app.py)
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
REAL_MADRID_TEAM_ID = "8633"
RM_LEAGUE_IDS = {87, 42}          # LaLiga + Champions League only
SCOPES = ["https://www.googleapis.com/auth/calendar"]
_BASE_URL = "https://free-api-live-football-data.p.rapidapi.com"

_scheduler = BackgroundScheduler(timezone="UTC")
_notified_today: set = set()      # prevents duplicate notifications within a day


# ── Google Calendar helpers ───────────────────────────────────────────────────
def _get_calendar_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def _parse_event_dt(start_raw: str) -> datetime.datetime:
    """Parse a Calendar event start string into a UTC datetime."""
    if "T" in start_raw:
        return datetime.datetime.fromisoformat(start_raw).astimezone(datetime.timezone.utc)
    # All-day event — treat as 20:00 UTC kick-off placeholder
    return datetime.datetime.fromisoformat(start_raw + "T20:00:00+00:00")


def _find_rm_calendar_id() -> str | None:
    """
    Find the Google Calendar ID for the user's calendar named 'Real Madrid'.
    Returns the calendar ID string, or None if not found.
    """
    try:
        service = _get_calendar_service()
        page_token = None
        while True:
            response = service.calendarList().list(pageToken=page_token).execute()
            for cal in response.get("items", []):
                if cal.get("summary", "").strip().lower() == "real madrid":
                    logger.info("Found 'Real Madrid' calendar: %s", cal["id"])
                    return cal["id"]
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:
        logger.error("Failed to list calendars: %s", exc)
    logger.warning("No calendar named 'Real Madrid' found in calendar list")
    return None


def get_upcoming_games_from_rm_calendar(days: int = 60) -> list:
    """
    Return upcoming Real Madrid games from the dedicated 'Real Madrid' Google Calendar.
    Each item is a dict: {title, kickoff_utc, kickoff_local}.
    Uses the 'Real Madrid' calendar (not the primary calendar).
    """
    cal_id = _find_rm_calendar_id()
    if not cal_id:
        return []

    try:
        service = _get_calendar_service()
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        end = now + datetime.timedelta(days=days)

        result = service.events().list(
            calendarId=cal_id,
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        games = []
        for event in result.get("items", []):
            start_raw = event["start"].get("dateTime") or event["start"].get("date")
            dt = _parse_event_dt(start_raw)
            games.append({
                "title": event.get("summary", ""),
                "kickoff_utc": dt,
                "kickoff_local": _local_time(dt),
            })
        logger.info("Found %d upcoming games in 'Real Madrid' calendar", len(games))
        return games

    except Exception as exc:
        logger.error("Failed to fetch 'Real Madrid' calendar events: %s", exc)
        return []


def get_todays_game_from_rm_calendar() -> tuple | None:
    """
    Return (kickoff_utc, title) for today's game from the 'Real Madrid' calendar.
    Uses start-of-day as the lower bound so already-started games are included.
    Returns None if no game is scheduled today.
    """
    cal_id = _find_rm_calendar_id()
    if not cal_id:
        return None

    try:
        service = _get_calendar_service()
        today = datetime.date.today()
        day_start = datetime.datetime(today.year, today.month, today.day,
                                      tzinfo=datetime.timezone.utc)
        day_end = day_start + datetime.timedelta(days=1)

        result = service.events().list(
            calendarId=cal_id,
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])
        if not events:
            return None

        event = events[0]
        start_raw = event["start"].get("dateTime") or event["start"].get("date")
        dt = _parse_event_dt(start_raw)
        return dt, event.get("summary", "Real Madrid")

    except Exception as exc:
        logger.error("Failed to get today's game from 'Real Madrid' calendar: %s", exc)
        return None


def get_todays_rm_event_from_calendar() -> tuple | None:
    """
    Scan the PRIMARY Google Calendar for a Real Madrid event today.
    Returns (kickoff_utc, title) or None.
    For the dedicated schedule, prefer get_todays_game_from_rm_calendar() instead.
    """
    try:
        service = _get_calendar_service()
        today = datetime.date.today()
        day_start = datetime.datetime(today.year, today.month, today.day,
                                      tzinfo=datetime.timezone.utc).isoformat()
        day_end = datetime.datetime(today.year, today.month, today.day,
                                    23, 59, 59, tzinfo=datetime.timezone.utc).isoformat()

        result = service.events().list(
            calendarId="primary",
            timeMin=day_start,
            timeMax=day_end,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        for event in result.get("items", []):
            title = event.get("summary", "")
            if "real madrid" not in title.lower():
                continue
            start_raw = event["start"].get("dateTime") or event["start"].get("date")
            return _parse_event_dt(start_raw), title

    except Exception as exc:
        logger.error("Primary calendar check failed: %s", exc)
    return None


# ── RapidAPI layer ────────────────────────────────────────────────────────────
def _api_headers() -> dict:
    return {
        "x-rapidapi-host": "free-api-live-football-data.p.rapidapi.com",
        "x-rapidapi-key": os.environ["FOOTBALL_API_KEY"],
    }


def _search_matches() -> list:
    """Fetch all match suggestions for 'Real Madrid' from the search endpoint."""
    try:
        r = requests.get(
            f"{_BASE_URL}/football-matches-search",
            headers=_api_headers(),
            params={"search": "Real Madrid"},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("response", {}).get("suggestions", [])
    except Exception as exc:
        logger.error("Football API search failed: %s", exc)
        return []


def _is_first_team(match: dict) -> bool:
    """True only for Real Madrid's men's first team in LaLiga or Champions League."""
    home_id = match.get("homeTeamId")
    away_id = match.get("awayTeamId")
    return (
        (home_id == REAL_MADRID_TEAM_ID or away_id == REAL_MADRID_TEAM_ID)
        and match.get("leagueId") in RM_LEAGUE_IDS
    )


def get_match_by_id(match_id: str) -> dict | None:
    """Re-fetch fresh match data for a given match ID (score may have changed)."""
    for m in _search_matches():
        if str(m.get("id")) == str(match_id):
            return m
    return None


def get_todays_match_from_api() -> dict | None:
    """Return today's Real Madrid first-team match from the API, or None."""
    today = datetime.date.today()
    for m in _search_matches():
        if not _is_first_team(m):
            continue
        kick_off = datetime.datetime.fromisoformat(m["matchDate"].replace("Z", "+00:00"))
        if kick_off.date() == today:
            return m
    return None


def get_real_madrid_updates() -> str:
    """
    Returns a formatted string of recent + upcoming Real Madrid matches.
    Used by the Claude tool-use handler in app.py.
    """
    matches = [m for m in _search_matches() if _is_first_team(m)]
    if not matches:
        return "No Real Madrid matches found."

    lines = ["⚽ Real Madrid — latest matches:"]
    for m in matches[:8]:
        home = m.get("homeTeamName", "?")
        away = m.get("awayTeamName", "?")
        status = m.get("status", {})
        date_str = m.get("matchDate", "")[:10]

        if status.get("finished"):
            score = status.get("scoreStr", "?")
            reason = status.get("reason", {}).get("short", "FT")
            lines.append(f"  {home} {score} {away}  [{date_str}] {reason}")
        elif status.get("started"):
            score = status.get("scoreStr", "?")
            lines.append(f"  🔴 LIVE: {home} {score} {away}")
        else:
            lines.append(f"  {home} vs {away}  [{date_str}]")

    return "\n".join(lines)


# ── Message formatters ────────────────────────────────────────────────────────
def _local_time(utc_dt: datetime.datetime) -> str:
    """Convert UTC datetime to a local HH:MM string."""
    return utc_dt.astimezone().strftime("%H:%M")


def format_prematch_msg(match: dict, kickoff_utc: datetime.datetime) -> str:
    home = match["homeTeamName"]
    away = match["awayTeamName"]
    league = match.get("leagueName", "")
    time_str = _local_time(kickoff_utc)
    return (
        f"⚽ Game in 45 minutes!\n"
        f"🏟 {home} vs {away}\n"
        f"🏆 {league}\n"
        f"🕐 Kick-off: {time_str}"
    )


def format_live_msg(match: dict) -> str:
    home = match["homeTeamName"]
    away = match["awayTeamName"]
    status = match.get("status", {})
    score = status.get("scoreStr") or (
        f"{match.get('homeTeamScore', '?')} - {match.get('awayTeamScore', '?')}"
    )
    # NOTE: Individual goal scorers are not available from this API endpoint.
    # To add scorers, integrate an API that exposes match events (e.g. API-Football).
    return f"📊 ~50 minutes in!\n🔴 {home}  {score}  {away}"


def format_final_msg(match: dict) -> str:
    home = match["homeTeamName"]
    away = match["awayTeamName"]
    score = match.get("status", {}).get("scoreStr", "?")
    league = match.get("leagueName", "")
    return (
        f"🏁 Full Time!\n"
        f"⚽ {home}  {score}  {away}\n"
        f"🏆 {league}"
    )


# ── Proactive WhatsApp sender ─────────────────────────────────────────────────
def send_whatsapp_notification(text: str):
    """Push an outbound WhatsApp message to the user via the Twilio REST API."""
    from twilio.rest import Client  # lazy import

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_WHATSAPP_NUMBER")
    to_number = os.environ.get("MY_PHONE_NUMBER")

    if not all([account_sid, auth_token, from_number, to_number]):
        logger.error("Twilio credentials missing — cannot send proactive notification")
        return

    try:
        Client(account_sid, auth_token).messages.create(
            body=text,
            from_=f"whatsapp:{from_number}",
            to=f"whatsapp:{to_number}",
        )
        logger.info("Sent WhatsApp notification: %s", text[:80])
    except Exception as exc:
        logger.error("Twilio send failed: %s", exc)


# ── Scheduler jobs ────────────────────────────────────────────────────────────
def _job_prematch(match_id: str, kickoff_utc_iso: str):
    key = f"prematch:{match_id}"
    if key in _notified_today:
        return
    match = get_match_by_id(match_id)
    if not match:
        logger.warning("Pre-match: could not find match %s in API", match_id)
        return
    kickoff_utc = datetime.datetime.fromisoformat(kickoff_utc_iso)
    send_whatsapp_notification(format_prematch_msg(match, kickoff_utc))
    _notified_today.add(key)


def _job_live(match_id: str):
    key = f"live:{match_id}"
    if key in _notified_today:
        return
    match = get_match_by_id(match_id)
    if match:
        send_whatsapp_notification(format_live_msg(match))
        _notified_today.add(key)

    # Begin polling every 5 minutes until the match ends
    poll_id = f"poll:{match_id}"
    if not _scheduler.get_job(poll_id):
        _scheduler.add_job(
            _job_poll_final,
            "interval",
            minutes=5,
            id=poll_id,
            kwargs={"match_id": match_id},
        )
        logger.info("Started polling for full-time (match %s)", match_id)


def _job_poll_final(match_id: str):
    key = f"final:{match_id}"
    if key in _notified_today:
        _scheduler.remove_job(f"poll:{match_id}")
        return

    match = get_match_by_id(match_id)
    if match and match.get("status", {}).get("finished"):
        send_whatsapp_notification(format_final_msg(match))
        _notified_today.add(key)
        _scheduler.remove_job(f"poll:{match_id}")
        logger.info("Full-time notification sent for match %s", match_id)


# ── Daily game check ──────────────────────────────────────────────────────────
def _check_todays_game():
    """
    Runs at 08:00 UTC and on startup.
    1. Checks Google Calendar for a Real Madrid event today.
    2. Validates/enriches with the football API.
    3. Schedules the three notification jobs.
    """
    _notified_today.clear()

    # Step 1: get kick-off time from the dedicated 'Real Madrid' Google Calendar
    calendar_result = get_todays_game_from_rm_calendar()
    if not calendar_result:
        logger.info("No Real Madrid game found in calendar today")
        return

    kickoff_utc, event_title = calendar_result
    logger.info("Calendar event: '%s' at %s UTC", event_title, kickoff_utc)

    # Step 2: find the matching API entry for live score polling
    api_match = get_todays_match_from_api()
    if not api_match:
        logger.warning("Game in calendar but not found in API — notifications may lack score data")
        # Still schedule prematch using calendar time; live/final won't have a match ID to poll
        return

    match_id = str(api_match["id"])
    now = datetime.datetime.now(tz=datetime.timezone.utc)

    prematch_time = kickoff_utc - datetime.timedelta(minutes=45)
    live_time = kickoff_utc + datetime.timedelta(minutes=50)

    # Step 3: schedule jobs
    if prematch_time > now:
        _scheduler.add_job(
            _job_prematch,
            DateTrigger(run_date=prematch_time),
            id=f"prematch:{match_id}",
            kwargs={"match_id": match_id, "kickoff_utc_iso": kickoff_utc.isoformat()},
            replace_existing=True,
        )
        logger.info("Scheduled pre-match alert at %s UTC", prematch_time)
    else:
        logger.info("Pre-match window already passed (kick-off %s UTC)", kickoff_utc)

    if live_time > now:
        _scheduler.add_job(
            _job_live,
            DateTrigger(run_date=live_time),
            id=f"live:{match_id}",
            kwargs={"match_id": match_id},
            replace_existing=True,
        )
        logger.info("Scheduled live score update at %s UTC", live_time)
    elif api_match.get("status", {}).get("started") and not api_match.get("status", {}).get("finished"):
        logger.info("Game already in progress — sending live update now")
        _job_live(match_id)


# ── Morning briefing ──────────────────────────────────────────────────────────

def send_morning_briefing():
    """
    Sends a daily WhatsApp briefing at 08:00 Israel time with:
      - Today's events from the primary Google Calendar
      - Real Madrid game if there is one today
    """
    today = datetime.date.today()
    day_label = today.strftime("%A, %d %B")
    lines = [f"☀️ *Good morning Aviv!*", f"📆 {day_label}", ""]

    # ── Today's calendar events ───────────────────────────────────────────────
    try:
        service = _get_calendar_service()
        day_start = datetime.datetime(today.year, today.month, today.day,
                                      tzinfo=datetime.timezone.utc)
        day_end = day_start + datetime.timedelta(days=1)

        result = service.events().list(
            calendarId="primary",
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])
        if events:
            lines.append("📅 *Today's schedule:*")
            for event in events:
                start_raw = event["start"].get("dateTime") or event["start"].get("date")
                title = event.get("summary", "?")
                if "T" in start_raw:
                    time_str = _local_time(_parse_event_dt(start_raw))
                    lines.append(f"  • {time_str} — {title}")
                else:
                    lines.append(f"  • {title} (all day)")
        else:
            lines.append("📅 No events scheduled today.")

    except Exception as exc:
        logger.error("Morning briefing — calendar error: %s", exc)
        lines.append("📅 (Couldn't load calendar)")

    # ── Real Madrid game ──────────────────────────────────────────────────────
    game = get_todays_game_from_rm_calendar()
    if game:
        kickoff_utc, title = game
        lines.append("")
        lines.append("⚽ *Real Madrid game today!*")
        lines.append(f"  🕐 Kick-off: {_local_time(kickoff_utc)}")
        lines.append(f"  🏆 {title}")

    send_whatsapp_notification("\n".join(lines))
    logger.info("Morning briefing sent")


# ── Public entry point ────────────────────────────────────────────────────────
def start_scheduler():
    """
    Initialise and start the APScheduler background scheduler.
    Call this once when the Flask app starts.
    """
    israel = ZoneInfo("Asia/Jerusalem")

    # Morning briefing — 08:00 Israel time every day
    _scheduler.add_job(
        send_morning_briefing,
        CronTrigger(hour=8, minute=0, timezone=israel),
        id="morning_briefing",
        replace_existing=True,
    )

    # Game-day check — 08:00 UTC (schedules the 3 match notifications)
    _scheduler.add_job(
        _check_todays_game,
        CronTrigger(hour=8, minute=0, timezone=ZoneInfo("UTC")),
        id="daily_game_check",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Scheduler started — morning briefing at 08:00 Israel, game check at 08:00 UTC")
    _check_todays_game()  # run immediately on startup to catch games before the daily window
