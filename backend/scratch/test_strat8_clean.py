import pickle
import numpy as np
import pandas as pd

with open('backend/spot_backtest_cache.pkl', 'rb') as f:
    raw_dataset = pickle.load(f)

# Filter out coin 22 (stablecoin)
clean_dataset = [df for i, df in enumerate(raw_dataset) if i != 22]

coins_data = []
for idx, df in enumerate(clean_dataset):
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
        'rvol': df['rvol'].to_numpy(dtype=float),
        'v_vel': vol_vel.to_numpy(dtype=float),
        'cmo': cmo.to_numpy(dtype=float),
        'trend_bull': df['trend_bullish'].to_numpy(dtype=bool),
        'chg': df['chg_24h'].to_numpy(dtype=float),
        'length': len(df)
    })

NUM_CANDLES = min(c['length'] for c in coins_data)
FEE = 0.001

balance = 100.00
pos = None
trades = []

for t in range(50, NUM_CANDLES):
    if pos is not None:
        cd = coins_data[pos['coin_idx']]
        h, l, c = cd['high'][t], cd['low'][t], cd['close'][t]
        ent = pos['entry']
        if h > pos['peak']: pos['peak'] = h
        peak_pct = (pos['peak'] - ent) / ent * 100.0
        
        if peak_pct >= 35.0: pos['sl'] = max(pos['sl'], ent * 1.25)
        elif peak_pct >= 18.0: pos['sl'] = max(pos['sl'], ent * 1.12)
        elif peak_pct >= 10.0: pos['sl'] = max(pos['sl'], ent * 1.07)
        elif peak_pct >= 5.5: pos['sl'] = max(pos['sl'], ent * 1.032)
        elif peak_pct >= 2.5: pos['sl'] = max(pos['sl'], ent * 1.005)
        if peak_pct >= 50.0: pos['sl'] = max(pos['sl'], pos['peak'] * 0.92)
        
        exit_p = None
        reason = ''
        if l <= pos['sl']:
            exit_p = pos['sl']
            reason = 'ESCALATOR' if pos['sl'] > ent else 'SL'
        elif t - pos['entry_t'] >= 48:
            exit_p = c
            reason = 'TIMEOUT'
            
        if exit_p is not None:
            cost = pos['size']
            gross = (exit_p / ent) * cost
            fee = (cost * FEE) + (gross * FEE)
            pnl = gross - fee - cost
            balance += pnl
            trades.append({'pnl': pnl, 'pct': (exit_p - ent)/ent*100, 'reason': reason, 'coin': pos['coin_idx'], 'bal': balance})
            pos = None
            continue
            
    if pos is None and balance >= 10.0:
        best_sc = -999
        best_c = None
        for idx, cd in enumerate(coins_data):
            c = cd['close'][t]
            rvol = cd['rvol'][t]
            v_vel = cd['v_vel'][t]
            cmo = cd['cmo'][t]
            chg = cd['chg'][t]
            bull = cd['trend_bull'][t]
            if bull and rvol >= 1.8 and v_vel >= 0.12 and cmo >= 35 and 0.5 <= chg <= 18.0:
                sc = rvol * 10 + cmo + (v_vel * 100)
                if sc > best_sc:
                    best_sc = sc
                    best_c = idx
        if best_c is not None:
            ent = coins_data[best_c]['close'][t]
            pos = {'coin_idx': best_c, 'entry': ent, 'entry_t': t, 'size': balance, 'peak': ent, 'sl': ent * (1.0 - 0.025)}

print(f"Final Balance: ${balance:.2f} ({(balance-100)/100*100:+.2f}%)")
print(f"Total Trades: {len(trades)}")
wins = [tr for tr in trades if tr['pnl'] > 0]
print(f"Wins: {len(wins)}, Losses: {len(trades)-len(wins)}, Win Rate: {len(wins)/len(trades)*100:.1f}%")
for tr in trades:
    print(f"Coin {tr['coin']:<2} | {tr['pct']:+6.2f}% | PnL: ${tr['pnl']:+6.2f} | Bal: ${tr['bal']:<6.2f} | {tr['reason']}")
