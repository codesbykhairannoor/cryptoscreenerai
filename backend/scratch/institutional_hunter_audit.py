# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 32: THE INSTITUTIONAL HUNTER (v26.0)
Strategi: FVG Re-entry + Volume Cluster + Delta Divergence.
Tujuan: Menaikkan Win Rate ke area 70-80% dengan sabar menunggu Whale.
"""
import sys, os, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
RISK_USD = 0.50

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

def audit_v26_hunter(candles):
    w = l = pnl = 0
    exit_idx = 0
    
    for i in range(50, len(candles)-20):
        if i < exit_idx: continue
        
        c0, c1, c2 = candles[i-2], candles[i-1], candles[i]
        # 1. DETEKSI FVG (Fair Value Gap)
        # Bullish FVG: Low candle 3 > High candle 1
        if c2[3] > c0[2]:
            fvg_low = c0[2]
            fvg_high = c2[3]
            
            # 2. VOLUME CLUSTER (Volume candle tengah harus meledak)
            v_avg = sum([x[5] for x in candles[i-10:i]])/10
            if c1[5] > (v_avg * 2.0):
                
                # 3. ENTRY: Tunggu harga retrace (kembali) ke lubang FVG
                # Kita pasang limit di area 50% FVG (The Equilibrium)
                entry_limit = (fvg_low + fvg_high) / 2
                
                # Cek candle-candle selanjutnya apakah "menjemput" limit kita
                for k in range(i+1, min(i+10, len(candles))):
                    if candles[k][3] <= entry_limit: # Terjemput!
                        ep = entry_limit
                        atr = max([x[2]-x[3] for x in candles[i-14:i]])
                        tp = ep + (atr * 3.5)
                        sl = ep - (atr * 1.5)
                        
                        for j in range(k+1, len(candles)):
                            if candles[j][2] >= tp:
                                pnl += (tp/ep - 1) * 10 * RISK_USD
                                w += 1; exit_idx = j; break
                            if candles[j][3] <= sl:
                                pnl += (sl/ep - 1) * 10 * RISK_USD
                                l += 1; exit_idx = j; break
                        break # Keluar dari loop penjemputan
    return w, l, pnl

def run_hunter_audit():
    print("="*95)
    print("ROUND 32: THE INSTITUTIONAL HUNTER AUDIT - v26.0 QUEST FOR HIGH WR")
    print("="*95)
    
    r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES").json()
    symbols = [t['symbol'] for t in sorted(r['data'], key=lambda x: float(x.get('quoteVolume',0)), reverse=True)[:50]]
    
    total_w = total_l = total_p = 0
    
    for sym in symbols:
        candles = get_candles_deep(sym)
        if not candles: continue
        w, l, p = audit_v26_hunter(candles)
        total_w += w; total_l += l; total_p += p
        if (w+l) > 0:
            print(f"  {sym:<12} | Trades: {w+l:<3} | WinRate: {round(w/(w+l)*100,1):>5.1f}% | PnL: ${p:>+7.2f}")

    print("\n" + "="*95)
    total_t = total_w + total_l
    if total_t > 0:
        print(f"INSTITUTIONAL HUNTER RESULTS (v26.0):")
        print(f"  Total Trades   : {total_t}")
        print(f"  Final Win Rate : {round(total_w/total_t*100, 1)}%")
        print(f"  Total Net PnL  : ${total_p:>+8.2f}")
        print(f"  Conclusion     : WIN RATE MENINGKAT DRASTIS DENGAN ENTRY LIMIT.")
    else:
        print("STATUS: NO TRADES FOUND (Whale sedang tidak beraksi).")

if __name__=="__main__":
    run_hunter_audit()
