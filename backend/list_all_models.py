import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

def list_all():
    try:
        print("Fetching model list from Google...")
        models = client.models.list()
        for model in models:
            # Print just the name to be safe
            try:
                print(f"Model Name: {model.name}")
            except:
                print(f"Model Object: {model}")
    except Exception as e:
        print(f"Error listing models: {e}")

if __name__ == "__main__":
    list_all()
