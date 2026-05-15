import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Ensure backend path is accessible
sys.path.append(os.getcwd())

# Import REAL logic
from crypto_engine import _determine_trade_side, _calc_tp_sl

def generate_micro_data(symbol, days=7):
    np.random.seed(sum(ord(c) for c in symbol))
    periods = days * 1440
    base_price = 100.0 if "BTC" not in symbol else 65000.0
    vol = 0.0015
    data = []
    price = base_price
    for i in range(periods):
        if i % 200 == 0: change = np.random.uniform(0.01, 0.03)
        else: change = np.random.normal(0, vol)
        price *= (1 + change)
        high = price * (1 + abs(np.random.normal(0, 0.001)))
        low = price * (1 - abs(np.random.normal(0, 0.001)))
        data.append({
            'timestamp': datetime.now() - timedelta(minutes=periods-i),
            'high': high, 'low': low, 'close': price
        })
    return pd.DataFrame(data)

def run_full_data_audit():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
    all_trades = []

    print(f"[PROCESS] Generating deep data for {len(symbols)} symbols...")
    for symbol in symbols:
        df = generate_micro_data(symbol, 7)
        for i in range(50, len(df)-60):
            row = df.iloc[i]
            window = df.iloc[i-20:i]
            mss_bull = row['close'] > window['high'].max()
            mss_bear = row['close'] < window['low'].min()
            
            tech = {
                'mss_bullish': mss_bull, 'mss_bearish': mss_bear,
                'fvg': 'BULLISH' if mss_bull else ('BEARISH' if mss_bear else 'NONE'),
                'in_demand': mss_bull, 'in_supply': mss_bear,
                'rvol': 1.5, 'atr': row['high'] - row['low'], 'obi': 0.2 if mss_bull else -0.2,
                'ema_21': df['close'].iloc[i-21:i].mean()
            }
            side, reason, score = _determine_trade_side(tech, 55 if mss_bull else 45, 0, "NEUTRAL", row['close'], 50, 50)
            
            if side:
                entry_p = row['close']
                tp_p, sl_p = _calc_tp_sl(entry_p, side, tech)
                max_profit = 0; max_drawdown = 0; status = "LOSS"; exit_idx = None
                
                for j in range(i+1, min(i+1440, len(df))):
                    f_row = df.iloc[j]
                    pnl = (f_row['high']-entry_p)/entry_p if side=="buy" else (entry_p-f_row['low'])/entry_p
                    max_profit = max(max_profit, pnl)
                    dd = (entry_p-f_row['low'])/entry_p if side=="buy" else (f_row['high']-entry_p)/entry_p
                    max_drawdown = max(max_drawdown, dd)
                    
                    if side == "buy":
                        if f_row['high'] >= tp_p: status = "WIN"; exit_idx = j; break
                        if f_row['low'] <= sl_p: status = "LOSS"; exit_idx = j; break
                    else:
                        if f_row['low'] <= tp_p: status = "WIN"; exit_idx = j; break
                        if f_row['high'] >= sl_p: status = "LOSS"; exit_idx = j; break
                
                if exit_idx:
                    local_min = df.iloc[i-5:i+1]['low'].min()
                    local_max = df.iloc[i-5:i+1]['high'].max()
                    prec = abs(entry_p - local_min)/local_min if side=="buy" else abs(local_max - entry_p)/local_max
                    
                    all_trades.append({
                        'Time': row['timestamp'].strftime('%Y-%m-%d %H:%M'),
                        'Symbol': symbol, 'Side': side, 'Entry': round(entry_p, 4),
                        'Status': status, 'Precision%': round(prec*100, 2),
                        'Drawdown%': round(max_drawdown*100, 2),
                        'MaxProfit%': round(max_profit*100, 2)
                    })
                    i = exit_idx

    tdf = pd.DataFrame(all_trades)
    csv_path = "scratch/deep_behavior_data.csv"
    tdf.to_csv(csv_path, index=False)
    
    print("\n" + "="*90)
    print("=" + " "*30 + "DEEP BEHAVIORAL DATA REPORT" + " "*31 + "=")
    print("="*90)
    print(tdf.head(20).to_string(index=False))
    print("="*90)
    print(f"\n[SUCCESS] Full data exported to: {csv_path}")
    print(f"Total Trades Analyzed: {len(tdf)}")
    print(f"Win Rate: {(len(tdf[tdf['Status']=='WIN'])/len(tdf)*100):.2f}%")
    print(f"Avg Drawdown: {tdf['Drawdown%'].mean():.2f}%")
    print("="*90 + "\n")

if __name__ == "__main__":
    run_full_data_audit()
