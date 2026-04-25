import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get("ANTHROPIC_API_KEY")

print(f"Key loaded: {'✅ YES' if api_key else '❌ NO'}")
print(f"Key prefix: {api_key[:20]}..." if api_key else "No key!")
print()

# Hit the Anthropic models list endpoint
headers = {
    "x-api-key": api_key,
    "anthropic-version": "2023-06-01"
}

resp = requests.get("https://api.anthropic.com/v1/models", headers=headers)
print(f"Status code: {resp.status_code}")
print(f"Response: {resp.json()}")
