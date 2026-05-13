# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 15: THE CIRCUIT BREAKER STRESS TEST
Menguji apakah fitur v12.0 (Penalty Box) berhasil menahan kerugian saat koin 'Bintang' berubah menjadi 'Musuh'.
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012
SLIPPAGE = 0.0005

def get_bad_regime_data(symbol="INJUSDT"):
    # Kita ambil data di mana INJ sedang 'nakal' (Block 4 hasil audit sebelumnya)
    params = {"symbol":symbol,"granularity":"15m","limit":200,"productType":"USDT-FUTURES"}
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
        return sorted([[float(c[i]) for i in range(6)] for c in r.get("data", [])], key=lambda x: x[0])
    except: return []

def simulate_trade(candles, start_idx):
    ep = candles[start_idx][4]
    peak = 0
    sl_pnl = -50.0
    for j in range(start_idx+1, min(start_idx+100, len(candles))):
        h, l = candles[j][2], candles[j][3]
        p_high, p_low = (h/ep-1)*1000, (l/ep-1)*1000
        peak = max(peak, p_high)
        if peak >= 20: sl_pnl = max(sl_pnl, (int(peak/20)*20)-10)
        if p_low <= sl_pnl: return sl_pnl - (FEE*100) - (SLIPPAGE*100*2)
    return (candles[-1][4]/ep-1)*1000 - (FEE*100) - (SLIPPAGE*100*2)

def run_stress_test():
    print("="*95)
    print("ROUND 15: CIRCUIT BREAKER STRESS TEST - SAVING THE BALANCE")
    print("="*95)
    
    candles = get_bad_regime_data()
    if not candles: return

    # TEST 1: NO CIRCUIT BREAKER
    pnl_no_cb = 0
    trades_no_cb = 0
    for i in range(30, len(candles)-30, 2):
        if candles[i][4] > sum([c[4] for c in candles[i-20:i]])/20:
            pnl_no_cb += simulate_trade(candles, i)
            trades_no_cb += 1
            
    # TEST 2: WITH CIRCUIT BREAKER (v12.0)
    pnl_with_cb = 0
    trades_with_cb = 0
    consecutive_losses = 0
    lock_until = 0
    
    for i in range(30, len(candles)-30, 2):
        if i < lock_until: continue
        
        if candles[i][4] > sum([c[4] for c in candles[i-20:i]])/20:
            res = simulate_trade(candles, i)
            pnl_with_cb += res
            trades_with_cb += 1
            
            if res < 0:
                consecutive_losses += 1
                if consecutive_losses >= 2:
                    # LOCK COIN for 50 candles (simulasi penalty box)
                    lock_until = i + 50 
                    consecutive_losses = 0
            else:
                consecutive_losses = 0

    print(f"RESULTS FOR INJUSDT (Enemy Phase):")
    print(f"  [NO BREAKER] Total Trades: {trades_no_cb:<3} | Net PnL: {pnl_no_cb:>+9.1f}%")
    print(f"  [WITH v12.0] Total Trades: {trades_with_cb:<3} | Net PnL: {pnl_with_cb:>+9.1f}%")
    
    saved = pnl_with_cb - pnl_no_cb
    print(f"\n  > CIRCUIT BREAKER SAVED: {saved:>+8.1f}% PnL!")
    if saved > 0:
        print(f"  > STATUS: SUCCESS. Bot berhenti tepat waktu sebelum drawdown parah.")

if __name__=="__main__":
    run_stress_test()
