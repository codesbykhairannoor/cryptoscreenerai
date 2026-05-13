# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 29: THE AGGRESSIVE REALITY AUDIT (v24.0)
Tujuan: Menguji strategi Predator pada 1000 candle (Deep Scan).
Mencari titik lemah strategi agresif (Whipsaw/Loss beruntun).
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012
SLIPPAGE = 0.0005
RISK_USD = 0.50 # Tiap kekalahan rugi $0.50

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

def audit_v24_aggressive(candles):
    w = l = pnl = 0
    in_trade = False
    exit_idx = 0
    
    for i in range(30, len(candles)-10):
        if i < exit_idx: continue # Skip jika masih dalam trade
        
        o, h, l, c, v = candles[i][1], candles[i][2], candles[i][3], candles[i][4], candles[i][5]
        cl = [x[4] for x in candles[i-20:i+1]]
        ma20 = sum(cl)/20
        vols = [x[5] for x in candles[i-10:i+1]]
        avg_v = sum(vols[:-1])/(len(vols)-1)
        
        # v24.0 LOGIC: Aggressive Momentum
        if c > ma20 and c > o and v > avg_v:
            ep = c
            tp = ep * 1.03
            sl = ep * 0.985
            
            for j in range(i+1, len(candles)):
                if candles[j][2] >= tp:
                    res = (tp/ep - 1) * 10 * RISK_USD # Approx gain
                    pnl += res; w += 1; exit_idx = j; break
                if candles[j][3] <= sl:
                    res = (sl/ep - 1) * 10 * RISK_USD # Approx loss
                    pnl += res; l += 1; exit_idx = j; break
    return w, l, pnl

def run_aggressive_stress_test():
    print("="*95)
    print("ROUND 29: THE AGGRESSIVE REALITY AUDIT - v24.0 STRESS TEST")
    print("="*95)
    
    r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES").json()
    symbols = [t['symbol'] for t in sorted(r['data'], key=lambda x: float(x.get('quoteVolume',0)), reverse=True)[:50]]
    
    total_w = total_l = total_p = 0
    
    for sym in symbols:
        candles = get_candles_deep(sym)
        if not candles: continue
        w, l, p = audit_v24_aggressive(candles)
        total_w += w; total_l += l; total_p += p
        if (w+l) > 0:
            wr = w/(w+l)*100
            print(f"  {sym:<12} | Trades: {w+l:<3} | WinRate: {wr:>5.1f}% | PnL: ${p:>+7.2f}")

    print("\n" + "="*95)
    total_t = total_w + total_l
    if total_t > 0:
        print(f"OVERALL STRESS TEST RESULTS (1000 CANDLES):")
        print(f"  Total Trades   : {total_t}")
        print(f"  Final Win Rate : {round(total_w/total_t*100, 1)}%")
        print(f"  Total Net PnL  : ${total_p:>+8.2f}")
        print(f"  Avg Trades/Coin: {round(total_t/len(symbols), 1)}")
        print("\nANALISIS KELEMAHAN: Strategi agresif sangat rentan pada market sideways.")
    else:
        print("STATUS: NO TRADES FOUND.")

if __name__=="__main__":
    run_aggressive_stress_test()
