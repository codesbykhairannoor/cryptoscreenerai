# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 31: THE TRAILING DAILY AUDIT (v25.0)
Fitur: Full Parabolic Trailing SL, Daily Profit Breakdown.
Tujuan: Memberikan gambaran 'Gaji Harian' dan dampak Trailing SL.
"""
import sys, os, time, requests
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
RISK_USD = 0.50
ATR_SL_MULT = 1.8
ATR_TP_MULT = 4.0
TRAIL_GAP = 2.0 # Gap ATR untuk trailing

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

def audit_v25_daily_trailing(candles):
    daily_stats = {} # {date_str: pnl}
    exit_idx = 0
    
    for i in range(50, len(candles)-20):
        if i < exit_idx: continue
        
        o, h, l, c, v = candles[i][1], candles[i][2], candles[i][3], candles[i][4], candles[i][5]
        prev_o, prev_c = candles[i-1][1], candles[i-1][4]
        cl_50 = [x[4] for x in candles[i-50:i+1]]
        ema50 = sum(cl_50)/len(cl_50)
        
        # v25.0 TRIGGER
        if c > ema50 and c > o and prev_c > prev_o:
            ep = c
            date_str = datetime.fromtimestamp(candles[i][0]/1000).strftime('%Y-%m-%d')
            atr = max([x[2]-x[3] for x in candles[i-14:i]])
            tp = ep + (atr * ATR_TP_MULT)
            initial_sl = ep - (atr * ATR_SL_MULT)
            max_p = ep
            
            for j in range(i+1, len(candles)):
                max_p = max(max_p, candles[j][2])
                # LOGIKA TRAILING SL (Kunci Profit)
                current_sl = max(initial_sl, max_p - (atr * TRAIL_GAP))
                
                if candles[j][2] >= tp: # HIT TP
                    res = (tp/ep - 1) * 10 * RISK_USD
                    daily_stats[date_str] = daily_stats.get(date_str, 0) + res
                    exit_idx = j; break
                if candles[j][3] <= current_sl: # HIT TRAILING/INITIAL SL
                    res = (current_sl/ep - 1) * 10 * RISK_USD
                    daily_stats[date_str] = daily_stats.get(date_str, 0) + res
                    exit_idx = j; break
    return daily_stats

def run_trailing_audit():
    print("="*95)
    print("ROUND 31: THE TRAILING DAILY AUDIT - v25.0 FULL SIMULATION")
    print("="*95)
    
    r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES").json()
    symbols = [t['symbol'] for t in sorted(r['data'], key=lambda x: float(x.get('quoteVolume',0)), reverse=True)[:40]]
    
    overall_daily = {}
    
    for sym in symbols:
        candles = get_candles_deep(sym)
        if not candles: continue
        stats = audit_v25_daily_trailing(candles)
        for d, p in stats.items():
            overall_daily[d] = overall_daily.get(d, 0) + p

    print("\nDAILY PROFIT BREAKDOWN (Estimasi Gaji Harian):")
    total_p = 0
    for d in sorted(overall_daily.keys()):
        p = overall_daily[d]
        total_p += p
        print(f"  {d} | Profit: ${p:>+6.2f} | Status: {'WINNING' if p>0 else 'DRAW/LOSS'}")

    print("\n" + "="*95)
    print(f"SUMMARY v25.0 WITH TRAILING SL:")
    print(f"  Total Profit (7 Hari) : ${total_p:>+6.2f}")
    print(f"  Avg Profit per Hari   : ${total_p/len(overall_daily):>+6.2f}")
    print(f"  ROI Mingguan (%)      : {round(total_p/12*100, 1)}%")
    print(f"  Final Saldo (Estimasi): ${12 + total_p:.2f}")

if __name__=="__main__":
    run_trailing_audit()
