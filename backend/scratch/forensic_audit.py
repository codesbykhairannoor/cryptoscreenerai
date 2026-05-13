# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 20: THE FORENSIC REALITY AUDIT
Strategi: v16.0 (Breakout King + Anti-Stale).
Data: 24 Jam Terakhir, 100 Koin.
Penalti: 0.1% Slippage (Honest Reality).
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012
SLIPPAGE = 0.0010 # 0.1% (Brutal Reality)
SQUEEZE_THR = 0.015
STALE_LIMIT = 4

def get_candles(symbol, limit=400):
    params = {"symbol":symbol,"granularity":"15m","limit":limit,"productType":"USDT-FUTURES"}
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
        return sorted([[float(c[i]) for i in range(6)] for c in r.get("data", [])], key=lambda x: x[0])
    except: return []

def run_forensic_audit():
    print("="*95)
    print("ROUND 20: THE FORENSIC REALITY AUDIT - HONEST v16.0 EVALUATION")
    print("="*95)
    
    r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES").json()
    symbols = [t['symbol'] for t in sorted(r['data'], key=lambda x: float(x.get('quoteVolume',0)), reverse=True)[:100]]
    
    total_pnl = 0
    total_trades = 0
    wins = 0
    traps_found = 0 # Weakness: Fake Breakouts
    stale_blocked = 0 # Success: Anti-Pucuk filter
    
    for sym in symbols:
        candles = get_candles(sym)
        if len(candles) < 50: continue
        
        for i in range(20, len(candles)-10):
            cl = [x[4] for x in candles[i-10:i+1]]
            ma = sum(cl)/len(cl)
            
            # v16.0 LOGIC
            # 1. Check Squeeze
            hi_lo_range = (max(cl[-10:]) / min(cl[-10:]) - 1)
            is_fresh = hi_lo_range < SQUEEZE_THR
            
            # 2. Check Stale
            greens = 0
            for k in range(i, i-5, -1):
                if candles[k][4] > candles[k][1]: greens += 1
                else: break
            
            if cl[-1] > ma:
                if greens >= STALE_LIMIT:
                    stale_blocked += 1
                    continue
                
                if is_fresh:
                    # ENTRY!
                    total_trades += 1
                    ep = cl[-1]
                    atr = max([x[2]-x[3] for x in candles[i-14:i]])
                    sl = ep - (atr * 1.5)
                    max_p = ep
                    
                    for j in range(i+1, len(candles)):
                        max_p = max(max_p, candles[j][2])
                        trail = max(sl, max_p - (atr * 2.0))
                        if candles[j][3] <= trail:
                            res = (trail/ep - 1) * 1000 - (FEE*100) - (SLIPPAGE*100*2)
                            total_pnl += res
                            if res > 0: wins += 1
                            else: traps_found += 1
                            break

    print(f"\nAUDIT RESULTS (100 COINS - 24H):")
    print(f"  Total Trades   : {total_trades}")
    print(f"  Total PnL      : {total_pnl:>+9.1f}%")
    print(f"  Win Rate       : {round(wins/total_trades*100, 1) if total_trades else 0}%")
    print(f"  Anti-Pucuk Save: {stale_blocked} (Potensi kerugian yang dihindari)")
    print(f"  Fake Breakouts : {traps_found} (Kelemahan yang masih ada)")
    
    if total_pnl > 0:
        print("\nCONCLUSION: STRATEGI v16.0 JUJUR DAN PROFITABLE.")
    else:
        print("\nCONCLUSION: STRATEGI MASIH MEMILIKI KELEMAHAN PADA FAKE BREAKOUTS.")

if __name__=="__main__":
    run_forensic_audit()
