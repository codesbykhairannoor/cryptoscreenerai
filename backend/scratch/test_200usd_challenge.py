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
    
    # 20-period High breakout
    high_20 = df['high'].rolling(20).max()
    
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
        'high_20': high_20.to_numpy(dtype=float),
        'length': len(df)
    })

NUM_CANDLES = min(c['length'] for c in coins_data)
FEE = 0.001

def run_challenge(timeout_h=4, sl_pct=2.0, min_v_vel=0.08, min_rvol=1.5, min_cmo=25):
    balance = 100.00
    peak_bal = 100.00
    max_dd = 0.0
    trades = []
    pos = None
    timeout_candles = timeout_h * 4
    
    for t in range(50, NUM_CANDLES):
        if pos is not None:
            cd = coins_data[pos['coin_idx']]
            h, l, c = cd['high'][t], cd['low'][t], cd['close'][t]
            ent = pos['entry']
            if h > pos['peak_price']: pos['peak_price'] = h
            peak_pct = (pos['peak_price'] - ent) / ent * 100.0
            
            # Escalator:
            if peak_pct >= 25.0:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.20)
            elif peak_pct >= 15.0:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.11)
            elif peak_pct >= 8.0:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.055)
            elif peak_pct >= 4.0:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.02)
            elif peak_pct >= 2.0:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.004) # Breakeven
                
            if peak_pct >= 40.0:
                pos['current_sl'] = max(pos['current_sl'], pos['peak_price'] * 0.93)
                
            exit_p = None
            exit_reason = None
            if l <= pos['current_sl']:
                exit_p = pos['current_sl']
                exit_reason = "SL/Escalator"
            elif t - pos['entry_t'] >= timeout_candles:
                # Capital velocity timeout: cut fast if no pump
                exit_p = c
                exit_reason = "Velocity Timeout"
                
            if exit_p is not None:
                raw_pnl = (exit_p - ent) / ent * 100.0
                cost = pos['size']
                pnl_usd = cost * (raw_pnl / 100.0) - (cost * FEE * 2)
                balance += pnl_usd
                trades.append({'pnl_usd': pnl_usd, 'pnl_pct': raw_pnl, 'peak_pct': peak_pct, 'reason': exit_reason})
                if balance > peak_bal: peak_bal = balance
                dd = (peak_bal - balance) / peak_bal * 100.0
                if dd > max_dd: max_dd = dd
                pos = None
                continue
                
        if pos is None and balance >= 10.0:
            best_c = None
            best_sc = -1
            for c_idx, cd in enumerate(coins_data):
                if (cd['trend_bull'][t] and 
                    cd['rvol'][t] >= min_rvol and 
                    cd['v_vel'][t] >= min_v_vel and 
                    cd['cmo'][t] >= min_cmo and 
                    0.5 <= cd['chg'][t] <= 25.0):
                    
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
                    'size': balance * 0.98, # Full 98% compound deployment
                    'peak_price': ent,
                    'current_sl': ent * (1.0 - sl_pct / 100.0)
                }
                
    wins = [tr for tr in trades if tr['pnl_usd'] > 0]
    losses = [tr for tr in trades if tr['pnl_usd'] <= 0]
    wr = len(wins) / len(trades) * 100.0 if trades else 0
    tot_p = sum(tr['pnl_usd'] for tr in wins)
    tot_l = abs(sum(tr['pnl_usd'] for tr in losses)) if losses else 0.001
    pf = tot_p / tot_l
    return balance, wr, pf, max_dd, len(trades), trades

print("=== OPTIMIZING CAPITAL VELOCITY FOR $200 CHALLENGE ===")
results = []
for th in [2, 3, 4, 6]:
    for sl in [1.5, 2.0, 2.5]:
        for vv in [0.08, 0.10, 0.12]:
            for rv in [1.4, 1.8, 2.2]:
                bal, wr, pf, dd, num_t, trs = run_challenge(timeout_h=th, sl_pct=sl, min_v_vel=vv, min_rvol=rv)
                results.append((bal, wr, pf, dd, num_t, th, sl, vv, rv))

results.sort(key=lambda x: x[0], reverse=True)
for r in results[:10]:
    print(f"Final: ${r[0]:.2f} (+{r[0]-100:.1f}%) | WR: {r[1]:.1f}% | PF: {r[2]:.2f} | MaxDD: {r[3]:.1f}% | Trades: {r[4]} | Timeout:{r[5]}h SL:{r[6]}% V-Vel:{r[7]} RVOL:{r[8]}")
