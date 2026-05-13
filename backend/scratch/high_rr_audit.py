# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 17: THE HIGH-RR SURVIVAL AUDIT
Strategi: TP 8.0% (80% PnL) vs SL 1.4% (14% PnL).
Tujuan: Mencari koin yang bisa 'Moon' tanpa koreksi tajam.
Saldo: Simulasi 12 USDT (Modal $3 per trade).
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
SL_LIMIT = 0.014
TP_LIMIT = 0.080
MARGIN = 3.0
SALDO_AWAL = 12.0

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

def run_high_rr_audit():
    print("="*95)
    print(f"ROUND 17: HIGH-RR SURVIVAL AUDIT (TP: 8.0% | SL: 1.4%)")
    print(f"Target: Finding coins that 'Moon' without retracing 1.4%")
    print("="*95)
    
    symbols = get_all_symbols()
    all_results = []
    
    for sym in symbols:
        candles = get_candles(sym)
        if not candles: continue
        
        wins = losses = 0
        for i in range(20, len(candles)-60, 5):
            cl = [x[4] for x in candles[i-20:i+1]]
            if cl[-1] > sum(cl)/len(cl): # Momentum trigger
                ep = cl[-1]
                for j in range(i+1, min(i+100, len(candles))):
                    h, l = candles[j][2], candles[j][3]
                    if l <= ep * (1 - SL_LIMIT): # SL Hit
                        losses += 1
                        break
                    if h >= ep * (1 + TP_LIMIT): # TP Hit
                        wins += 1
                        break
        
        wr = round(wins/(wins+losses)*100, 1) if (wins+losses) else 0
        pnl = (wins * (TP_LIMIT * 10 * MARGIN)) - (losses * (SL_LIMIT * 10 * MARGIN))
        
        if wins > 0:
            all_results.append({"sym": sym, "wr": wr, "pnl": pnl, "wins": wins, "losses": losses})
            print(f"  {sym:<12} | Wins: {wins:<2} | Losses: {losses:<2} | WR: {wr:>5}% | Net: ${pnl:>+6.2f}")

    print("\n" + "="*95)
    print("THE HIGH-RR SURVIVORS (Koin yang sanggup lari 8%):")
    survivors = sorted(all_results, key=lambda x: x['pnl'], reverse=True)
    for r in survivors[:10]:
        print(f"  {r['sym']:<12} | WR: {r['wr']:>5}% | Net: ${r['pnl']:>+6.2f} | PnL Factor: {round(r['wins']*5.7/max(1,r['losses']),2)}")

if __name__=="__main__":
    run_high_rr_audit()
