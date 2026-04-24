import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

# Configure the Gemini API with the provided key
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

def analyze_market_data(data_json):
    if not client:
        return "API Key Gemini belum diset di .env"
    try:
        prompt = f"""
        Analyze this crypto/market data and provide 3 hot trading recommendations.
        Focus on whale activity, RSI momentum, and MTF trend confirmation.
        Data: {data_json}
        Format your response in professional Indonesian, use emojis, and be concise.
        Include Entry, TP, and SL for each recommendation.
        """
        
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"AI Analysis Error: {e}")
        return "Gagal melakukan analisis AI. Silakan cek koneksi atau API Key Anda."