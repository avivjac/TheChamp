import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from anthropic import Anthropic
from dotenv import load_dotenv

# טוען את המפתח הסודי מקובץ ה-.env
load_dotenv()

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise ValueError("ANTHROPIC_API_KEY not found in .env — check the file!")

app = Flask(__name__)

# מתחבר למוח של קלוד
client = Anthropic(api_key=api_key)
system_prompt = "אתה עוזר אישי חכם בווטסאפ בשם 'הצ'מפ'. אתה העוזר של אביב, סטודנט למדעי המחשב ואוהב את ריאל מדריד. תענה תמיד קצר, קולע, ובגובה העיניים (כמו 'אח'). אל תחפור."

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    # 1. מקבלים את ההודעה מהווטסאפ שלך
    incoming_msg = request.values.get('Body', '')
    
    resp = MessagingResponse()
    msg = resp.message()
    
    try:
        # 2. שולחים את ההודעה לקלוד שיחשוב עליה
        claude_response = client.messages.create(
            model="claude-haiku-4-5-20251001",  # ✅ fast & cheap, perfect for WhatsApp
            max_tokens=350, # מגביל את אורך התשובה כדי לא לבזבז לך סתם כסף
            system=system_prompt,
            messages=[
                {"role": "user", "content": incoming_msg}
            ]
        )
        
        # 3. שולפים את הטקסט שקלוד כתב
        reply_text = claude_response.content[0].text
        
        # 4. מעבירים את הטקסט לטוויליו שישלח אליך לווטסאפ
        msg.body(reply_text)
        
    except Exception as e:
        print(f"Error: {e}")
        msg.body("אח שלי, יש לי איזה באג במוח. תן שנייה לבדוק את הלוגים.")

    return str(resp)

@app.route("/whatsapp", methods=['GET'])
def health_check():
    return "✅ TheChamp bot is alive!", 200

if __name__ == "__main__":
    app.run(port=5000, debug=True)