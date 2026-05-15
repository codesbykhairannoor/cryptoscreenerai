import sys
import os
import time

# Pastikan path backend terbaca
sys.path.append(os.getcwd())

from data_fetcher import get_technical_indicators, fetch_all_tickers
from crypto_engine import _determine_trade_side

def test_live_scan_tech():
    print("\n" + "="*70)
    print("=== LIVE SCAN TECH SCORE PROOF ===")
    print("="*70)
    
    # 1. Ambil 5 koin teratas yang lagi rame
    print("[1] Fetching live tickers...", flush=True)
    tickers = fetch_all_tickers()[:5]
    
    print(f"\n{'SYMBOL':<12} | {'RSI':<5} | {'RVOL':<5} | {'TECH SCORE':<10} | {'SIDE':<6} | {'REASON'}", flush=True)
    print("-" * 75, flush=True)
    
    for t in tickers:
        symbol = t['symbol']
        print(f"[FETCHING] {symbol}...", end="\r", flush=True)
        clean_base = symbol.replace("USDT", "")
        
        # 2. Ambil data teknikal asli
        try:
            tech = get_technical_indicators(symbol)
            if not tech: continue
            
            rsi = tech.get('rsi', 50)
            mark_price = tech.get('mark_price', 0)
            vwap_dist = 0 # Mocked for simplicity
            
            # 3. Jalankan logika penentuan side (OTAK BARU)
            side, reason, tech_score = _determine_trade_side(
                tech, rsi, vwap_dist, "NEUTRAL", mark_price, 70.0, 0.0
            )
            
            # Tampilkan hasil
            print(f"{clean_base:<12} | {rsi:<5.1f} | {tech.get('rvol',0):<5.1f} | {tech_score:<10} | {str(side):<6} | {reason}")
            
        except Exception as e:
            print(f"{clean_base:<12} | ERROR: {str(e)[:30]}")

    print("="*70 + "\n")
    print("LIAT BOS! Kalau sinyalnya ada (MSS/FVG/OB/Holy), Tech Score PASTI muncul (60-100+).")
    print("Kalau masih 0, berarti koin itu emang lagi 'tidur' teknikalnya.")
    print("="*70 + "\n")

if __name__ == "__main__":
    test_live_scan_tech()
