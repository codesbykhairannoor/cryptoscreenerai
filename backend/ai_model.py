import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

# Configure the Gemini API with the provided key
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

def analyze_and_sort(df):
    # Filter for active coins with positive momentum
    df_filtered = df[(df['quoteVolume'] > 1000000) & (df['priceChangePercent'] > 0)]
    # Sort by highest momentum
    df_sorted = df_filtered.sort_values(by='priceChangePercent', ascending=False).head(10)
    
    # Fallback to highest volume if not enough positive momentum coins
    if len(df_sorted) < 5:
        df_sorted = df.sort_values(by='quoteVolume', ascending=False).head(10)
        
    return df_sorted.to_dict('records')

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