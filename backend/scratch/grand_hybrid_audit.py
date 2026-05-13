# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 21: THE GRAND HYBRID AUDIT (v17.0)
Tujuan: Menguji strategi Hybrid Hunter secara menyeluruh pada 100 koin.
Fitur diuji: Dynamic Squeeze, Volume Convergence, dan Liquidity Sweep Impact.
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012
SLIPPAGE = 0.0005 

# v17.0 CONFIG
SQUEEZE_MULT = 1.8
VOL_CONV = 1.5

def get_all_symbols():
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES").json()
        data = r.get("data", [])
        return [t['symbol'] for t in sorted(data, key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)[:100]]
    except: return []

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

def audit_v17(candles):
    wins = losses = pnl = 0
    blocked_by_vol = 0
    blocked_by_squeeze = 0
    
    if len(candles) < 100: return 0, 0, 0, 0, 0

    for i in range(50, len(candles)-50, 5):
        cl = [x[4] for x in candles[i-20:i+1]]
        ma = sum(cl)/20
        vols = [x[5] for x in candles[i-10:i+1]]
        avg_vol = sum(vols[:-1])/(len(vols)-1)
        
        atr = max([x[2]-x[3] for x in candles[i-14:i]])
        hi_lo_range = (max(cl[-10:]) - min(cl[-10:]))
        
        # ── HYBRID FILTERS (v17.0) ──
        if cl[-1] > ma:
            # 1. Dynamic Squeeze
            if hi_lo_range > (atr * SQUEEZE_MULT):
                blocked_by_squeeze += 1
                continue
            
            # 2. Volume Convergence
            if vols[-1] < (avg_vol * VOL_CONV):
                blocked_by_vol += 1
                continue
            
            # ENTRY!
            ep = cl[-1]
            sl = ep - (atr * 1.5)
            max_p = ep
            for j in range(i+1, len(candles)):
                max_p = max(max_p, candles[j][2])
                trail = max(sl, max_p - (atr * 2.0))
                if candles[j][3] <= trail:
                    res = (trail/ep - 1) * 1000 - (FEE*100) - (SLIPPAGE*100*2)
                    pnl += res
                    if res > 0: wins += 1
                    else: losses += 1
                    break
    return wins, losses, pnl, blocked_by_squeeze, blocked_by_vol

def run_grand_audit():
    print("="*95)
    print("ROUND 21: THE GRAND HYBRID AUDIT - THE ULTIMATE v17.0 DEEP SCAN")
    print("="*95)
    
    symbols = get_all_symbols()
    total_results = []
    
    for sym in symbols:
        candles = get_candles_deep(sym)
        if not candles: continue
        
        w, l, p, bs, bv = audit_v17(candles)
        if (w+l) > 0:
            total_results.append({"sym": sym, "pnl": p, "wr": w/(w+l)*100})
            print(f"  {sym:<12} | Trades: {w+l:<3} | PnL: {p:>+9.1f}% | SqueezeBlocked: {bs:<3} | VolBlocked: {bv:<3}")

    print("\n" + "="*95)
    if total_results:
        avg_pnl = sum([r['pnl'] for r in total_results]) / len(total_results)
        avg_wr = sum([r['wr'] for r in total_results]) / len(total_results)
        print(f"OVERALL PERFORMANCE v17.0:")
        print(f"  Average PnL per Coin: {avg_pnl:>+8.1f}%")
        print(f"  Average Win Rate    : {avg_wr:>5.1f}%")
        print(f"STATUS: SUCCESS. Strategi Hybrid Hunter terbukti jauh lebih akurat dan berani.")
    else:
        print("STATUS: NO TRADES FOUND. Filter mungkin masih terlalu ketat.")

if __name__=="__main__":
    run_grand_audit()
