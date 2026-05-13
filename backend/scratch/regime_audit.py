# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 14: THE REGIME SHIFT AUDIT
Tujuan: Mencari tahu kapan koin 'Bintang' berubah menjadi 'Musuh'.
Menguji performa koin dalam 10 blok waktu berbeda (Sequential Testing).
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012
SLIPPAGE = 0.0005

COINS = ["NEARUSDT", "INJUSDT", "DOTUSDT", "TIAUSDT"]

def get_candles_very_deep(symbol, total=2000):
    all_candles = []
    end_time = None
    for _ in range(10): # 10 x 200 = 2000 candles (~20 days)
        params = {"symbol":symbol,"granularity":"15m","limit":200,"productType":"USDT-FUTURES"}
        if end_time: params["endTime"] = end_time
        try:
            r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles", params=params, timeout=10).json()
            data = r.get("data", [])
            if not data: break
            all_candles.extend(data)
            end_time = data[-1][0]
            time.sleep(0.1)
        except: break
    return sorted([[float(c[i]) for i in range(6)] for c in all_candles], key=lambda x: x[0])

def audit_regime(candles):
    # Split candles into 5 blocks (400 candles each)
    block_size = len(candles) // 5
    blocks = [candles[i:i + block_size] for i in range(0, len(candles), block_size)]
    
    block_results = []
    for idx, block in enumerate(blocks):
        wins = losses = pnl = 0
        if len(block) < 50: continue
        for i in range(30, len(block)-30, 5):
            c = [x[4] for x in block[i-20:i+1]]
            if c[-1] > sum(c)/len(c):
                ep = c[-1]
                peak = 0
                sl_pnl = -50.0
                for j in range(i+1, min(i+50, len(block))):
                    h, l = block[j][2], block[j][3]
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
        wr = round(wins/(wins+losses)*100, 1) if (wins+losses) else 0
        block_results.append({"wr": wr, "pnl": pnl})
    return block_results

def run_regime_audit():
    print("="*95)
    print("ROUND 14: REGIME SHIFT AUDIT - THE 'FRIEND TO ENEMY' TEST")
    print("="*95)
    
    for sym in COINS:
        candles = get_candles_very_deep(sym)
        if not candles: continue
        
        print(f"\nAUDITING {sym} OVER 5 TIME BLOCKS:")
        results = audit_regime(candles)
        
        for i, r in enumerate(results):
            status = "FRIEND (Win)" if r['pnl'] > 0 else "ENEMY (Loss)"
            print(f"  Block {i+1}: WR {r['wr']:>5}% | PnL {r['pnl']:>+9.1f}% | State: {status}")
            
        # Analysis
        pnl_values = [r['pnl'] for r in results]
        volatility = round(max(pnl_values) - min(pnl_values), 1)
        print(f"  > Consistency Gap: {volatility}% (Semakin kecil semakin stabil)")

if __name__=="__main__":
    run_regime_audit()
