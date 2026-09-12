import pickle
import pandas as pd
import numpy as np

with open('backend/spot_backtest_cache.pkl', 'rb') as f:
    raw = pickle.load(f)

print(f"Loaded {len(raw)} coins.")

pump_episodes = []

for idx, df in enumerate(raw):
    df = df.sort_values('ts').reset_index(drop=True)
    n = len(df)
    
    # Calculate 4h forward return (16 candles of 15m)
    # and 8h forward return (32 candles)
    # and 12h forward return (48 candles)
    c = df['close'].to_numpy()
    h = df['high'].to_numpy()
    
    # Check max gain in next 16, 32 candles
    for t in range(50, n - 32):
        cur_p = c[t]
        max_4h_high = np.max(h[t+1:t+17])
        max_8h_high = np.max(h[t+1:t+33])
        gain_4h = (max_4h_high - cur_p) / cur_p * 100.0
        gain_8h = (max_8h_high - cur_p) / cur_p * 100.0
        
        if gain_8h >= 25.0: # Huge pump of >= 25% in 8 hours!
            vol_1h = df['baseVol'].iloc[t-3:t+1].sum()
            vol_24h = df['baseVol'].iloc[max(0, t-95):t+1].sum()
            v_vel = vol_1h / (vol_24h + 1e-9)
            pump_episodes.append({
                'coin_idx': idx,
                'candle_idx': t,
                'price': cur_p,
                'gain_4h': gain_4h,
                'gain_8h': gain_8h,
                'rsi': df['rsi'].iloc[t],
                'rvol': df['rvol'].iloc[t],
                'chg_24h': df['chg_24h'].iloc[t],
                'trend_bull': df['trend_bullish'].iloc[t],
                'v_vel': v_vel
            })

p_df = pd.DataFrame(pump_episodes)
print(f"Total >=25% 8-hour pump opportunities found: {len(p_df)}")
if not p_df.empty:
    print("\nSample of top pump episodes:")
    print(p_df.sort_values('gain_8h', ascending=False).head(15)[['coin_idx', 'candle_idx', 'price', 'gain_4h', 'gain_8h', 'rvol', 'v_vel', 'chg_24h', 'rsi']])
