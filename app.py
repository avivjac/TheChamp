import os
import logging
import logging.handlers
import datetime
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from anthropic import Anthropic
from dotenv import load_dotenv

import real_madrid
import database

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

# ── Load environment variables from .env ───────────────────────────────────────
load_dotenv()
logger.info("Environment variables loaded from .env")

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise ValueError("ANTHROPIC_API_KEY not found in .env — check the file!")
logger.info("Anthropic API key found")

app = Flask(__name__)

# ── Connect to Claude (the AI brain) ──────────────────────────────────────────
client = Anthropic(api_key=api_key)
logger.info("Anthropic client initialised")


def _system_prompt() -> str:
    today = datetime.date.today().strftime("%A, %d %B %Y")
    return (
        f"You are 'TheChamp', Aviv's personal WhatsApp assistant. "
        f"Aviv is a CS student who loves Real Madrid. "
        f"Today is {today}. "
        f"Reply short and casual — like a friend texting back. Don't over-explain. "
        f"You understand both Hebrew and English; always reply in the same language Aviv wrote in. "
        f"When a tool returns a formatted list or structured result, send it to the user exactly as-is — do not paraphrase or summarise it into a sentence. "
        f"Use tools proactively: call add_calendar_event whenever Aviv wants to schedule anything, "
        f"get_calendar_events when he asks about his schedule, "
        f"get_real_madrid_updates for anything Real Madrid, "
        f"and the shopping list tools when he mentions groceries or a shopping list."
    )


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
    },
    {
        "name": "add_calendar_event",
        "description": (
            "Add a new event to the user's Google Calendar. "
            "Use this when the user asks to add, create, schedule, or remind about something. "
            "Convert natural language dates ('tomorrow', 'next Monday') to YYYY-MM-DD. "
            "Convert times to 24-hour HH:MM. If no duration is given, default to 60 minutes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Event title."
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format."
                },
                "time": {
                    "type": "string",
                    "description": "Start time in 24-hour HH:MM format (local time)."
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Duration in minutes (default 60)."
                }
            },
            "required": ["title", "date", "time"]
        }
    },
    {
        "name": "add_to_shopping_list",
        "description": (
            "Add one or more items to the shopping list. "
            "Use this whenever Aviv says he needs to buy something or wants to add to the list. "
            "Pass all items in a single call as a list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of items to add (e.g. ['milk', 'eggs', 'bread'])."
                }
            },
            "required": ["items"]
        }
    },
    {
        "name": "view_shopping_list",
        "description": "Show the current shopping list. Use when Aviv asks what's on the list. Send the tool result directly to the user without any changes.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "remove_from_shopping_list",
        "description": (
            "Remove a single item from the shopping list (marks it as bought). "
            "Use when Aviv says he bought something or wants to remove an item."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {
                    "type": "string",
                    "description": "The item name to remove."
                }
            },
            "required": ["item"]
        }
    },
    {
        "name": "clear_shopping_list",
        "description": "Delete all items from the shopping list. Use only when Aviv explicitly asks to clear or empty the whole list.",
        "input_schema": {"type": "object", "properties": {}}
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
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=_system_prompt(),
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
                observation = real_madrid.get_real_madrid_updates()
            elif tool_use.name == "add_calendar_event":
                inp = tool_use.input
                observation = add_calendar_event(
                    title=inp["title"],
                    date=inp["date"],
                    time=inp["time"],
                    duration_minutes=inp.get("duration_minutes", 60),
                )
            elif tool_use.name == "add_to_shopping_list":
                observation = database.add_shopping_items(tool_use.input["items"])
            elif tool_use.name == "view_shopping_list":
                observation = database.get_shopping_list()
            elif tool_use.name == "remove_from_shopping_list":
                observation = database.remove_shopping_item(tool_use.input["item"])
            elif tool_use.name == "clear_shopping_list":
                observation = database.clear_shopping_list()
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
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=_system_prompt(),
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


# ── Google Calendar helpers ────────────────────────────────────────────────────
def get_upcoming_events(max_results=10):
    """Fetch the next `max_results` events from the user's primary Google Calendar."""
    try:
        service = real_madrid.get_calendar_service()
        now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        logger.info("Fetching up to %d upcoming calendar events", max_results)
        result = service.events().list(
            calendarId='primary', timeMin=now,
            maxResults=max_results, singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = result.get('items', [])
        if not events:
            return "You have no upcoming events — your schedule is clear!"
        summary = "Here's what I found in your calendar:\n"
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary += f"- {event['summary']} at {start}\n"
        return summary
    except Exception as exc:
        logger.error("get_upcoming_events failed: %s", exc)
        return f"❌ Couldn't load calendar: {exc}"


def add_calendar_event(title: str, date: str, time: str, duration_minutes: int = 60) -> str:
    """Add a single event to the user's primary Google Calendar."""
    logger.info("add_calendar_event called: title=%r date=%r time=%r duration=%r",
                title, date, time, duration_minutes)
    try:
        parts = time.strip().split(":")
        time_clean = f"{int(parts[0]):02d}:{parts[1][:2]}"
        start_naive = datetime.datetime.fromisoformat(f"{date.strip()}T{time_clean}")
        start_local = start_naive.astimezone()
        end_local = start_local + datetime.timedelta(minutes=int(duration_minutes))
    except (ValueError, TypeError) as exc:
        logger.error("Date/time parse error: %s", exc)
        return f"❌ Couldn't parse date/time (got date='{date}', time='{time}'): {exc}"

    try:
        service = real_madrid.get_calendar_service()
        event_body = {
            'summary': title,
            'start': {'dateTime': start_local.isoformat()},
            'end':   {'dateTime': end_local.isoformat()},
        }
        created = service.events().insert(calendarId='primary', body=event_body).execute()
        logger.info("Created calendar event '%s': %s", title, created.get('htmlLink'))
        return f"✅ Added '{title}' on {start_local.strftime('%A %d %b, %H:%M')} ({duration_minutes} min)"
    except Exception as exc:
        logger.error("Failed to create calendar event: %s", exc)
        return f"❌ Failed to add event: {exc}"


# ── Health-check endpoint ──────────────────────────────────────────────────────
@app.route("/whatsapp", methods=['GET'])
def health_check():
    logger.info("Health check requested")
    return "✅ TheChamp bot is alive!", 200


real_madrid.start_scheduler()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    logger.info("Starting TheChamp Flask server on port %d (debug=%s)", port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)