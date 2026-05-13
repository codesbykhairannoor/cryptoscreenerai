# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 16: THE SURVIVAL STRATEGY (Saldo 12 USDT)
Target: SL 1.4% (14% PnL), TP 3.0% (30% PnL).
Hanya pada koin-koin paling nurut (ELITE ONLY).
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012
SL_LIMIT = 0.014 # 1.4% Price (14% PnL)
TP_LIMIT = 0.030 # 3.0% Price (30% PnL)

COINS = ["INJUSDT", "NEARUSDT", "DOTUSDT", "TIAUSDT", "LINKUSDT"]

def get_candles(symbol, limit=400):
    params = {"symbol":symbol,"granularity":"15m","limit":limit,"productType":"USDT-FUTURES"}
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
        return sorted([[float(c[i]) for i in range(6)] for c in r.get("data", [])], key=lambda x: x[0])
    except: return []

def run_survival_audit():
    print("="*95)
    print(f"ROUND 16: SURVIVAL AUDIT (SL: {SL_LIMIT*100}% | TP: {TP_LIMIT*100}%)")
    print("="*95)
    
    total_wins = 0
    total_losses = 0
    
    for sym in COINS:
        candles = get_candles(sym)
        if not candles: continue
        
        wins = losses = 0
        for i in range(30, len(candles)-50, 5):
            # Momentum + 5m Alignment Proxy
            cl = [x[4] for x in candles[i-20:i+1]]
            if cl[-1] > sum(cl)/20 and cl[-1] > cl[-2]:
                ep = cl[-1]
                # Simulate Trade with tight SL
                for j in range(i+1, min(i+50, len(candles))):
                    h, l = candles[j][2], candles[j][3]
                    if l <= ep * (1 - SL_LIMIT):
                        losses += 1
                        break
                    if h >= ep * (1 + TP_LIMIT):
                        wins += 1
                        break
                
        wr = round(wins/(wins+losses)*100, 1) if (wins+losses) else 0
        print(f"  {sym:<12} | Wins: {wins:<3} | Losses: {losses:<3} | WinRate: {wr:>5}%")
        total_wins += wins
        total_losses += losses

    final_wr = round(total_wins/(total_wins+total_losses)*100, 1) if (total_wins+total_losses) else 0
    print("\n" + "="*95)
    print(f"OVERALL SURVIVAL WIN RATE: {final_wr}%")
    if final_wr > 70:
        print("STATUS: AMAN. Strategi SL Ketat ini bisa menyelamatkan saldo Anda.")
    else:
        print("STATUS: BERBAHAYA. SL 1.4% terlalu sering terkena noise market.")

if __name__=="__main__":
    run_survival_audit()
