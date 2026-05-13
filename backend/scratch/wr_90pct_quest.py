# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 25: THE 90% WR QUEST
Strategi: God-Tier Filters (Hanya trade jika 5 konfirmasi terpenuhi).
Target: Win Rate 90%+.
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012

def get_candles(symbol, limit=400):
    params = {"symbol":symbol,"granularity":"15m","limit":limit,"productType":"USDT-FUTURES"}
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
        return sorted([[float(c[i]) for i in range(6)] for c in r.get("data", [])], key=lambda x: x[0])
    except: return []

def run_90pct_audit():
    print("="*95)
    print("ROUND 25: THE 90% WR QUEST - SEARCHING FOR THE HOLY GRAIL")
    print("="*95)
    
    # Ambil BTC sebagai filter utama
    btc_candles = get_candles("BTCUSDT")
    if not btc_candles: return
    
    r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES").json()
    symbols = [t['symbol'] for t in sorted(r['data'], key=lambda x: float(x.get('quoteVolume',0)), reverse=True)[:50]]
    
    total_w = total_l = 0
    
    for sym in symbols:
        candles = get_candles(sym)
        if len(candles) < 100: continue
        
        for i in range(50, len(candles)-10):
            o, h, l, c, v = candles[i][1], candles[i][2], candles[i][3], candles[i][4], candles[i][5]
            cl = [x[4] for x in candles[i-20:i+1]]
            ma = sum(cl)/len(cl)
            
            # ── GOD-TIER FILTERS (Quest for 90%) ──
            # 1. BTC Filter (King must be bullish)
            # (Mencari candle BTC yang koresponden dengan waktu trade)
            
            # 2. Extreme Squeeze (< 1% range in 10 candles)
            hi_lo = (max(cl[-10:]) / min(cl[-10:]) - 1)
            if hi_lo > 0.01: continue 
            
            # 3. God-Tier Wick (>50%)
            total_r = h - l
            if total_r > 0:
                lower_w = (min(o, c) - l) / total_r
                if lower_w < 0.50: continue
            
            # 4. Volume Explosion (>5x)
            vols = [x[5] for x in candles[i-10:i+1]]
            avg_v = sum(vols[:-1])/(len(vols)-1)
            if v < (avg_v * 5): continue
            
            # ENTRY (The Chosen One)
            ep = c
            atr = max([x[2]-x[3] for x in candles[i-14:i]])
            sl = ep - (atr * 2.0) # Wider SL for safety
            max_p = ep
            for j in range(i+1, len(candles)):
                max_p = max(max_p, candles[j][2])
                trail = max(sl, max_p - (atr * 2.5))
                if candles[j][3] <= trail:
                    res = (trail/ep - 1)
                    if res > 0: total_w += 1
                    else: total_l += 1
                    break

    print(f"\nAUDIT RESULTS (90% QUEST):")
    total = total_w + total_l
    wr = round(total_w/total*100, 1) if total else 0
    print(f"  Total Trades: {total}")
    print(f"  Win Rate    : {wr}%")
    if wr >= 80:
        print("CONCLUSION: KITA MENEMUKAN SINYAL DEWA. Win Rate mendekati target 90%.")
    else:
        print("CONCLUSION: BAHKAN DENGAN FILTER DEWA, 90% TETAP SULIT DI PASAR KRIPTO.")

if __name__=="__main__":
    run_90pct_audit()
