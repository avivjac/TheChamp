# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

TheChamp is a personal WhatsApp AI assistant for Aviv, built as a Flask app. Incoming WhatsApp messages are received via a Twilio webhook, forwarded to Claude (Anthropic API) with tool definitions, and the bot dispatches tool calls before sending the final reply back via Twilio. It also sends proactive scheduled messages via GitHub Actions.

## Running locally

```powershell
# Terminal 1 — activate venv and start the Flask server
.\venv\Scripts\Activate.ps1
python app.py

# Terminal 2 — expose port 5000 via ngrok
ngrok http 5000
```

Set the Twilio sandbox webhook to the ngrok URL: `https://<subdomain>.ngrok-free.dev/whatsapp`

## Running tests

```powershell
# All tests (integration — hits real Supabase, ~50s)
python -m pytest tests/ -v

# Single file
python -m pytest tests/test_real_madrid.py -v
python -m pytest tests/test_database.py -v
python -m pytest tests/test_todo.py -v
```

- **Unit tests** (no network): `TestIsFirstTeam`, `TestParseEventDt`, `TestFormatters` in `test_real_madrid.py`
- **Integration tests** (real APIs): skipped automatically if `FOOTBALL_API_KEY` / Supabase credentials / Google credentials are missing
- Database test items use prefix `TEST_` (shopping) and `TEST_TODO_` (to-do) to avoid polluting real data

## Required environment variables (`.env`)

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | Twilio REST client |
| `TWILIO_WHATSAPP_NUMBER` | From-number for outbound messages |
| `MY_PHONE_NUMBER` | Aviv's WhatsApp number for proactive notifications |
| `MY_NAME` | Full name for football form submission |
| `FOOTBALL_API_KEY` | RapidAPI free-api-live-football-data key |
| `SUPABASE_URL` / `SUPABASE_KEY` | Supabase project (service-role key) |
| `GOOGLE_TOKEN_JSON` | Full contents of `token.json` for server deployments |
| `TRIGGER_TOKEN` | Shared secret for GitHub Actions → Railway trigger endpoints |
| `FORM_ENTRY_NAME` | Google Form entry ID for the name field (e.g. `entry.123456789`) |
| `FORM_ENTRY_PHONE` | Google Form entry ID for the phone field (e.g. `entry.987654321`) |

## Architecture

### Request flow

```
WhatsApp → Twilio → POST /whatsapp (app.py)
  → Claude API (tool_use loop)
    → real_madrid.py       (match data / calendar read)
    → database.py          (Supabase: shopping list + to-do list)
    → app.py               (Google Calendar write)
  → Twilio → WhatsApp reply

GitHub Actions (cron)
  → POST /trigger/morning-briefing    → real_madrid.send_morning_briefing()
  → POST /trigger/football-registration → football_registration.register_for_football()
```

### Module responsibilities

- **`app.py`** — Flask entry point. Owns all Claude tool definitions (`tools` list), the tool-dispatch loop (`while response.stop_reason == "tool_use"`), Google Calendar read/write helpers, and the protected trigger endpoints. Calls `real_madrid.start_scheduler()` on startup.

- **`real_madrid.py`** — Two concerns:
  1. **Data layer**: fetches match data from RapidAPI (`_search_matches`), filters to first-team LaLiga/Champions League only (`_is_first_team`, team ID `8633`, league IDs `{87, 42}`).
  2. **Scheduler** (`start_scheduler`): APScheduler background thread. Checks for a Real Madrid game daily at 08:00 UTC and schedules three notifications (pre-match −45 min, live +50 min, poll-until-FT every 5 min). Sends morning briefing daily at 08:00 Israel time — but this is also triggered by GitHub Actions for reliability.

- **`database.py`** — Supabase client (singleton). Two tables:
  - `shopping_list`: soft-delete via `bought=True`
  - `todo_list`: tasks with optional `due_date`; soft-delete via `done=True`. `get_todays_todos()` returns tasks due today + tasks with no due date — used by the morning briefing.

- **`football_registration.py`** — Runs every Wednesday at 20:00 via GitHub Actions. Finds next Sunday, checks Google Calendar for conflicts at 21:00–23:00 Israel time, submits the Google Form if free, adds the event to calendar, and sends a WhatsApp confirmation either way.

### Claude tools exposed to the AI

Shopping list: `add_to_shopping_list`, `view_shopping_list`, `remove_from_shopping_list`, `clear_shopping_list`
To-do list: `add_todo`, `view_todos`, `complete_todo`, `remove_todo`
Calendar: `get_calendar_events`, `add_calendar_event`
Football: `get_real_madrid_updates`

### Trigger endpoints (GitHub Actions → Railway)

Both require `X-Trigger-Token` header matching `TRIGGER_TOKEN` env var.

- `POST /trigger/morning-briefing` — sends the daily briefing
- `POST /trigger/football-registration` — runs the registration check

### Scheduled GitHub Actions

- `.github/workflows/morning_briefing.yml` — `0 5 * * *` (05:00 UTC = 08:00 Israel, summer)
- `.github/workflows/football_registration.yml` — `0 17 * * 3` (17:00 UTC = 20:00 Israel, summer, Wednesdays only)

Update cron hour by +1 in winter (Israel: UTC+3 summer, UTC+2 winter).

### Google Calendar setup

`get_calendar_service()` (in `real_madrid.py`) reads `token.json` from disk, or writes it from `GOOGLE_TOKEN_JSON` env var. Generate `token.json` locally via the OAuth flow first — the server never opens a browser. The dedicated **"Real Madrid"** calendar is used for kick-off times; the primary calendar is used for everything else.

### Deployment

Railway + gunicorn (`Procfile`: `gunicorn app:app --workers 1`). The APScheduler thread handles match notifications during uptime; morning briefings and football registration are handled by GitHub Actions to be resilient to Railway's idle sleep behaviour.
