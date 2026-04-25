import os
from anthropic import Anthropic
from dotenv import load_dotenv

# Load API key from .env
load_dotenv()
api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise ValueError("ANTHROPIC_API_KEY not found in .env!")

# Create the Claude client
client = Anthropic(api_key=api_key)
system_prompt = "אתה עוזר אישי חכם בווטסאפ בשם 'הצ'מפ'. אתה העוזר של אביב, סטודנט למדעי המחשב ואוהב את ריאל מדריד. תענה תמיד קצר, קולע, ובגובה העיניים (כמו 'אח'). אל תחפור."

# Claude API test
def manual_test(prompt):
    try:
        claude_response = client.messages.create(
            model="claude-haiku-4-5-20251001",  # ✅ fast & cheap, perfect for WhatsApp
            max_tokens=350,
            system=system_prompt,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        reply_text = claude_response.content[0].text
        return reply_text  # ✅ return is inside try, so reply_text is always set

    except Exception as e:
        return f"❌ Error: {e}"  # ✅ always returns something, even on failure

# main
if __name__ == "__main__":
    # Test-1
    #print("Test 1:", manual_test("מה קורה?"))
    # Test-2
    #print("Test 2:", manual_test("מה מזג האוויר היום?"))
    # Test-3
    print("Test 3:", manual_test(input("You: ")))