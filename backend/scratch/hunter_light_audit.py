# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 32: THE INSTITUTIONAL HUNTER (v26.0) - LIGHT MODE
Tujuan: Mengatasi Timeout API dengan membatasi jumlah koin.
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
RISK_USD = 0.50

def get_candles_deep(symbol):
    params = {"symbol":symbol,"granularity":"15m","limit":500,"productType":"USDT-FUTURES"}
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=30).json()
        data = r.get("data", [])
        return sorted([[float(c[i]) for i in range(6)] for c in data], key=lambda x: x[0])
    except: return []

def audit_v26_hunter(candles):
    w = l = pnl = 0
    exit_idx = 0
    for i in range(50, len(candles)-20):
        if i < exit_idx: continue
        c0, c1, c2 = candles[i-2], candles[i-1], candles[i]
        if c2[3] > c0[2]: # Bullish FVG
            fvg_low, fvg_high = c0[2], c2[3]
            v_avg = sum([x[5] for x in candles[i-10:i]])/10
            if c1[5] > (v_avg * 1.5):
                entry_limit = (fvg_low + fvg_high) / 2
                for k in range(i+1, min(i+15, len(candles))):
                    if candles[k][3] <= entry_limit: # Terjemput
                        ep = entry_limit
                        atr = max([x[2]-x[3] for x in candles[i-14:i]])
                        tp = ep + (atr * 4.0)
                        sl = ep - (atr * 1.8)
                        for j in range(k+1, len(candles)):
                            if candles[j][2] >= tp:
                                pnl += (tp/ep - 1) * 10 * RISK_USD
                                w += 1; exit_idx = j; break
                            if candles[j][3] <= sl:
                                pnl += (sl/ep - 1) * 10 * RISK_USD
                                l += 1; exit_idx = j; break
                        break
    return w, l, pnl

def run_hunter_audit():
    print("="*95)
    print("ROUND 32: THE INSTITUTIONAL HUNTER (v26.0) - LIGHT SCAN")
    print("="*95)
    
    # Fokus pada 15 koin paling liquid saja untuk menghindari timeout
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT", "ADAUSDT", "LINKUSDT", "NEARUSDT", "FETUSDT"]
    
    total_w = total_l = total_p = 0
    for sym in symbols:
        candles = get_candles_deep(sym)
        if not candles: 
            print(f"  {sym:<12} | Skipping (API Timeout)")
            continue
        w, l, p = audit_v26_hunter(candles)
        total_w += w; total_l += l; total_p += p
        if (w+l) > 0:
            print(f"  {sym:<12} | Trades: {w+l:<3} | WinRate: {round(w/(w+l)*100,1):>5.1f}% | PnL: ${p:>+7.2f}")

    print("\n" + "="*95)
    total_t = total_w + total_l
    if total_t > 0:
        print(f"INSTITUTIONAL HUNTER RESULTS (v26.0):")
        print(f"  Total Trades   : {total_t}")
        print(f"  Final Win Rate : {round(total_w/total_t*100, 1)}%")
        print(f"  Total Net PnL  : ${total_p:>+8.2f}")
    else:
        print("STATUS: API BITGET SEDANG GANGGUAN. COBA LAGI NANTI.")

if __name__=="__main__":
    run_hunter_audit()
