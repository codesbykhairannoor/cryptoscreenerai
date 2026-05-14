import requests
import pandas as pd
import numpy as np
import concurrent.futures

# --- MASSIVE STRATEGY OPTIMIZER v33.0 ---
# Mencari Kombinasi "Holy Grail" dari Timeframe, SL, TP, dan Trailing

def fetch_data(symbol, interval):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit=1000"
    try:
        r = requests.get(url, timeout=10).json()
        df = pd.DataFrame(r, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
        
        df['ema_9'] = df['c'].ewm(span=9).mean()
        df['ema_21'] = df['c'].ewm(span=21).mean()
        df['atr'] = (df['h'] - df['l']).rolling(14).mean()
        df['vwap'] = (df['c'] * df['v']).cumsum() / df['v'].cumsum()
        return symbol, df.dropna()
    except: return symbol, None

def simulate(df, sl_pct, tp_mult, trail_step):
    wallet = 10.0
    margin = 5.0
    lev = 10
    fee = 0.0006
    in_pos = None
    trades = []
    
    for i in range(50, len(df)):
        row = df.iloc[i]
        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if cpnl > in_pos['peak']: in_pos['peak'] = cpnl
            
            # Trailing
            if in_pos['peak'] >= trail_step:
                locked = (int(in_pos['peak'] / trail_step) * trail_step) - (trail_step/2)
                new_sl = in_pos['ent'] * (1 + (max(0, locked)/100)/lev)
                if new_sl > in_pos['sl']: in_pos['sl'] = new_sl

            # Exit
            ep = 0
            if row['l'] <= in_pos['sl']: ep = in_pos['sl']
            elif row['h'] >= in_pos['tp']: ep = in_pos['tp']
            
            if ep > 0:
                f_pnl = ((ep - in_pos['ent'])/in_pos['ent']) * lev * 100
                net = (f_pnl/100 * margin) - (margin * lev * fee * 2)
                wallet += net
                trades.append(net)
                in_pos = None
            continue

        if in_pos is None and wallet >= margin:
            if row['ema_9'] > row['ema_21'] and row['c'] > row['vwap']:
                in_pos = {
                    'ent': row['c'], 'peak': 0, 'margin': margin,
                    'sl': row['c'] * (1 - sl_pct/100),
                    'tp': row['c'] + (row['atr'] * tp_mult)
                }
    
    win_rate = (len([t for t in trades if t > 0]) / len(trades) * 100) if trades else 0
    return wallet, win_rate, len(trades)

def main():
    print("\n" + "="*80)
    print("MASSIVE OPTIMIZER: MENCARI POLA HOLY GRAIL v33.0")
    print("="*80)
    
    symbols = ["SOLUSDT", "BTCUSDT", "ETHUSDT", "WLDUSDT", "ENAUSDT"] # Sample representatif
    timeframes = ["15m", "1h"]
    sl_options = [1.0, 1.5, 2.0] # Price % (10%, 15%, 20% PnL)
    trail_options = [5, 10, 15] # PnL %
    
    results = []
    
    for tf in timeframes:
        print(f"\n[SCAN] Menguji Timeframe {tf}...")
        all_data = {}
        for s in symbols:
            _, df = fetch_data(s, tf)
            if df is not None: all_data[s] = df
            
        for sl in sl_options:
            for trail in trail_options:
                total_bal = 0
                total_wr = 0
                total_trades = 0
                for s, df in all_data.items():
                    bal, wr, count = simulate(df, sl, 4.0, trail)
                    total_bal += bal
                    total_wr += wr
                    total_trades += count
                
                avg_bal = total_bal / len(symbols)
                avg_wr = total_wr / len(symbols)
                results.append({
                    'tf': tf, 'sl': sl, 'trail': trail, 
                    'avg_bal': avg_bal, 'avg_wr': avg_wr, 'total_trades': total_trades
                })

    # Sort by balance
    results.sort(key=lambda x: x['avg_bal'], reverse=True)
    
    print("\n" + "="*80)
    print(f"{'TF':<5} | {'SL%':<5} | {'TRAIL':<6} | {'AVG BAL':<10} | {'WR%':<8} | {'TRADES'}")
    print("-" * 80)
    for r in results[:15]:
        print(f"{r['tf']:<5} | {r['sl']:<5.1f} | {r['trail']:<6} | ${r['avg_bal']:<9.2f} | {r['avg_wr']:>6.1f}% | {r['total_trades']}")
    
    print("="*80)
    best = results[0]
    print(f"KESIMPULAN: Pola TERBAIK adalah Timeframe {best['tf']} dengan SL {best['sl']}% dan Trailing {best['trail']}%")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
