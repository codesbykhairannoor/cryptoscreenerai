# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 8: TRAILING STOP OPTIMIZER
Mencari setting TSL terbaik agar tidak 'kebuang' terlalu dini saat koin sedang rally.
Data: 3000 candles (~30 hari).
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012
COINS = ["NEARUSDT", "INJUSDT", "BNBUSDT", "ATOMUSDT", "SOLUSDT"]

def get_candles_extreme(symbol, total=3000):
    all_candles = []
    end_time = None
    for _ in range((total // 200) + 1):
        params = {"symbol":symbol,"granularity":"15m","limit":200,"productType":"USDT-FUTURES"}
        if end_time: params["endTime"] = end_time
        try:
            r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
            data = r.get("data", [])
            if not data: break
            all_candles.extend(data)
            end_time = data[-1][0]
            time.sleep(0.1)
        except: break
    return sorted([[float(c[i]) for i in range(6)] for c in all_candles], key=lambda x: x[0])

def simulate_with_tsl(candles, start_idx, variant_type):
    ep = candles[start_idx][4]
    peak_pnl = 0
    current_sl_pnl = -50.0 # Initial SL 5% price = 50% PnL (10x leverage)
    
    for j in range(start_idx+1, min(start_idx+200, len(candles))):
        h, l, c = candles[j][2], candles[j][3], candles[j][4]
        # Current PnL at high
        pnl_high = (h/ep - 1) * 1000 # 10x leverage
        pnl_low  = (l/ep - 1) * 1000
        pnl_close = (c/ep - 1) * 1000
        
        peak_pnl = max(peak_pnl, pnl_high)
        
        # LOGIKA TRAILING
        new_sl_pnl = -50.0
        if variant_type == "A (Tight)":
            if peak_pnl >= 10: new_sl_pnl = peak_pnl - 5
        elif variant_type == "B (Relaxed)":
            if peak_pnl >= 30: new_sl_pnl = peak_pnl - 15
        elif variant_type == "C (Adaptive)":
            if peak_pnl >= 15:
                gap = 12 if peak_pnl < 40 else 6
                new_sl_pnl = peak_pnl - gap
        elif variant_type == "D (Step)":
            if peak_pnl >= 20: new_sl_pnl = (int(peak_pnl/20)*20) - 10
            
        current_sl_pnl = max(current_sl_pnl, new_sl_pnl)
        
        # Check SL
        if pnl_low <= current_sl_pnl:
            return current_sl_pnl - 1.2 # Minus fee
            
        # Hard TP at 150% PnL (15% price move)
        if pnl_high >= 150:
            return 150 - 1.2
            
    return pnl_close - 1.2

def run_optimizer():
    print("="*85)
    print("ROUND 8: TRAILING STOP OPTIMIZER - WINNER ANALYSIS")
    print("="*85)
    
    variants = ["A (Tight)", "B (Relaxed)", "C (Adaptive)", "D (Step)"]
    
    for v in variants:
        print(f"\nTESTING VARIANT: {v}")
        total_pnl = 0
        total_trades = 0
        
        for sym in COINS:
            candles = get_candles_extreme(sym)
            if not candles: continue
            
            cpnl = 0
            ctrades = 0
            for i in range(50, len(candles)-200, 10): # Step 10 to speed up
                cl = [c[4] for c in candles[i-20:i+1]]
                # Simple momentum check
                if cl[-1] > cl[-10] and cl[-1] > sum(cl)/len(cl):
                    res_pnl = simulate_with_tsl(candles, i, v)
                    cpnl += res_pnl
                    ctrades += 1
            
            avg_pnl = cpnl/ctrades if ctrades else 0
            print(f"  {sym:<10} | Trades: {ctrades:<4} | Total PnL: {cpnl:>+9.1f}% | Avg: {avg_pnl:>+5.1f}%")
            total_pnl += cpnl
            total_trades += ctrades
            
        print(f"  {'OVERALL':<10} | Trades: {total_trades:<4} | TOTAL PNL: {total_pnl:>+9.1f}%")

if __name__=="__main__":
    run_optimizer()
