import pickle
import numpy as np
import pandas as pd

with open('backend/spot_backtest_cache.pkl', 'rb') as f:
    raw_dataset = pickle.load(f)

results = []
for df in raw_dataset:
    df = df.sort_values('ts').reset_index(drop=True)
    # Calculate 1h volume (sum 4 candles) vs 24h volume (sum 96 candles)
    vol_1h = df['baseVol'].rolling(4).sum()
    vol_24h = df['baseVol'].rolling(96).sum()
    vol_velocity = vol_1h / (vol_24h + 1e-9)
    
    # Calculate Keltner Channels
    kc_mid = df['close'].ewm(span=20, adjust=False).mean()
    kc_upper = kc_mid + (1.5 * df['atr'])
    kc_lower = kc_mid - (1.5 * df['atr'])
    squeeze_on = (df['bb_low'] > kc_lower) & (df['bb_up'] < kc_upper)
    squeeze_fired = squeeze_on.shift(1).rolling(5).max() == 1
    
    # CMO (Chande Momentum Oscillator)
    diff = df['close'].diff()
    up = diff.clip(lower=0)
    down = (-diff).clip(lower=0)
    sum_up = up.rolling(14).sum()
    sum_down = down.rolling(14).sum()
    cmo = 100 * (sum_up - sum_down) / (sum_up + sum_down + 1e-9)
    
    for i in range(50, len(df)-25):
        v_vel = vol_velocity.iloc[i]
        rvol_val = df['rvol'].iloc[i]
        close_p = df['close'].iloc[i]
        bb_up_val = df['bb_up'].iloc[i]
        rsi_val = df['rsi'].iloc[i]
        cmo_val = cmo.iloc[i]
        sq_fired = squeeze_fired.iloc[i]
        
        # Test elite combo:
        # RVOL >= 2.0, CMO >= 30, close near or above BB up, volume velocity >= 0.12 (12%)
        if rvol_val >= 2.0 and cmo_val >= 35 and v_vel >= 0.12 and df['trend_bullish'].iloc[i]:
            entry_p = close_p
            future_high = df['high'].iloc[i+1:i+25].max()
            future_low = df['low'].iloc[i+1:i+25].min()
            max_gain = (future_high - entry_p) / entry_p * 100
            max_drop = (entry_p - future_low) / entry_p * 100
            results.append({
                'max_gain': max_gain,
                'max_drop': max_drop,
                'sq_fired': sq_fired,
                'v_vel': v_vel,
                'cmo': cmo_val
            })

res_df = pd.DataFrame(results)
print(f"Total elite signals detected: {len(res_df)}")
print(f"Signals reaching +3%: {(res_df['max_gain'] >= 3.0).mean():.1%}")
print(f"Signals reaching +5%: {(res_df['max_gain'] >= 5.0).mean():.1%}")
print(f"Signals reaching +8%: {(res_df['max_gain'] >= 8.0).mean():.1%}")
print(f"Signals reaching +15%: {(res_df['max_gain'] >= 15.0).mean():.1%}")
print(f"Signals reaching +25%: {(res_df['max_gain'] >= 25.0).mean():.1%}")
print(f"Average Max Gain: {res_df['max_gain'].mean():.2f}%")
print(f"Average Max Drop: {res_df['max_drop'].mean():.2f}%")
