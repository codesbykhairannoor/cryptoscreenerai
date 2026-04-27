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

def smart_trade_decision(symbol, technicals, news):
    """
    Final Filter: Uses Gemini to decide if we should actually place the trade.
    Returns: (bool, str_reason)
    """
    if not client: return False, "Gemini Client not initialized"
    
    try:
        prompt = f"""
        TIDAK BOLEH ASAL TRADE! Anda adalah Risk Manager Pro.
        Analisa apakah kita harus masuk ke trade ini sekarang?
        
        Aset: {symbol}
        Data Teknikal: {technicals}
        Berita Terkini: {news}
        
        Aturan: 
        1. Hanya katakan SETUJU jika teknikal (RSI, Trend, OB/FVG) DAN berita mendukung.
        2. Jika berita negatif atau teknikal jenuh (overbought), katakan TOLAK.
        
        Format Jawaban Harus:
        KEPUTUSAN: [SETUJU/TOLAK]
        ALASAN: [Berikan alasan singkat dan padat]
        """
        
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        text = response.text
        decision = "SETUJU" in text.upper()
        return decision, text
    except Exception as e:
        return False, f"AI Error: {str(e)}"

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
            model='gemini-2.0-flash',
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"AI Analysis Error: {e}")
        return "Gagal melakukan analisis AI. Silakan cek koneksi atau API Key Anda."