import sys
sys.path.append('.')
import pickle
import numpy as np

with open('backend/spot_backtest_cache.pkl', 'rb') as f:
    raw_dataset = pickle.load(f)
clean_dataset = [df for i, df in enumerate(raw_dataset) if i != 22]

from backend.scratch.test_strat8_clean import coins_data, NUM_CANDLES

for coin_id in [35, 7, 18, 29, 15, 19]:
    cd = coins_data[coin_id]
    print(f"\n--- Analysis for Coin {coin_id} ---")
    # find where rvol >= 1.8 and v_vel >= 0.12 and cmo >= 35
    for t in range(50, NUM_CANDLES-32):
        if cd['trend_bull'][t] and cd['rvol'][t] >= 1.8 and cd['v_vel'][t] >= 0.12 and cd['cmo'][t] >= 35 and 0.5 <= cd['chg'][t] <= 18.0:
            ent = cd['close'][t]
            max_forward_high = np.max(cd['high'][t+1:t+33])
            min_forward_low = np.min(cd['low'][t+1:t+33])
            gain = (max_forward_high - ent) / ent * 100.0
            max_dd = (min_forward_low - ent) / ent * 100.0
            print(f"Candle {t} (Hour {t*0.25:.1f}): Entry={ent:.4f} | Next 8h Max Gain: +{gain:.1f}% | Next 8h Max Drawdown: {max_dd:.1f}%")
            break
