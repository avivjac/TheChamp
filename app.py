from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    # קבלת ההודעה שהמשתמש שלח
    incoming_msg = request.values.get('Body', '').lower()
    
    # יצירת תגובה
    resp = MessagingResponse()
    msg = resp.message()
    
    if 'היי' in incoming_msg or 'הלו' in incoming_msg:
        msg.body("אהלן אביב, הצ'מפ כאן בשירותך! מה עושים היום?")
    elif 'שירזי':
        msg.body("שירזי הומו")
    elif 'בניסטי':
        msg.body("בניסטי הומו")
    else:
        msg.body(f"הצ'מפ קיבל את ההודעה: '{incoming_msg}'. בקרוב אוכל גם לענות עליה חכם!")

    return str(resp)

if __name__ == "__main__":
    app.run(port=5000)