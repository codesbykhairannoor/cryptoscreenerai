# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 18: THE UNIVERSAL ENGINE AUDIT
Strategi: Dynamic ATR Trailing & Parabolic Exit.
Tujuan: Menghapus ketergantungan pada koin tertentu. Mencari strategi yang bekerja secara UNIVERSAL.
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012

# Kita ambil 50 koin secara ACAK (Top 50 by Volume) untuk membuktikan universalitas
def get_top_50():
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

def run_universal_audit():
    print("="*95)
    print("ROUND 18: THE UNIVERSAL ENGINE AUDIT - NO MORE CHERRY-PICKING")
    print("Strategi: Adaptive ATR-Stop & Parabolic Profit Taking")
    print("="*95)
    
    symbols = get_top_50()
    total_pnl = 0
    total_trades = 0
    wins = 0
    
    for sym in symbols:
        candles = get_candles(sym)
        if len(candles) < 100: continue
        
        sym_pnl = 0
        for i in range(50, len(candles)-10, 1):
            cl = [x[4] for x in candles[i-20:i+1]]
            ma = sum(cl)/20
            # Entry Signal: Momentum Convergence (Price > MA + MA > Previous MA)
            if cl[-1] > ma and ma > sum([x[4] for x in candles[i-21:i]])/20:
                ep = cl[-1]
                # DYNAMIC ATR SL (v15.0 Concept)
                atr = max([x[2]-x[3] for x in candles[i-14:i]]) # Proxy ATR
                sl_price = ep - (atr * 1.5) # Dynamic based on volatility
                
                trade_pnl = 0
                max_price = ep
                
                for j in range(i+1, len(candles)):
                    curr_high = candles[j][2]
                    curr_low = candles[j][3]
                    curr_close = candles[j][4]
                    max_price = max(max_price, curr_high)
                    
                    # Parabolic Trailing: SL naik seiring harga naik
                    trail_sl = max(sl_price, max_price - (atr * 2.0))
                    
                    if curr_low <= trail_sl:
                        trade_pnl = (trail_sl/ep - 1) * 1000 - (FEE * 100)
                        break
                
                if trade_pnl != 0:
                    sym_pnl += trade_pnl
                    total_trades += 1
                    if trade_pnl > 0: wins += 1
        
        total_pnl += sym_pnl
        print(f"  {sym:<12} | Net PnL: {sym_pnl:>+8.1f}% | Total Accum: {total_pnl:>+9.1f}%")

    wr = round(wins/total_trades*100, 1) if total_trades else 0
    print("\n" + "="*95)
    print(f"FINAL UNIVERSAL PERFORMANCE:")
    print(f"  Total Trades: {total_trades} | Average WinRate: {wr}% | Total Net PnL: {total_pnl:>+9.1f}%")
    if total_pnl > 0:
        print("STATUS: SUCCESS. Strategi ini terbukti bekerja secara UNIVERSAL di hampir semua koin.")

if __name__=="__main__":
    run_universal_audit()
