# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 28: THE HYPER-ACTIVE AUDIT (v24.0)
Strategi: Aggressive Momentum Scalper.
Tujuan: Menjamin adanya trade harian (High Frequency) dengan risiko terukur.
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012
RISK_PER_TRADE = 0.50

def get_candles(symbol, limit=200):
    params = {"symbol":symbol,"granularity":"5m","limit":limit,"productType":"USDT-FUTURES"}
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
        return sorted([[float(c[i]) for i in range(6)] for c in r.get("data", [])], key=lambda x: x[0])
    except: return []

def audit_v24(candles):
    w = l = pnl = 0
    for i in range(30, len(candles)-10):
        o, h, l, c, v = candles[i][1], candles[i][2], candles[i][3], candles[i][4], candles[i][5]
        cl = [x[4] for x in candles[i-20:i+1]]
        ma20 = sum(cl)/20
        vols = [x[5] for x in candles[i-10:i+1]]
        avg_v = sum(vols[:-1])/(len(vols)-1)
        
        # ── HYPER-ACTIVE LOGIC (v24.0) ──
        # Syarat minimal: Harga di atas MA + Candle Hijau + Volume > Rata-rata
        if c > ma20 and c > o and v > avg_v:
            # ENTRY (No more waiting!)
            ep = c
            sl = ep * 0.985 # Fixed 1.5% SL for action
            tp = ep * 1.03  # 3% TP Target
            
            for j in range(i+1, len(candles)):
                if candles[j][2] >= tp: # Hit TP
                    res = (tp/ep - 1) * 10 * RISK_PER_TRADE
                    pnl += res; w += 1; break
                if candles[j][3] <= sl: # Hit SL
                    res = (sl/ep - 1) * 10 * RISK_PER_TRADE
                    pnl += res; l += 1; break
    return w, l, pnl

def run_hyper_active_audit():
    print("="*95)
    print("ROUND 28: THE HYPER-ACTIVE AUDIT - v24.0 ACTION MODE")
    print("="*95)
    
    r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES").json()
    symbols = [t['symbol'] for t in sorted(r['data'], key=lambda x: float(x.get('quoteVolume',0)), reverse=True)[:100]]
    
    total_w = total_l = total_p = 0
    
    for sym in symbols:
        candles = get_candles(sym)
        if not candles: continue
        w, l, p = audit_v24(candles)
        total_w += w; total_l += l; total_p += p
        if (w+l) > 0:
            print(f"  {sym:<12} | Trades: {w+l:<3} | PnL: ${p:>+6.2f}")

    print("\n" + "="*95)
    total_t = total_w + total_l
    print(f"HYPER-ACTIVE RESULTS (LAST 16 HOURS):")
    print(f"  Total Trades   : {total_t}")
    print(f"  Win Rate       : {round(total_w/total_t*100, 1) if total_t else 0}%")
    print(f"  Total Profit   : ${total_p:>+6.2f}")
    print(f"  Status         : AGGRESSIVE ACTION ACTIVE")

if __name__=="__main__":
    run_hyper_active_audit()
