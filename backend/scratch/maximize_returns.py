import sys
if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass
import pickle
import numpy as np
import pandas as pd

with open('backend/spot_backtest_cache.pkl', 'rb') as f:
    raw_dataset = pickle.load(f)

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

def evaluate_extended(max_chg, min_rvol, min_v_vel, min_cmo, be_trig, be_lock, l1_trig, l1_lock, to_h, sl_pct):
    balance = 100.00
    peak_balance = 100.00
    max_dd = 0.0
    pos = None
    trades = []
    to_candles = to_h * 4
    
    for t in range(50, NUM_CANDLES):
        if pos is not None:
            cd = coins_data[pos['coin_idx']]
            h, l, c = cd['high'][t], cd['low'][t], cd['close'][t]
            ent = pos['entry']
            if h > pos['peak']: pos['peak'] = h
            peak_pct = (pos['peak'] - ent) / ent * 100.0
            
            if peak_pct >= 35.0:
                pos['sl'] = max(pos['sl'], ent * 1.25)
            elif peak_pct >= 18.0:
                pos['sl'] = max(pos['sl'], ent * 1.12)
            elif peak_pct >= l1_trig:
                pos['sl'] = max(pos['sl'], ent * (1.0 + l1_lock / 100.0))
            elif peak_pct >= be_trig:
                pos['sl'] = max(pos['sl'], ent * (1.0 + be_lock / 100.0))
                
            if peak_pct >= 50.0:
                pos['sl'] = max(pos['sl'], pos['peak'] * 0.92)
                
            exit_p = None
            reason = ''
            if l <= pos['sl']:
                exit_p = pos['sl']
                reason = 'ESCALATOR' if pos['sl'] > ent else 'SL'
            elif t - pos['entry_t'] >= to_candles:
                exit_p = c
                reason = 'TIMEOUT'
                
            if exit_p is not None:
                cost = pos['size']
                gross = (exit_p / ent) * cost
                fee = (cost * FEE) + (gross * FEE)
                pnl = gross - fee - cost
                balance += pnl
                trades.append({'pnl': pnl, 'pct': (exit_p - ent)/ent*100, 'reason': reason})
                if balance > peak_balance: peak_balance = balance
                dd = (peak_balance - balance) / peak_balance * 100.0
                if dd > max_dd: max_dd = dd
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
                if bull and rvol >= min_rvol and v_vel >= min_v_vel and cmo >= min_cmo and 0.5 <= chg <= max_chg:
                    sc = rvol * 10 + cmo + (v_vel * 100)
                    if sc > best_sc:
                        best_sc = sc
                        best_c = idx
            if best_c is not None:
                ent = coins_data[best_c]['close'][t]
                pos = {'coin_idx': best_c, 'entry': ent, 'entry_t': t, 'size': balance, 'peak': ent, 'sl': ent * (1.0 - sl_pct / 100.0)}
                
    wins = [tr for tr in trades if tr['pnl'] > 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    tot_w = sum(tr['pnl'] for tr in wins)
    tot_l = abs(sum(tr['pnl'] for tr in trades if tr['pnl'] <= 0)) if trades else 0.001
    pf = tot_w / tot_l if tot_l > 0 else 0
    return balance, wr, pf, max_dd, len(trades)

results = []
for max_chg in [18.0, 25.0, 32.0]:
    for min_rv in [1.4, 1.8]:
        for min_vv in [0.09, 0.12]:
            for be_t in [4.0, 4.5, 5.0]:
                for l1_t in [7.0, 8.0]:
                    for l1_l in [5.5, 7.0]:
                        for to in [4, 6]:
                            bal, wr, pf, dd, nt = evaluate_extended(max_chg, min_rv, min_vv, 30, be_t, 0.4, l1_t, l1_l, to, 2.5)
                            results.append((bal, wr, pf, dd, nt, max_chg, min_rv, min_vv, be_t, l1_t, l1_l, to))

results.sort(key=lambda x: x[0], reverse=True)
print("=== EXTENDED PARAMETER RESULTS ===")
for r in results[:10]:
    print(f"Final: ${r[0]:.2f} (+{r[0]-100:.1f}%) | WR: {r[1]:.1f}% | PF: {r[2]:.2f} | DD: {r[3]:.1f}% | Tr: {r[4]} | MaxChg:{r[5]}% RV:{r[6]} VV:{r[7]} | BE:{r[8]}% | L1:{r[9]}%->{r[10]}% | TO:{r[11]}h")
