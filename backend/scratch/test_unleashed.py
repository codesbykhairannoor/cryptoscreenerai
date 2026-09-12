import pickle
import numpy as np
import pandas as pd

with open('backend/spot_backtest_cache.pkl', 'rb') as f:
    raw_dataset = pickle.load(f)

coins_data = []
for idx, df in enumerate(raw_dataset):
    df = df.sort_values('ts').reset_index(drop=True)
    vol_1h = df['baseVol'].rolling(4).sum()
    vol_24h = df['baseVol'].rolling(96).sum()
    vol_vel = vol_1h / (vol_24h + 1e-9)
    
    diff = df['close'].diff()
    up = diff.clip(lower=0)
    down = (-diff).clip(lower=0)
    sum_up = up.rolling(14).sum()
    sum_down = down.rolling(14).sum()
    cmo = 100 * (sum_up - sum_down) / (sum_up + sum_down + 1e-9)
    
    coins_data.append({
        'id': idx,
        'high': df['high'].to_numpy(dtype=float),
        'low': df['low'].to_numpy(dtype=float),
        'close': df['close'].to_numpy(dtype=float),
        'open': df['open'].to_numpy(dtype=float),
        'rsi': df['rsi'].to_numpy(dtype=float),
        'rvol': df['rvol'].to_numpy(dtype=float),
        'v_vel': vol_vel.to_numpy(dtype=float),
        'cmo': cmo.to_numpy(dtype=float),
        'trend_bull': df['trend_bullish'].to_numpy(dtype=bool),
        'chg': df['chg_24h'].to_numpy(dtype=float),
        'bb_up': df['bb_up'].to_numpy(dtype=float),
        'length': len(df)
    })

NUM_CANDLES = min(c['length'] for c in coins_data)
FEE = 0.001

print("=== TESTING UNLEASHED RUNAWAY MOMENTUM (REMOVING 18% CAP) ===")

def test_unleashed(max_chg=200.0, max_rsi=95.0, min_rvol=2.0, min_v_vel=0.10, trail_from_peak=5.0):
    balance = 100.00
    peak_bal = 100.00
    max_dd = 0.0
    trades = []
    pos = None
    
    for t in range(50, NUM_CANDLES):
        if pos is not None:
            cd = coins_data[pos['coin_idx']]
            h, l, c = cd['high'][t], cd['low'][t], cd['close'][t]
            ent = pos['entry']
            if h > pos['peak_price']: pos['peak_price'] = h
            peak_pct = (pos['peak_price'] - ent) / ent * 100.0
            
            # Aggressive Moonshot Trailing
            # Breakeven lock at +3% -> lock +0.5%
            if peak_pct >= 3.0:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.005)
            if peak_pct >= 8.0:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.04)
            if peak_pct >= 15.0:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.10)
            if peak_pct >= 25.0:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.18)
            if peak_pct >= 40.0:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.30)
            if peak_pct >= 60.0:
                pos['current_sl'] = max(pos['current_sl'], pos['peak_price'] * 0.90)
                
            exit_p = None
            if l <= pos['current_sl']:
                exit_p = pos['current_sl']
            elif t - pos['entry_t'] >= 36: # 9 hours
                exit_p = c
                
            if exit_p is not None:
                raw_pnl = (exit_p - ent) / ent * 100.0
                cost = pos['size']
                pnl_usd = cost * (raw_pnl / 100.0) - (cost * FEE * 2)
                balance += pnl_usd
                trades.append({'pnl_usd': pnl_usd, 'pnl_pct': raw_pnl, 'peak_pct': peak_pct, 'coin': pos['coin_idx']})
                if balance > peak_bal: peak_bal = balance
                dd = (peak_bal - balance) / peak_bal * 100.0
                if dd > max_dd: max_dd = dd
                pos = None
                continue
                
        if pos is None and balance >= 10.0:
            best_c = None
            best_sc = -1
            for c_idx, cd in enumerate(coins_data):
                # Runaway momentum condition
                if (cd['trend_bull'][t] and 
                    cd['rvol'][t] >= min_rvol and 
                    cd['v_vel'][t] >= min_v_vel and 
                    cd['cmo'][t] >= 30 and 
                    cd['rsi'][t] <= max_rsi and
                    1.0 <= cd['chg'][t] <= max_chg):
                    
                    sc = cd['rvol'][t] * 10 + cd['cmo'][t] + (cd['v_vel'][t] * 100)
                    if sc > best_sc:
                        best_sc = sc
                        best_c = c_idx
                        
            if best_c is not None:
                ent = coins_data[best_c]['close'][t]
                pos = {
                    'coin_idx': best_c,
                    'entry': ent,
                    'entry_t': t,
                    'size': balance * 0.95, # 95% all-in compounding
                    'peak_price': ent,
                    'current_sl': ent * 0.975 # -2.5% strict SL
                }
                
    wins = [tr for tr in trades if tr['pnl_usd'] > 0]
    losses = [tr for tr in trades if tr['pnl_usd'] <= 0]
    wr = len(wins) / len(trades) * 100.0 if trades else 0
    tot_p = sum(tr['pnl_usd'] for tr in wins)
    tot_l = abs(sum(tr['pnl_usd'] for tr in losses)) if losses else 0.001
    pf = tot_p / tot_l
    return balance, wr, pf, max_dd, len(trades), trades

for max_c in [30.0, 50.0, 100.0, 200.0]:
    for min_rv in [1.8, 2.2, 2.5]:
        for min_vv in [0.08, 0.10, 0.12]:
            bal, wr, pf, dd, num_t, trs = test_unleashed(max_chg=max_c, min_rvol=min_rv, min_v_vel=min_vv)
            if bal >= 120.0:
                print(f"MaxChg:{max_c}% | RVOL:{min_rv} | V-Vel:{min_vv} -> Final Bal: ${bal:.2f} (+{bal-100:.1f}%) | WR: {wr:.1f}% | PF: {pf:.2f} | MaxDD: {dd:.1f}% | Trades: {num_t}")
