# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 10: MULTI-TIMEFRAME (MTF) SYNERGY AUDIT
Tujuan: Mencari bug di mana 15m Bullish tapi 5m Bearish (Trap Entry).
Data: Sinkronisasi 5m dan 15m candles.
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"

COINS = ["NEARUSDT", "INJUSDT", "TIAUSDT", "SEIUSDT"]

def get_candles(symbol, gran, limit=300):
    params = {"symbol":symbol,"granularity":gran,"limit":limit,"productType":"USDT-FUTURES"}
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
        data = r.get("data", [])
        return sorted([[float(c[i]) for i in range(6)] for c in data], key=lambda x: x[0])
    except:
        return []

def run_mtf_audit():
    print("="*90)
    print("ROUND 10: MTF SYNERGY AUDIT - BUG HUNTING (5m vs 15m Alignment)")
    print("="*90)

    for sym in COINS:
        c15 = get_candles(sym, "15m", 300)
        c5  = get_candles(sym, "5m", 900) # 3x more to match 15m time range
        
        if not c15 or not c5: continue
        
        print(f"\nAUDITING {sym}:")
        trap_count = 0
        alignment_count = 0
        
        # Match time
        c5_map = {int(c[0]): c for c in c5}
        
        for i in range(20, len(c15)):
            ts = int(c15[i][0])
            # 15m Signal: Price above 15m EMA20 (Simple momentum proxy)
            closes_15 = [c[4] for c in c15[i-20:i+1]]
            ema15 = sum(closes_15)/len(closes_15)
            
            if closes_15[-1] > ema15:
                # Check 5m state at the same time
                c5_now = c5_map.get(ts)
                if c5_now:
                    # 5m state: check if 5m is overextended (RSI > 75) or below its own EMA
                    # This represents a "Trap" where 15m looks good but 5m is exhausted.
                    idx5 = next((j for j, c in enumerate(c5) if int(c[0]) == ts), None)
                    if idx5 and idx5 > 20:
                        closes_5 = [c[4] for c in c5[idx5-20:idx5+1]]
                        ema5 = sum(closes_5)/len(closes_5)
                        
                        if closes_5[-1] < ema5: # 15m UP but 5m DOWN (Conflict!)
                            trap_count += 1
                        else:
                            alignment_count += 1
                            
        total = trap_count + alignment_count
        trap_pct = round(trap_count/total*100, 1) if total else 0
        print(f"  Alignment: {alignment_count} | Traps Found: {trap_count} | Trap Risk: {trap_pct}%")
        
        if trap_pct > 20:
            print(f"  [BUG ALERT] {sym} memiliki resiko '15m Trap' yang tinggi ({trap_pct}%).")
            print(f"  Solusi: Perketat filter 5m VWAP di engine.")

if __name__=="__main__":
    run_mtf_audit()
