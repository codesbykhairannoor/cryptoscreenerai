# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 23: THE SNIPER ACCURACY AUDIT
Membandingkan v18.0 (Tanpa Sniper) vs v19.0 (Dengan Sniper Wick Rejection).
Mencari bukti kenaikan Win Rate.
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012

# CONFIG v19.0
WICK_REJ_MIN = 0.35 # 35% Wick

def get_all_symbols():
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES").json()
        data = r.get("data", [])
        return [t['symbol'] for t in sorted(data, key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)[:50]]
    except: return []

def get_candles_deep(symbol):
    params = {"symbol":symbol,"granularity":"15m","limit":300,"productType":"USDT-FUTURES"}
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
        return sorted([[float(c[i]) for i in range(6)] for c in r.get("data", [])], key=lambda x: x[0])
    except: return []

def audit_sniper(candles, use_sniper=False):
    wins = losses = pnl = 0
    for i in range(20, len(candles)-20):
        o, h, l, c = candles[i][1], candles[i][2], candles[i][3], candles[i][4]
        cl = [x[4] for x in candles[i-10:i+1]]
        ma = sum(cl)/len(cl)
        
        if c > ma:
            # SNIPER FILTER
            if use_sniper:
                total_range = h - l
                if total_range > 0:
                    lower_wick = (min(o, c) - l) / total_range
                    if lower_wick < WICK_REJ_MIN: continue # Skip jika tidak ada penolakan harga
            
            # TRADE SIMULATION
            ep = c
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

def run_sniper_audit():
    print("="*95)
    print("ROUND 23: THE SNIPER ACCURACY AUDIT - v18.0 VS v19.0")
    print("="*95)
    
    symbols = get_all_symbols()
    results = {"v18.0 (No Sniper)": {"w":0, "l":0}, "v19.0 (Sniper)": {"w":0, "l":0}}
    
    for sym in symbols:
        candles = get_candles_deep(sym)
        if not candles: continue
        
        for mode in ["v18.0 (No Sniper)", "v19.0 (Sniper)"]:
            w, l = audit_sniper(candles, use_sniper=(mode=="v19.0 (Sniper)"))
            results[mode]["w"] += w
            results[mode]["l"] += l
            
    print("\nFINAL WIN-RATE COMPARISON:")
    for mode, r in results.items():
        total = r["w"] + r["l"]
        wr = round(r["w"]/total*100, 1) if total else 0
        print(f"  {mode:<20} | Trades: {total:<5} | Win Rate: {wr:>5}%")

if __name__=="__main__":
    run_sniper_audit()
