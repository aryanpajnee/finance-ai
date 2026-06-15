import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def get_llm_response(prompt):
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash" , 
            contents= prompt
        )
        return response.text
    except Exception as e:
        print(f"LLM ERROR: {e}")   # see the real reason
        return None

if __name__ == "__main__":
    print(get_llm_response("Say 'connection working' if you can read this."))