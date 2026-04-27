import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

def test_gemini():
    models_to_try = [
        'gemini-2.0-flash',
        'gemini-2.0-flash-lite',
        'gemini-1.5-flash'
    ]
    
    for model_name in models_to_try:
        try:
            print(f"Testing model: {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents="Halo bot, apa kabar? Katakan 'AKTIF' jika kamu mendengarku."
            )
            print(f"SUCCESS: {model_name} responded: {response.text.strip()}")
            return model_name
        except Exception as e:
            print(f"FAILED: {model_name} error: {str(e)}")
            
    return None

if __name__ == "__main__":
    working_model = test_gemini()
    if working_model:
        print(f"Final Selection: {working_model}")
    else:
        print("All Gemini models failed.")
