# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 27: THE FINAL BALANCE AUDIT (v23.0)
Tujuan: Mengukur performa v23.0 (Body-to-Wick) dengan simulasi saldo 12 USDT.
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012
SLIPPAGE = 0.0005
SALDO_AWAL = 12.0
RISK_PER_TRADE = 0.50

# CONFIG v23.0
BODY_DOM = 0.60
VOL_MOM = 1.8

def get_candles(symbol, limit=400):
    params = {"symbol":symbol,"granularity":"15m","limit":limit,"productType":"USDT-FUTURES"}
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
        return sorted([[float(c[i]) for i in range(6)] for c in r.get("data", [])], key=lambda x: x[0])
    except: return []

def audit_v23(candles):
    w = l = pnl = 0
    for i in range(50, len(candles)-10):
        o, h, l, c, v = candles[i][1], candles[i][2], candles[i][3], candles[i][4], candles[i][5]
        cl = [x[4] for x in candles[i-10:i+1]]
        ma = sum(cl)/len(cl)
        vols = [x[5] for x in candles[i-10:i+1]]
        avg_v = sum(vols[:-1])/(len(vols)-1) if len(vols)>1 else 1
        
        if c > ma:
            total_r = h - l
            body_s = abs(c - o) / total_r if total_r > 0 else 0
            is_strong_v = v > (avg_v * VOL_MOM)
            
            entry = False
            if body_s > BODY_DOM and is_strong_v:
                entry = True
            else:
                lower_w = (min(o, c) - l) / total_r if total_r > 0 else 0
                if lower_w >= 0.20:
                    entry = True
            
            if entry:
                ep = c
                atr = max([x[2]-x[3] for x in candles[i-14:i]])
                sl = ep - (atr * 2.0)
                max_p = ep
                for j in range(i+1, len(candles)):
                    max_p = max(max_p, candles[j][2])
                    trail = max(sl, max_p - (atr * 2.5))
                    if candles[j][3] <= trail:
                        res = (trail/ep - 1) * 10 * RISK_PER_TRADE # Simplified Dollar Profit
                        pnl += res
                        if res > 0: w += 1
                        else: l += 1
                        break
    return w, l, pnl

def run_final_audit():
    print("="*95)
    print("ROUND 27: THE FINAL BALANCE AUDIT - v23.0 REALITY CHECK")
    print("="*95)
    
    r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES").json()
    symbols = [t['symbol'] for t in sorted(r['data'], key=lambda x: float(x.get('quoteVolume',0)), reverse=True)[:50]]
    
    total_w = total_l = total_p = 0
    
    for sym in symbols:
        candles = get_candles(sym)
        if not candles: continue
        
        w, l, p = audit_v23(candles)
        total_w += w; total_l += l; total_p += p
        
    print(f"\nFINAL PERFORMANCE v23.0 (LAST 24H):")
    total_t = total_w + total_l
    wr = round(total_w/total_t*100, 1) if total_t else 0
    print(f"  Total Trades   : {total_t}")
    print(f"  Win Rate       : {wr}%")
    print(f"  Profit (USD)   : ${total_p:>+6.2f}")
    print(f"  Final Saldo GW : ${SALDO_AWAL + total_p:.2f}")

if __name__=="__main__":
    run_final_audit()
