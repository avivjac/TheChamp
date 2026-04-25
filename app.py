import os
import logging
import logging.handlers
import datetime
import requests as http_requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from anthropic import Anthropic
from dotenv import load_dotenv

# Google Calendar API imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ── Logging setup — console + rotating file ───────────────────────────────────
_log_formatter = logging.Formatter(
    fmt="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Console handler (existing behaviour)
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_formatter)

# File handler — rotates at 5 MB, keeps last 3 files
_file_handler = logging.handlers.RotatingFileHandler(
    filename="app.log",
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=3,
    encoding="utf-8",
)
_file_handler.setFormatter(_log_formatter)

logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _file_handler])
logger = logging.getLogger(__name__)

# ── Google Calendar API scope — read + write access ────────────────────────────
SCOPES = ['https://www.googleapis.com/auth/calendar']

# ── Load environment variables from .env ───────────────────────────────────────
load_dotenv()
logger.info("Environment variables loaded from .env")

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise ValueError("ANTHROPIC_API_KEY not found in .env — check the file!")
logger.info("Anthropic API key found")

rapidapi_key = os.environ.get("FOOTBALL_API_KEY")
if not rapidapi_key:
    raise ValueError("FOOTBALL_API_KEY not found in .env — check the file!")
logger.info("RapidAPI (football) key found")

app = Flask(__name__)

# ── Connect to Claude (the AI brain) ──────────────────────────────────────────
client = Anthropic(api_key=api_key)
system_prompt = (
    "You are a smart personal assistant on WhatsApp named 'TheChamp'. "
    "You are Aviv's assistant — a computer science student who loves Real Madrid. "
    "Always reply short, sharp, and casual (like a friend). Don't over-explain."
)
logger.info("Anthropic client initialised")

LALIGA_CODE = 87
CHAMPIONS_LEAGUE_CODE = 42



# ── Tool definitions exposed to Claude ────────────────────────────────────────
tools = [
    {
        "name": "get_calendar_events",
        "description": "Get the user's upcoming calendar events and football matches.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_real_madrid_updates",
        "description": (
            "Fetch the latest Real Madrid match results and upcoming fixtures "
            "from a live football data API. Use this whenever the user asks "
            "about Real Madrid matches, scores, results, fixtures, or news."
        ),
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]

# ── WhatsApp webhook — handles incoming messages ───────────────────────────────
@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    # 1. Receive the incoming WhatsApp message
    incoming_msg = request.values.get('Body', '')
    logger.info("Incoming message: %s", incoming_msg)

    resp = MessagingResponse()
    msg = resp.message()

    try:
        # 2. Send the message to Claude (with tools enabled)
        logger.info("Sending message to Claude...")
        messages = [{"role": "user", "content": incoming_msg}]
        response = client.messages.create(
            model="claude-haiku-4-5",  # Fast & cheap — perfect for WhatsApp
            max_tokens=512,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        # 3. Tool-use loop — Claude may request one or more tools
        while response.stop_reason == "tool_use":
            tool_use = next(block for block in response.content if block.type == "tool_use")
            logger.info("Claude requested tool: %s", tool_use.name)

            # Dispatch to the correct tool handler
            if tool_use.name == "get_calendar_events":
                observation = get_upcoming_events()
            elif tool_use.name == "get_real_madrid_updates":
                observation = get_real_madrid_updates()
            else:
                observation = f"Tool '{tool_use.name}' is not implemented."

            logger.info("Tool result: %s", observation[:120])

            # Append assistant's tool-use turn + the tool result, then re-call Claude
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": observation,
                    }
                ],
            })
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=512,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )

        # 4. Extract the final text reply
        reply_text = next(
            (block.text for block in response.content if hasattr(block, "text")),
            "I couldn't generate a reply — please try again."
        )
        logger.info("Claude replied: %s", reply_text)

        # 5. Pass the text to Twilio to send back via WhatsApp
        msg.body(reply_text)

    except Exception as e:
        logger.error("Error while processing message: %s", e, exc_info=True)
        msg.body("Sorry, something went wrong on my end. Check the logs for details.")

    return str(resp)


# ── Real Madrid football updates helper ───────────────────────────────────────
def _extract_list(obj):
    """Walk a JSON value until we find a list (BFS over dict values)."""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        # Prefer well-known keys first
        for key in ("matches", "response", "data", "events", "fixtures", "results"):
            if key in obj and isinstance(obj[key], list):
                return obj[key]
        # Fall back: recurse into all values
        for val in obj.values():
            result = _extract_list(val)
            if result is not None:
                return result
    return None


def get_real_madrid_updates():
    """Fetches the latest Real Madrid matches (results + upcoming fixtures) from
    the Free API Live Football Data on RapidAPI."""
    url = "https://free-api-live-football-data.p.rapidapi.com/football-matches-search"
    headers = {
        "x-rapidapi-host": "free-api-live-football-data.p.rapidapi.com",
        "x-rapidapi-key": rapidapi_key,
    }
    params = {"search": "Real Madrid"}

    logger.info("Calling RapidAPI football search for Real Madrid")
    try:
        resp = http_requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error("Football API error: %s", exc)
        return "Couldn't fetch Real Madrid data right now — try again later."

    # Log the raw response keys so we can debug future shape changes
    logger.info("Football API raw response keys: %s", list(data.keys()) if isinstance(data, dict) else type(data).__name__)

    # Robustly extract a list from whatever shape the API returned
    matches = _extract_list(data)

    if not matches:
        logger.warning("No match list found in API response: %s", str(data)[:300])
        return "No Real Madrid matches found in the API response."

    logger.info("Found %d match entries from football API", len(matches))
    lines = ["⚽ Real Madrid — latest matches:"]
    for match in matches[:8]:  # cap at 8 to keep the WhatsApp message short
        home   = match.get("home_name") or match.get("homeTeam", {}).get("name", "?")
        away   = match.get("away_name") or match.get("awayTeam", {}).get("name", "?")
        score  = match.get("score")     or match.get("result", "vs")
        date   = match.get("date")      or match.get("event_date", "")
        status = match.get("status", "") or match.get("event_status", "")
        lines.append(f"  {home} {score} {away}  [{date}] {status}".strip())

    return "\n".join(lines)


# ── Google Calendar helper ─────────────────────────────────────────────────────
def get_upcoming_events(max_results=10):
    """Fetches the next `max_results` events from the user's primary Google Calendar."""
    creds = None

    # token.json stores the access/refresh token after the first OAuth login
    if os.path.exists('token.json'):
        logger.info("Loading existing Google credentials from token.json")
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    # If no valid credentials exist, open a browser for the OAuth login flow
    if not creds or not creds.valid:
        logger.info("No valid credentials — launching OAuth browser flow")
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
        logger.info("New credentials saved to token.json")

    service = build('calendar', 'v3', credentials=creds)

    # Fetch events from now onward (RFC3339 format required by the API)
    now = datetime.datetime.utcnow().isoformat() + 'Z'
    logger.info("Fetching up to %d upcoming calendar events", max_results)

    events_result = service.events().list(
        calendarId='primary', timeMin=now,
        maxResults=max_results, singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])

    if not events:
        logger.info("No upcoming events found")
        return "You have no upcoming events — your schedule is clear!"

    logger.info("Found %d upcoming event(s)", len(events))
    summary = "Here's what I found in your calendar:\n"
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        summary += f"- {event['summary']} at {start}\n"

    return summary


# ── Health-check endpoint ──────────────────────────────────────────────────────
@app.route("/whatsapp", methods=['GET'])
def health_check():
    logger.info("Health check requested")
    return "✅ TheChamp bot is alive!", 200


if __name__ == "__main__":
    logger.info("Starting TheChamp Flask server on port 5000")
    app.run(port=5000, debug=True)