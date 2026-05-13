# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 6: SCIENTIFIC AUDIT (Strategy vs Asset Behavior)
Membuktikan apakah kekalahan disebabkan oleh Strategi atau Karakter Koin.
"""
import sys, os, time, requests, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012

WINNERS = ["NEARUSDT", "ATOMUSDT", "BNBUSDT"]
LOSERS  = ["SOLUSDT", "WIFUSDT", "LTCUSDT"]

def get_candles_deep(symbol, total=1000):
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

def calc_rsi(closes,p=14):
    g,l=[],[]
    for i in range(1,len(closes)):
        d=closes[i]-closes[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g[:p])/p; al=sum(l[:p])/p
    for i in range(p,len(g)):
        ag=(ag*(p-1)+g[i])/p; al=(al*(p-1)+l[i])/p
    return 100-(100/(1+(ag/(al or 1e-6))))

def audit_group(name, symbols):
    print(f"\nAUDITING GROUP: {name}")
    print("-" * 50)
    
    overall_trades = 0
    overall_wins = 0
    overall_pnl = 0
    
    for sym in symbols:
        candles = get_candles_deep(sym)
        if not candles: continue
        
        wins = losses = pnl = 0
        for i in range(50, len(candles)-48):
            window = candles[i-50:i+1]
            cl = [c[4] for c in window]
            rsi = calc_rsi(cl)
            
            # VWAP
            pv=vol=0
            for cw in window[-30:]:
                t=(cw[2]+cw[3]+cw[4])/3; pv+=t*cw[5]; vol+=cw[5]
            vd = (cl[-1]-(pv/vol))/(pv/vol)*100 if vol else 0
            
            # v9.5 Elite Criteria (SAMA PERSIS UNTUK SEMUA)
            if 52 <= rsi <= 65 and vd > 0.5:
                # Simulasi Trade
                ep = cl[-1]
                tp, sl = ep*1.09, ep*0.95
                outcome = "TIMEOUT"
                trade_pnl = 0
                for j in range(i+1, min(i+48, len(candles))):
                    if candles[j][3] <= sl: 
                        outcome="LOSS"; trade_pnl=-5.12; break
                    if candles[j][2] >= tp: 
                        outcome="WIN"; trade_pnl=8.88; break
                
                if outcome == "TIMEOUT":
                    trade_pnl = (candles[i+47][4]/ep-1)*100 - 0.12
                    outcome = "WIN" if trade_pnl > 0 else "LOSS"
                
                if outcome == "WIN": wins += 1
                else: losses += 1
                pnl += trade_pnl
        
        t = wins + losses
        wr = round(wins/t*100, 1) if t else 0
        print(f"  {sym:<10} | Trades: {t:<3} | WR: {wr:>5}% | PnL: {pnl:>+7.1f}%")
        overall_trades += t
        overall_wins += wins
        overall_pnl += pnl
        
    final_wr = round(overall_wins/overall_trades*100, 1) if overall_trades else 0
    return final_wr, overall_pnl, overall_trades

def main():
    print("="*70)
    print("ROUND 6: SCIENTIFIC AUDIT - WINNERS VS LOSERS (1000 CANDLES)")
    print("="*70)
    
    w_wr, w_pnl, w_t = audit_group("WINNERS (Institutional Grade)", WINNERS)
    l_wr, l_pnl, l_t = audit_group("LOSERS (Choppy/Manipulated)", LOSERS)
    
    print("\n" + "="*70)
    print(f"FINAL COMPARISON:")
    print(f"  WINNERS Group: WR {w_wr}% | Trades: {w_t} | PnL: {w_pnl:>+8.1f}%")
    print(f"  LOSERS  Group: WR {l_wr}% | Trades: {l_t} | PnL: {l_pnl:>+8.1f}%")
    print("-" * 70)
    
    diff = w_wr - l_wr
    print(f"  DIFFERENCE IN WR: {diff}%")
    if diff > 30:
        print("\nKESIMPULAN: STRATEGI SAMA, HASIL BEDA JAUH.")
        print("Ini membuktikan bahwa MASALAH BUKAN PADA STRATEGI, tapi pada pergerakan")
        print("harga koin tertentu yang memang 'unpredictable' (Gagal teknikal).")
    print("="*70)

if __name__=="__main__":
    main()
