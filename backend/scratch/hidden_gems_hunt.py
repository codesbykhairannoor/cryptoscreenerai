# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 13: THE HIDDEN GEMS HUNT
Pencarian massal koin 'Bintang' di antara 100+ koin Bitget.
Teknik: Deep Fetching (1000 candle per koin) + Slippage Penalty.
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012
SLIPPAGE = 0.0005

def get_all_symbols():
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES").json()
        data = r.get("data", [])
        # Sort by volume and take top 120
        sorted_data = sorted(data, key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)
        return [t['symbol'] for t in sorted_data[:120]]
    except: return []

def get_candles_deep(symbol, total=1000):
    all_candles = []
    end_time = None
    for _ in range(5): # 5 x 200 = 1000
        params = {"symbol":symbol,"granularity":"15m","limit":200,"productType":"USDT-FUTURES"}
        if end_time: params["endTime"] = end_time
        try:
            r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
            data = r.get("data", [])
            if not data: break
            all_candles.extend(data)
            end_time = data[-1][0]
            time.sleep(0.1) # Respect rate limits
        except: break
    return sorted([[float(c[i]) for i in range(6)] for c in all_candles], key=lambda x: x[0])

def audit_v10(candles):
    wins = losses = pnl = 0
    if len(candles) < 100: return 0, 0, 0
    for i in range(50, len(candles)-50, 5):
        c = [x[4] for x in candles[i-20:i+1]]
        ma = sum(c)/len(c)
        if c[-1] > ma and c[-1] > c[-2]:
            ep = c[-1]
            peak = 0
            sl_pnl = -50.0
            for j in range(i+1, min(i+100, len(candles))):
                h, l = candles[j][2], candles[j][3]
                p_high = (h/ep - 1) * 1000
                p_low = (l/ep - 1) * 1000
                peak = max(peak, p_high)
                if peak >= 20: sl_pnl = max(sl_pnl, (int(peak/20)*20) - 10)
                if p_low <= sl_pnl:
                    res = sl_pnl - (FEE*100) - (SLIPPAGE*100*2)
                    if res > 0: wins += 1
                    else: losses += 1
                    pnl += res
                    break
            else:
                res = (candles[-1][4]/ep - 1)*1000 - (FEE*100) - (SLIPPAGE*100*2)
                if res > 0: wins += 1
                else: losses += 1
                pnl += res
    return wins, losses, pnl

def run_hunt():
    print("="*95)
    print("ROUND 13: THE HIDDEN GEMS HUNT - DEEP SCAN 100+ SYMBOLS")
    print("="*95)
    
    symbols = get_all_symbols()
    results = []
    
    for sym in symbols:
        candles = get_candles_deep(sym)
        if not candles: continue
        
        w, l, p = audit_v10(candles)
        t = w + l
        if t < 5: continue
        
        wr = round(w/t*100, 1)
        results.append({"sym": sym, "wr": wr, "pnl": p, "trades": t})
        # print(f"  {sym:<15} | Trades: {t:<4} | WR: {wr:>5}% | PnL: {p:>+9.1f}%")

    print("\n" + "="*95)
    print("NEWLY DISCOVERED ELITE COINS (Win Rate > 85%):")
    elite = sorted([r for r in results if r['wr'] >= 85 and r['pnl'] > 50], key=lambda x: x['pnl'], reverse=True)
    for r in elite:
        print(f"  {r['sym']:<15} | WR: {r['wr']:>5}% | PnL: {r['pnl']:>+9.1f}% | Trades: {r['trades']}")

    print("\nRELIABLE PERFORMERS (Win Rate 75-85%):")
    reliable = sorted([r for r in results if 75 <= r['wr'] < 85 and r['pnl'] > 20], key=lambda x: x['pnl'], reverse=True)
    for r in reliable[:10]:
        print(f"  {r['sym']:<15} | WR: {r['wr']:>5}% | PnL: {r['pnl']:>+9.1f}% | Trades: {r['trades']}")

if __name__=="__main__":
    run_hunt()
