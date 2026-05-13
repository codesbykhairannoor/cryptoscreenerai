# -*- coding: utf-8 -*-
import sys, os, time, requests
SLIPPAGE = 0.0010 
FEE = 0.0012
COINS = ["NEARUSDT", "INJUSDT", "TIAUSDT"]

def run():
    print("="*80)
    print("ROUND 11: REALITY CHECK (Limit 200 candles)")
    print("="*80)
    for sym in COINS:
        r = requests.get(f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={sym}&granularity=15m&limit=200&productType=USDT-FUTURES").json()
        data = r.get("data", [])
        if not data: 
            print(f"  {sym}: No data found.")
            continue
        
        candles = sorted([[float(c[i]) for i in range(6)] for c in data], key=lambda x: x[0])
        perfect = reality = trades = 0
        for i in range(20, len(candles)-10):
            trades += 1
            ep = candles[i][4]
            # Simple Outcome
            move = (candles[i+5][4]/ep - 1) * 100
            perfect += move - 0.12
            reality += move - 0.12 - (SLIPPAGE * 100 * 2)
            
        print(f"  {sym:<12} | Trades: {trades:<4} | Perfect: {perfect:>+6.1f}% | Reality: {reality:>+6.1f}%")

if __name__=="__main__":
    run()
