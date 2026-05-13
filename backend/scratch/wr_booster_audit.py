# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 22: THE WIN-RATE BOOSTER AUDIT
Duel:
1. v18.0 (Breakout Entry) - Strategi Sekarang
2. v19.0 (Retest Entry) - Menunggu harga balik ke EMA-20 sebelum beli
Data: 100 Koin, 1000 Candle.
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012

def get_all_symbols():
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES").json()
        data = r.get("data", [])
        return [t['symbol'] for t in sorted(data, key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)[:50]]
    except: return []

def get_candles_deep(symbol):
    params = {"symbol":symbol,"granularity":"5m","limit":500,"productType":"USDT-FUTURES"}
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
        return sorted([[float(c[i]) for i in range(6)] for c in r.get("data", [])], key=lambda x: x[0])
    except: return []

def test_wr_booster(candles, mode="BREAKOUT"):
    wins = losses = 0
    for i in range(50, len(candles)-50):
        cl = [x[4] for x in candles[i-20:i+1]]
        ema20 = sum(cl)/20 # Simplified EMA
        
        # Sinyal Momentum
        if cl[-1] > ema20 and cl[-1] > cl[-2]:
            ep = 0
            if mode == "BREAKOUT":
                ep = cl[-1] # Beli langsung
            elif mode == "RETEST":
                # Tunggu harga menyentuh EMA-20 dalam 5 candle ke depan
                for k in range(i+1, i+6):
                    if candles[k][3] <= ema20:
                        ep = ema20 # Beli di jemputan
                        break
            
            if ep > 0:
                atr = max([x[2]-x[3] for x in candles[i-14:i]])
                sl = ep - (atr * 1.5)
                max_p = ep
                for j in range(i+1, len(candles)):
                    max_p = max(max_p, candles[j][2])
                    trail = max(sl, max_p - (atr * 2.0))
                    if candles[j][3] <= trail:
                        res = (trail/ep - 1)
                        if res > 0: wins += 1
                        else: losses += 1
                        break
    return wins, losses

def run_wr_booster_audit():
    print("="*95)
    print("ROUND 22: THE WIN-RATE BOOSTER AUDIT - BREAKOUT VS RETEST")
    print("="*95)
    
    symbols = get_all_symbols()
    results = {"BREAKOUT": {"w":0, "l":0}, "RETEST": {"w":0, "l":0}}
    
    for sym in symbols:
        candles = get_candles_deep(sym)
        if not candles: continue
        
        for mode in ["BREAKOUT", "RETEST"]:
            w, l = test_wr_booster(candles, mode)
            results[mode]["w"] += w
            results[mode]["l"] += l
            
    print("\nFINAL WIN-RATE COMPARISON:")
    for mode, r in results.items():
        total = r["w"] + r["l"]
        wr = round(r["w"]/total*100, 1) if total else 0
        print(f"  MODE {mode:<10} | Trades: {total:<5} | Win Rate: {wr:>5}%")

if __name__=="__main__":
    run_wr_booster_audit()
