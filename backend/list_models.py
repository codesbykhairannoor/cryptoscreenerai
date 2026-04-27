import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

def list_available_models():
    try:
        print("Listing available models...")
        # Note: Depending on SDK version, listing models might differ.
        # In newer SDKs, you might need to use a specific method.
        # Let's try to just check the most common ones manually if list fails.
        
        # Test 1.5-flash-latest
        try:
            res = client.models.generate_content(model='gemini-1.5-flash-latest', contents="test")
            print("ACTIVE: gemini-1.5-flash-latest")
        except Exception as e:
            print(f"FAILED: gemini-1.5-flash-latest - {str(e)}")

        # Test 1.5-pro
        try:
            res = client.models.generate_content(model='gemini-1.5-pro', contents="test")
            print("ACTIVE: gemini-1.5-pro")
        except Exception as e:
            print(f"FAILED: gemini-1.5-pro - {str(e)}")

    except Exception as e:
        print(f"General error: {e}")

if __name__ == "__main__":
    list_available_models()
