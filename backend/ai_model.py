import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Configure the Gemini API with the provided key
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

def analyze_market_data(data_json):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
        Analyze this crypto/market data and provide 3 hot trading recommendations.
        Focus on whale activity, RSI momentum, and MTF trend confirmation.
        Data: {data_json}
        Format your response in professional Indonesian, use emojis, and be concise.
        Include Entry, TP, and SL for each recommendation.
        """
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"AI Analysis Error: {e}")
        return "Gagal melakukan analisis AI. Silakan cek koneksi atau API Key Anda."