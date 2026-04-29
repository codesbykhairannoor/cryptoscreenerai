import os
import sys
from dotenv import load_dotenv

# Ensure we can import from the current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from data_fetcher import (
    fetch_all_tickers, get_technical_indicators, 
    get_retail_sentiment, detect_institutional_flow
)
from sentiment import get_crypto_news, get_global_market_data
from ai_model import analyze_and_sort

def test_bot_intelligence():
    print("[TEST] Memulai Pengetesan Otak Bot (Intelligence Check)...")
    load_dotenv()
    
    # 1. Check Global Context
    global_data = get_global_market_data()
    print(f"\n[STEP 1: GLOBAL CONTEXT]")
    print(f"Hasil: {global_data}")
    
    # 2. Fetch Market Data
    print(f"\n[STEP 2: SCANNING MARKET]")
    raw_data = fetch_all_tickers()
    if raw_data.empty:
        print("X Gagal mengambil data market.")
        return
    
    candidates = analyze_and_sort(raw_data)
    top_candidates = candidates[:3]
    print(f"Ditemukan {len(top_candidates)} kandidat awal.")
    
    # 3. Deep Analysis Confluence
    print(f"\n[STEP 3: DEEP CONFLUENCE ANALYSIS]")
    for coin in top_candidates:
        symbol = coin['symbol']
        print(f"\n--- Menganalisis {symbol} ---")
        
        # Technicals
        tech = get_technical_indicators(symbol)
        ob = tech.get('order_block', "NONE")
        fvg = tech.get('fvg', "NONE")
        flow = tech.get('inst_flow', "NORMAL")
        
        # Sentiments
        retail = get_retail_sentiment(symbol)
        news = get_crypto_news(symbol)
        
        print(f"Structure: OB={ob} | FVG={fvg}")
        print(f"Inst. Flow: {flow}")
        print(f"Retail L/S: {retail['ratio']} ({retail['sentiment']})")
        print(f"News Insight: {news}")
        
        # Decision Logic
        should_trade = False
        if (ob != "NONE" or fvg != "NONE"):
            if flow in ["INSTITUTIONAL_ABSORPTION", "INSTITUTIONAL_ACCUMULATION"]:
                if retail['ratio'] < 1.5:
                    should_trade = True
        
        if should_trade:
            print(f"OK STATUS: [VALID] Bot AKAN mengambil trade ini!")
        else:
            print(f"WAIT STATUS: [REJECT] Belum cukup kuat (Menunggu Confluence).")

if __name__ == "__main__":
    test_bot_intelligence()
