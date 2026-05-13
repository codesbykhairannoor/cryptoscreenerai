# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 9: THE GLOBAL MARKET SWEEP
Mencari 'Bintang Baru' dan 'Penipu Baru' di antara Top 50 Koin Bitget.
Data: 500 candles per coin (Total 25,000+ data points).
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012

def get_top_50_symbols():
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES").json()
        tickers = r.get("data", [])
        # Sort by 24h volume (quoteVolume)
        sorted_tickers = sorted(tickers, key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)
        return [t['symbol'] for t in sorted_tickers[:50]]
    except:
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "NEARUSDT", "INJUSDT", "ATOMUSDT", "BNBUSDT", "WIFUSDT", "LTCUSDT", "XRPUSDT"]

def get_candles(symbol, limit=500):
    params = {"symbol":symbol,"granularity":"15m","limit":limit,"productType":"USDT-FUTURES"}
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
        data = r.get("data", [])
        return sorted([[float(c[i]) for i in range(6)] for c in data], key=lambda x: x[0])
    except:
        return []

def simulate_v9_9(candles):
    wins = losses = pnl = 0
    for i in range(50, len(candles)-100, 5): # Step 5 to scan faster
        cl = [c[4] for c in candles[i-20:i+1]]
        if cl[-1] > cl[-5] and cl[-1] > sum(cl)/len(cl): # Simple Momentum
            ep = cl[-1]
            peak_pnl = 0
            current_sl_pnl = -50.0
            
            # Simulate trade
            for j in range(i+1, min(i+100, len(candles))):
                h, l, c = candles[j][2], candles[j][3], candles[j][4]
                pnl_high = (h/ep - 1) * 1000
                pnl_low  = (l/ep - 1) * 1000
                peak_pnl = max(peak_pnl, pnl_high)
                
                # TSL v9.9 Logic
                if peak_pnl >= 20:
                    new_sl_pnl = (int(peak_pnl/20)*20) - 10
                    current_sl_pnl = max(current_sl_pnl, new_sl_pnl)
                
                if pnl_low <= current_sl_pnl:
                    p = current_sl_pnl - 1.2
                    if p > 0: wins += 1
                    else: losses += 1
                    pnl += p
                    break
            else:
                p = (candles[-1][4]/ep-1)*1000 - 1.2
                if p > 0: wins += 1
                else: losses += 1
                pnl += p
                
    return wins, losses, pnl

def run_global_sweep():
    print("="*90)
    print("ROUND 9: THE GLOBAL MARKET SWEEP - TOP 50 TICKERS AUDIT")
    print("="*90)
    
    symbols = get_top_50_symbols()
    results = []
    
    for sym in symbols:
        candles = get_candles(sym)
        if not candles: continue
        
        w, l, p = simulate_v9_9(candles)
        t = w + l
        wr = round(w/t*100, 1) if t else 0
        results.append({"sym": sym, "trades": t, "wr": wr, "pnl": p})
        print(f"  {sym:<12} | Trades: {t:<4} | WR: {wr:>5}% | Total PnL: {p:>+9.1f}%")

    print("\n" + "="*90)
    print("TOP 10 BEST PERFORMERS (THE OBEDIENT ELITE):")
    best = sorted([r for r in results if r['trades'] > 5], key=lambda x: x['pnl'], reverse=True)
    for r in best[:10]:
        print(f"  {r['sym']:<12} | WR: {r['wr']:>5}% | PnL: {r['pnl']:>+9.1f}%")
        
    print("\nTOP 10 WORST PERFORMERS (THE BLACKLIST EXPANSION):")
    worst = sorted(results, key=lambda x: x['pnl'])
    for r in worst[:10]:
        print(f"  {r['sym']:<12} | WR: {r['wr']:>5}% | PnL: {r['pnl']:>+9.1f}%")

if __name__=="__main__":
    run_global_sweep()
