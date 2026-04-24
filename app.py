import os
import logging
import datetime
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from anthropic import Anthropic
from dotenv import load_dotenv

# Google Calendar API imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
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
        # 2. Send the message to Claude for processing
        logger.info("Sending message to Claude...")
        claude_response = client.messages.create(
            model="claude-haiku-4-5",  # Fast & cheap — perfect for WhatsApp
            max_tokens=350,            # Limit response length to keep costs low
            system=system_prompt,
            messages=[
                {"role": "user", "content": incoming_msg}
            ]
        )

        # 2. הבדיקה הקריטית: האם קלוד רוצה להפעיל כלי?
        if response.stop_reason == "tool_use":
            # מוצאים איזה כלי הוא ביקש
            tool_use = next(block for block in response.content if block.type == "tool_use")
            
            if tool_use.name == "get_calendar_events":
                # מפעילים את הפונקציה שכתבנו קודם
                observation = get_upcoming_events()
                
                # שולחים לקלוד חזרה את התוצאה כדי שינסח תשובה
                response = client.messages.create(
                    model="claude-haiku-4-5",
                    max_tokens=512,
                    system=system_prompt,
                    tools=tools,
                    messages=[
                        {"role": "user", "content": incoming_msg},
                        {"role": "assistant", "content": response.content},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_use.id,
                                    "content": observation,
                                }
                            ],
                        },
                    ],
                )

        # 3. Extract the text from Claude's response
        reply_text = claude_response.content[0].text
        logger.info("Claude replied: %s", reply_text)

        # 4. Pass the text to Twilio to send back via WhatsApp
        msg.body(reply_text)

    except Exception as e:
        logger.error("Error while processing message: %s", e, exc_info=True)
        msg.body("Sorry, something went wrong on my end. Check the logs for details.")

    return str(resp)


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