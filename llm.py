import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

MODEL = "gemini-2.5-flash"

# Fail fast with a clear message instead of an SDK traceback deep inside genai.Client.
# NEVER print or log the key itself.
if not os.getenv("GEMINI_API_KEY"):
    raise RuntimeError("GEMINI_API_KEY not set — copy .env.example to .env and add your key")

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def get_llm_response(prompt):
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt
        )
        if not response.text:
            # Call succeeded but no text came back (safety block / empty candidates).
            print(f"LLM EMPTY RESPONSE: prompt_feedback={response.prompt_feedback!r}")
            return None
        return response.text
    except Exception as e:
        print(f"LLM ERROR: {e}")   # see the real reason
        return None

if __name__ == "__main__":
    print(get_llm_response("Say 'connection working' if you can read this."))
