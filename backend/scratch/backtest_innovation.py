# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 4: INNOVATION & ADVANCED FILTERS
Tujuan: Menemukan jam trading terbaik dan pengaruh korelasi BTC.
"""
import sys, os, time, requests, statistics
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012

# Expanded list for data diversity
COINS = ["NEARUSDT", "INJUSDT", "BNBUSDT", "ATOMUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT"]

def get_candles(symbol, gran="15m", limit=400):
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles",
            params={"symbol":symbol,"granularity":gran,"limit":limit,"productType":"USDT-FUTURES"}, timeout=8)
        if r.status_code != 200:
            print(f"  [DEBUG] API Error {symbol}: {r.status_code} {r.text}")
            return []
        d = r.json().get("data")
        return [[float(c[i]) for i in range(6)] + [c[0]] for c in d if len(c)>=6] if d else []
    except Exception as e:
        print(f"  [DEBUG] Request Exception {symbol}: {e}")
        return []

# ─── Indicators ───────────────────────────────────────────
def calc_rsi(closes,p=14):
    if len(closes)<p+1: return 50.0
    g,l=[],[]
    for i in range(1,len(closes)):
        d=closes[i]-closes[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g[:p])/p; al=sum(l[:p])/p
    for i in range(p,len(g)):
        ag=(ag*(p-1)+g[i])/p; al=(al*(p-1)+l[i])/p
    return round(100-(100/(1+(ag/(al or 1e-6)))),2)

def vwap_val(candles):
    pv=vol=0
    for c in candles[-30:]:
        t=(c[2]+c[3]+c[4])/3; pv+=t*c[5]; vol+=c[5]
    return pv/vol if vol else candles[-1][4]

# ─── MAIN INNOVATION TEST ────────────────────────────────
def run_innovation_test():
    print("="*70)
    print("BACKTEST ROUND 4: INNOVATION (Time Analysis & BTC Guard)")
    print("="*70)

    # 1. Fetch BTC data for correlation guard
    btc_candles = get_candles("BTCUSDT", "15m", 200)
    btc_data = {}
    if not btc_candles:
        print("[ERROR] Failed to fetch BTC data")
        return
        
    for c in btc_candles:
        ts = str(c[6])
        btc_data[ts] = {"close": c[4], "vwap": 0}
    
    # Pre-calc BTC VWAP (use 30 period for 200 candle limit)
    for i in range(30, len(btc_candles)):
        window = btc_candles[i-30:i+1]
        pv=vol=0
        for cw in window:
            t=(cw[2]+cw[3]+cw[4])/3; pv+=t*cw[5]; vol+=cw[5]
        btc_data[str(btc_candles[i][6])]["vwap"] = pv/vol if vol else btc_candles[i][4]

    hour_performance = {h: {"win":0, "loss":0, "pnl":[]} for h in range(24)}
    btc_guard_results = {"with_guard": {"win":0, "loss":0, "pnl":[]}, "no_guard": {"win":0, "loss":0, "pnl":[]}}

    print(f"[DEBUG] BTC Data loaded: {len(btc_data)} points")

    for sym in COINS:
        candles = get_candles(sym, "15m", 200)
        if not candles: continue
        time.sleep(0.2)
        
        found_ts = 0
        for i in range(30, len(candles)-48):
            ts = str(candles[i][6])
            if ts not in btc_data or btc_data[ts]["vwap"] == 0:
                continue
            found_ts += 1
            
            w = candles[max(0,i-50):i+1]
            cl = [c[4] for c in w]
            rsi = calc_rsi(cl)
            vw = vwap_val(w)
            vd = (cl[-1]-vw)/vw*100
            
            # Relaxed Criteria for "Potential Trades" Analysis
            if 45 <= rsi <= 70 and vd > 0:
                ep = cl[-1]
                tp, sl = ep*1.08, ep*0.95
                outcome = "TIMEOUT"; pnl = 0
                for j in range(i+1, min(i+48, len(candles))):
                    if candles[j][3] <= sl: outcome="LOSS"; pnl=-5.12; break
                    if candles[j][2] >= tp: outcome="WIN"; pnl=7.88; break
                
                if outcome == "TIMEOUT":
                    pnl = (candles[i+47][4]/ep-1)*100 - 0.12
                    outcome = "WIN" if pnl > 0 else "LOSS"

                dt_obj = datetime.fromtimestamp(int(ts)/1000)
                hour = dt_obj.hour
                hour_performance[hour][outcome.lower()] += 1
                hour_performance[hour]["pnl"].append(pnl)

                btc_price = btc_data[ts]["close"]
                btc_vwap  = btc_data[ts]["vwap"]
                btc_healthy = btc_price > btc_vwap
                
                key = "with_guard" if btc_healthy else "no_guard"
                btc_guard_results[key][outcome.lower()] += 1
                btc_guard_results[key]["pnl"].append(pnl)
        
        print(f"  Processed {sym}: {found_ts} aligned timestamps")

    # ─── RESULTS 1: TIME OF DAY ─────────────────────────────
    print("\n[1/2] TIME-OF-DAY PERFORMANCE (UTC)")
    print(f"  {'Hour':<6} {'Trades':<8} {'WR%':<8} {'Total PnL%'}")
    print(f"  {'-'*35}")
    for h in range(24):
        res = hour_performance[h]
        t = res['win'] + res['loss']
        wr = round(res['win']/t*100, 1) if t else 0
        tot = round(sum(res['pnl']), 1)
        if t > 0:
            star = " <--- BEST" if wr > 75 else ""
            print(f"  {h:02d}:00   {t:<8} {wr}%{'':<5} {tot}% {star}")

    # ─── RESULTS 2: BTC GUARD ────────────────────────────────
    print("\n[2/2] BTC CORRELATION GUARD IMPACT")
    for key, res in btc_guard_results.items():
        t = res['win'] + res['loss']
        wr = round(res['win']/t*100, 1) if t else 0
        tot = round(sum(res['pnl']), 1)
        avg = round(tot/t, 2) if t else 0
        print(f"  {key.upper():<12}: {t} trades | WR: {wr}% | Avg PnL: {avg}% | Total: {tot}%")

    print("\n" + "="*70)
    print("INNOVATION ANALYSIS COMPLETE")
    print("="*70)

if __name__=="__main__":
    run_innovation_test()
