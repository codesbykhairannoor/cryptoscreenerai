import pickle
import pandas as pd
import numpy as np

with open('backend/spot_backtest_cache.pkl', 'rb') as f:
    raw_dataset = pickle.load(f)

for target_idx in [9, 15, 23, 43]:
    df = raw_dataset[target_idx].sort_values('ts').reset_index(drop=True)
    df['pct_chg_4h'] = (df['close'] - df['close'].shift(16)) / df['close'].shift(16) * 100
    max_4h_idx = df['pct_chg_4h'].idxmax()
    max_gain = df['pct_chg_4h'].max()
    print(f"\n=== Coin #{target_idx} Biggest 4h Move: +{max_gain:.1f}% around candle {max_4h_idx} ===")
    start_c = max(0, max_4h_idx - 5)
    for c in range(start_c, min(start_c + 8, len(df))):
        cl = df['close'].iloc[c]
        rv = df['rvol'].iloc[c]
        rs = df['rsi'].iloc[c]
        ch = df['chg_24h'].iloc[c]
        b = df['trend_bullish'].iloc[c]
        print(f"Candle {c}: Close: {cl:.6f} | RVOL: {rv:.1f}x | RSI: {rs:.1f} | 24h: {ch:.1f}% | Bull: {b}")
