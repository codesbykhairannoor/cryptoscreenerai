# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 7: UNIVERSAL ADAPTIVE STRATEGY
Menguji apakah 'Volatility-Adjusted SL/TP' bisa menaklukkan semua jenis koin.
Data: 2000 candles per coin (~20 hari).
"""
import sys, os, time, requests, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012

# 10 Koin Berbeda (Meme, Bluechip, Losers, Winners)
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "NEARUSDT", "WIFUSDT", "BNBUSDT", "ATOMUSDT", "LTCUSDT", "DOGEUSDT", "INJUSDT"]

def get_candles_very_deep(symbol, total=2000):
    all_candles = []
    end_time = None
    for _ in range((total // 200) + 1):
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

def calc_indicators(closes, highs, lows):
    # RSI
    p=14; g,l=[],[]
    for i in range(1,len(closes)):
        d=closes[i]-closes[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g[:p])/p; al=sum(l[:p])/p
    for i in range(p,len(g)):
        ag=(ag*(p-1)+g[i])/p; al=(al*(p-1)+l[i])/p
    rsi = 100-(100/(1+(ag/(al or 1e-6))))
    
    # ATR (Volatility)
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        tr_list.append(tr)
    atr = sum(tr_list[-14:])/14
    
    return rsi, atr

def run_universal_test():
    print("="*80)
    print("ROUND 7: UNIVERSAL ADAPTIVE STRATEGY (Volatility-Adjusted SL/TP)")
    print("="*80)
    
    overall_results = []

    for sym in COINS:
        candles = get_candles_very_deep(sym)
        if not candles: continue
        
        wins = losses = pnl = 0
        for i in range(100, len(candles)-100):
            window = candles[i-50:i+1]
            h = [c[2] for c in window]
            l = [c[3] for c in window]
            cl = [c[4] for c in window]
            
            rsi, atr = calc_indicators(cl, h, l)
            
            # VWAP Dist
            pv=vol=0
            for cw in window[-30:]:
                t=(cw[2]+cw[3]+cw[4])/3; pv+=t*cw[5]; vol+=cw[5]
            v_val = pv/vol if vol else cl[-1]
            vd = (cl[-1]-v_val)/v_val*100
            
            # CRITERIA: Momentum + Volume Support
            if 52 <= rsi <= 68 and vd > 0.3:
                ep = cl[-1]
                
                # ADAPTIVE LOGIC: SL/TP berdasarkan ATR (Volatilitas koin)
                # Jika koin liar (ATR tinggi), SL otomatis melebar.
                sl_dist = atr * 3.0 # 3x ATR untuk SL
                tp_dist = atr * 6.0 # 6x ATR untuk TP (RR 1:2)
                
                # Cap SL at 6% max, 2% min
                sl_pct = max(0.02, min(0.06, sl_dist / ep))
                tp_pct = sl_pct * 2.0 # Target RR 1:2
                
                tp_price, sl_price = ep*(1+tp_pct), ep*(1-sl_pct)
                
                # Simulate next 96 candles (24h)
                outcome = "TIMEOUT"; trade_pnl = 0
                for j in range(i+1, min(i+96, len(candles))):
                    if candles[j][3] <= sl_price: 
                        outcome="LOSS"; trade_pnl = -(sl_pct*100) - 0.12; break
                    if candles[j][2] >= tp_price: 
                        outcome="WIN"; trade_pnl = (tp_pct*100) - 0.12; break
                
                if outcome == "TIMEOUT":
                    trade_pnl = (candles[i+95][4]/ep-1)*100 - 0.12
                    outcome = "WIN" if trade_pnl > 0 else "LOSS"
                
                if outcome == "WIN": wins += 1
                else: losses += 1
                pnl += trade_pnl
        
        t = wins + losses
        wr = round(wins/t*100, 1) if t else 0
        print(f"  {sym:<10} | Trades: {t:<4} | WR: {wr:>5}% | PnL: {pnl:>+8.1f}%")
        overall_results.append((sym, t, wr, pnl))

    print("\n" + "="*80)
    final_t = sum(r[1] for r in overall_results)
    final_wr = round(sum(r[1]*r[2] for r in overall_results)/final_t, 1) if final_t else 0
    final_pnl = sum(r[3] for r in overall_results)
    print(f"OVERALL UNIVERSAL PERFORMANCE (10 Diverse Coins):")
    print(f"  Total Trades : {final_t}")
    print(f"  Avg Win Rate : {final_wr}%")
    print(f"  Total Profit : {final_pnl:>+8.1f}%")
    print("="*80)

if __name__=="__main__":
    run_universal_test()
