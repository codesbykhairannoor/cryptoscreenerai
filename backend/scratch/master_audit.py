# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 19: THE MASTER ALGORITHM AUDIT
Membandingkan 3 Strategi: 
1. Momentum murni (v15.0)
2. Momentum + VWAP Guard (v15.1)
3. Volume Squeeze (v15.2)
Data: 100 Koin, 1000 Candle per koin.
"""
import sys, os, time, requests, numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012

def get_all_symbols():
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES").json()
        data = r.get("data", [])
        return [t['symbol'] for t in sorted(data, key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)[:100]]
    except: return []

def get_candles_deep(symbol, total=1000):
    all_candles = []
    end_time = None
    for _ in range(5): 
        params = {"symbol":symbol,"granularity":"15m","limit":200,"productType":"USDT-FUTURES"}
        if end_time: params["endTime"] = end_time
        try:
            r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
            data = r.get("data", [])
            if not data: break
            all_candles.extend(data)
            end_time = data[-1][0]
        except: break
    return sorted([[float(c[i]) for i in range(6)] for c in all_candles], key=lambda x: x[0])

def test_strategy(candles, mode="A"):
    pnl = 0
    trades = 0
    wins = 0
    
    for i in range(50, len(candles)-50, 5):
        cl = [x[4] for x in candles[i-20:i+1]]
        ma20 = sum(cl)/20
        vwap = sum([x[4]*x[5] for x in candles[i-20:i+1]]) / sum([x[5] for x in candles[i-20:i+1]]) if sum([x[5] for x in candles[i-20:i+1]]) else ma20
        
        # ENTRY SIGNAL
        entry = False
        if mode == "A": # v15.0 Momentum
            if cl[-1] > ma20: entry = True
        elif mode == "B": # v15.1 Momentum + VWAP Guard
            if cl[-1] > ma20 and cl[-1] < vwap * 1.02: entry = True
        elif mode == "C": # v15.2 Volume Squeeze
            vols = [x[5] for x in candles[i-10:i+1]]
            if cl[-1] > ma20 and vols[-1] > sum(vols)/len(vols) * 2: entry = True
            
        if entry:
            ep = cl[-1]
            atr = max([x[2]-x[3] for x in candles[i-14:i]])
            sl = ep - (atr * 1.5)
            max_p = ep
            
            for j in range(i+1, len(candles)):
                max_p = max(max_p, candles[j][2])
                trail = max(sl, max_p - (atr * 2.0))
                if candles[j][3] <= trail:
                    res = (trail/ep - 1) * 1000 - (FEE*100)
                    pnl += res
                    trades += 1
                    if res > 0: wins += 1
                    break
    return pnl, trades, wins

def run_master_audit():
    print("="*95)
    print("ROUND 19: THE MASTER ALGORITHM AUDIT - 100 COINS DEEP SCAN")
    print("="*95)
    
    symbols = get_all_symbols()
    results = {"A": {"pnl":0, "t":0, "w":0}, "B": {"pnl":0, "t":0, "w":0}, "C": {"pnl":0, "t":0, "w":0}}
    
    for sym in symbols[:100]: # Audit 100 Koin
        candles = get_candles_deep(sym)
        if not candles: continue
        
        for mode in ["A", "B", "C"]:
            p, t, w = test_strategy(candles, mode)
            results[mode]["pnl"] += p
            results[mode]["t"] += t
            results[mode]["w"] += w
            
    print("\nFINAL COMPARISON RESULTS:")
    for mode, r in results.items():
        wr = round(r["w"]/r["t"]*100, 1) if r["t"] else 0
        desc = "Momentum (v15.0)" if mode=="A" else "VWAP Guard (v15.1)" if mode=="B" else "Volume Squeeze (v15.2)"
        print(f"  MODE {mode} [{desc:<20}] | Trades: {r['t']:<5} | WinRate: {wr:>5}% | Net PnL: {r['pnl']:>+11.1f}%")

if __name__=="__main__":
    run_master_audit()
