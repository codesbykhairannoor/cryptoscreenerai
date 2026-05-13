# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 5: EXTREME STRESS TEST & INDICATOR SYNERGY
Tujuan: Mencapai Win Rate semaksimal mungkin (Target 100%) dengan data 500+ candles.
"""
import sys, os, time, requests
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012
COINS = ["NEARUSDT", "INJUSDT", "BNBUSDT", "ATOMUSDT", "SOLUSDT"]

def get_candles_deep(symbol, gran="15m", total=500):
    """Fetch sequential candles to bypass the 200 limit"""
    all_candles = []
    end_time = None
    for _ in range((total // 200) + 1):
        params = {"symbol":symbol,"granularity":gran,"limit":200,"productType":"USDT-FUTURES"}
        if end_time: params["endTime"] = end_time
        try:
            r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
            data = r.get("data", [])
            if not data: break
            all_candles.extend(data)
            end_time = data[-1][0] # Earliest timestamp in result
            time.sleep(0.2)
        except: break
    
    # Sort by time ascending
    sorted_data = sorted(all_candles, key=lambda x: int(x[0]))
    return [[float(c[i]) for i in range(6)] for c in sorted_data]

# ─── SYNERGY SCORER v9.6 ────────────────────────────────
def score_synergy(rsi, vd, obi, mss, fr):
    s = 0
    # Core Momentum (Must be strong)
    if 55 <= rsi <= 68: s += 35
    # VWAP Support (Institutional price)
    if 0.5 <= vd <= 2.5: s += 30
    # Order Book Dominance (Whale support)
    if obi > 0.2: s += 25
    # Structure (Break of Market Structure)
    if mss: s += 15
    # Funding (Squeeze potential)
    if fr < -0.0001: s += 10
    return s

def simulate_stress(candles, idx, tp_pct, sl_pct):
    ep = candles[idx][4]
    tp, sl = ep*(1+tp_pct), ep*(1-sl_pct)
    # Scan next 96 candles (24 hours)
    for j in range(idx+1, min(idx+96, len(candles))):
        h, l = candles[j][2], candles[j][3]
        if l <= sl: return "LOSS", round((sl/ep-1)*100-FEE*100, 2)
        if h >= tp: return "WIN", round((tp/ep-1)*100-FEE*100, 2)
    p = (candles[-1][4]/ep-1)*100
    return ("WIN" if p>0 else "LOSS"), round(p-FEE*100,2)

def run_stress_test():
    print("="*70)
    print("BACKTEST ROUND 5: EXTREME STRESS TEST & SYNERGY OPTIMIZATION")
    print("="*70)

    configs = [
        {"name": "V9.5 (Elite)", "tp": 0.09, "sl": 0.05, "min_score": 45},
        {"name": "V9.6 (Aggressive TP)", "tp": 0.12, "sl": 0.05, "min_score": 50},
        {"name": "V9.6 (Safe Sniper)", "tp": 0.07, "sl": 0.04, "min_score": 55},
    ]

    for cfg in configs:
        print(f"\nTESTING CONFIG: {cfg['name']} (TP:{cfg['tp']*100}% SL:{cfg['sl']*100}% Score:{cfg['min_score']})")
        total_wins = total_losses = 0
        total_pnl = 0.0
        
        for sym in COINS:
            candles = get_candles_deep(sym, total=500)
            if not candles: continue
            
            cwins = closses = cpnl = 0
            for i in range(50, len(candles)-1):
                window = candles[i-50:i+1]
                closes = [c[4] for c in window]
                
                # Simple RSI calculation for backtest
                p=14; g,l=[],[]
                for k in range(1,len(closes)):
                    d=closes[k]-closes[k-1]; g.append(max(d,0)); l.append(max(-d,0))
                ag=sum(g[:p])/p; al=sum(l[:p])/p
                for k in range(p,len(g)):
                    ag=(ag*(p-1)+g[k])/p; al=(al*(p-1)+l[k])/p
                rsi = 100-(100/(1+(ag/(al or 1e-6))))
                
                # VWAP Dist
                pv=vol=0
                for cw in window[-30:]:
                    t=(cw[2]+cw[3]+cw[4])/3; pv+=t*cw[5]; vol+=cw[5]
                vd = (closes[-1]-(pv/vol))/(pv/vol)*100 if vol else 0
                
                # MSS
                mss = closes[-1] > max(closes[-20:-1])
                
                # Use randomized OBI for historical simulation (since historical OBI is hard to fetch)
                # But we use the current OBI as a proxy for the coin's character
                obi = 0.15 # Baseline
                
                score = score_synergy(rsi, vd, obi, mss, 0)
                if score >= cfg['min_score']:
                    out, pnl = simulate_stress(candles, i, cfg['tp'], cfg['sl'])
                    if out == "WIN": cwins += 1
                    else: closses += 1
                    cpnl += pnl
            
            t = cwins + closses
            wr = round(cwins/t*100, 1) if t else 0
            print(f"  {sym:<10} | Trades: {t:<3} | WR: {wr:>5}% | PnL: {cpnl:>+6.1f}%")
            total_wins += cwins; total_losses += closses; total_pnl += cpnl

        final_t = total_wins + total_losses
        final_wr = round(total_wins/final_t*100, 1) if final_t else 0
        print(f"  {'OVERALL':<10} | Trades: {final_t:<3} | WR: {final_wr:>5}% | Total: {total_pnl:>+6.1f}%")

if __name__=="__main__":
    run_stress_test()
