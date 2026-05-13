# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 11: THE REALITY CHECK (Slippage Stress Test)
Tujuan: Menguji ketahanan profit terhadap Slippage (0.1%) dan Latency.
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012
SLIPPAGE = 0.0010 # 0.1% Penalti harga (Dunia Nyata)

COINS = ["NEARUSDT", "INJUSDT", "TIAUSDT", "SEIUSDT", "ATOMUSDT"]

def get_candles(symbol, limit=1000):
    params = {"symbol":symbol,"granularity":"15m","limit":limit,"productType":"USDT-FUTURES"}
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
        data = r.get("data", [])
        return sorted([[float(c[i]) for i in range(6)] for c in data], key=lambda x: x[0])
    except:
        return []

def run_reality_check():
    print("="*90)
    print("ROUND 11: THE REALITY CHECK - SLIPPAGE STRESS TEST (Penalti 0.1% per trade)")
    print("="*90)

    for sym in COINS:
        candles = get_candles(sym)
        if not candles: continue
        
        perfect_pnl = 0
        reality_pnl = 0
        trades = 0
        
        for i in range(50, len(candles)-50, 5):
            cl = [c[4] for c in candles[i-20:i+1]]
            if cl[-1] > sum(cl)/len(cl): # Proxy momentum
                trades += 1
                ep = cl[-1]
                
                # Simulasi Exit (Target 5% Move)
                outcome_pnl = 0
                for j in range(i+1, min(i+48, len(candles))):
                    if candles[j][2] >= ep * 1.05:
                        outcome_pnl = 5.0
                        break
                    if candles[j][3] <= ep * 0.95:
                        outcome_pnl = -5.0
                        break
                
                # PERFECT WORLD (No Slippage)
                perfect_pnl += outcome_pnl - (FEE * 100)
                
                # REAL WORLD (With 0.1% Slippage on Entry and 0.1% on Exit)
                # Slippage 0.1% at 10x leverage = 1.0% PnL hit
                reality_pnl += outcome_pnl - (FEE * 100) - (SLIPPAGE * 100 * 2) 

        print(f"  {sym:<12} | Trades: {trades:<4}")
        print(f"    > Perfect PnL: {perfect_pnl:>+8.1f}%")
        print(f"    > Reality PnL: {reality_pnl:>+8.1f}% (Penalti Slippage)")
        
        survival = "SURVIVED" if reality_pnl > 0 else "KILLED"
        print(f"    > STATUS: {survival}")

if __name__=="__main__":
    run_reality_check()
