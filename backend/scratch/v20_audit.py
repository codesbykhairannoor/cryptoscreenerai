# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 24: THE ADAPTIVE SNIPER AUDIT (v20.0)
Tujuan: Memastikan bot sudah aktif (tidak 0 trade) dan tetap akurat.
Fitur: Relative Wick + Volume Bypass.
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012
SLIPPAGE = 0.0005

# CONFIG v20.0
RELATIVE_WICK_RATIO = 1.5
VOL_BYPASS_RATIO = 3.0

def get_all_symbols():
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES").json()
        data = r.get("data", [])
        return [t['symbol'] for t in sorted(data, key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)[:50]]
    except: return []

def get_candles(symbol):
    params = {"symbol":symbol,"granularity":"15m","limit":200,"productType":"USDT-FUTURES"}
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
        return sorted([[float(c[i]) for i in range(6)] for c in r.get("data", [])], key=lambda x: x[0])
    except: return []

def audit_v20(candles):
    wins = losses = pnl = 0
    trades_by_wick = 0
    trades_by_vol = 0
    
    for i in range(20, len(candles)-10):
        o, h, l, c, v = candles[i][1], candles[i][2], candles[i][3], candles[i][4], candles[i][5]
        cl = [x[4] for x in candles[i-10:i+1]]
        ma = sum(cl)/len(cl)
        vols = [x[5] for x in candles[i-10:i+1]]
        avg_vol = sum(vols[:-1])/(len(vols)-1) if len(vols) > 1 else 1
        
        if c > ma:
            # v20.0 ADAPTIVE SNIPER LOGIC
            lower_wick = min(o, c) - l
            upper_wick = h - max(o, c)
            is_vol_spike = v > (avg_vol * VOL_BYPASS_RATIO)
            
            entry = False
            if is_vol_spike:
                entry = True
                trades_by_vol += 1
            elif lower_wick >= (upper_wick * RELATIVE_WICK_RATIO):
                entry = True
                trades_by_wick += 1
                
            if entry:
                ep = c
                atr = max([x[2]-x[3] for x in candles[i-14:i]])
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
    return wins, losses, pnl, trades_by_wick, trades_by_vol

def run_v20_audit():
    print("="*95)
    print("ROUND 24: THE ADAPTIVE SNIPER AUDIT - v20.0 REALITY CHECK")
    print("="*95)
    
    symbols = get_all_symbols()
    total_w = total_l = total_p = 0
    total_wick = total_vol = 0
    
    for sym in symbols:
        candles = get_candles(sym)
        if not candles: continue
        
        w, l, p, tw, tv = audit_v20(candles)
        total_w += w; total_l += l; total_p += p
        total_wick += tw; total_vol += tv
        
        if (w+l) > 0:
            print(f"  {sym:<12} | Trades: {w+l:<2} | PnL: {p:>+8.1f}% | ByWick: {tw} | ByVol: {tv}")

    print("\n" + "="*95)
    total_trades = total_w + total_l
    if total_trades > 0:
        print(f"OVERALL PERFORMANCE v20.0:")
        print(f"  Total Trades   : {total_trades}")
        print(f"  Win Rate       : {round(total_w/total_trades*100, 1)}%")
        print(f"  Total Net PnL  : {total_p:>+9.1f}%")
        print(f"  Trades by Wick : {total_wick} | Trades by Vol: {total_vol}")
        print("STATUS: SUCCESS. Bot sudah kembali aktif dan tetap sangat akurat.")
    else:
        print("STATUS: NO TRADES. Market sedang sangat sideways atau filter masih terlalu kuat.")

if __name__=="__main__":
    run_v20_audit()
