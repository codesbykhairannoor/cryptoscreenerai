import sys
sys.path.append('.')
import pickle
import numpy as np
import pandas as pd

from backend.scratch.test_strat8_clean import coins_data, NUM_CANDLES, FEE

def run_test(be_trig, be_lock, lock1_trig, lock1_val, lock2_trig, lock2_val, timeout_h=6):
    balance = 100.00
    peak_balance = 100.00
    max_dd = 0.0
    pos = None
    trades = []
    timeout_candles = timeout_h * 4
    
    for t in range(50, NUM_CANDLES):
        if pos is not None:
            cd = coins_data[pos['coin_idx']]
            h, l, c = cd['high'][t], cd['low'][t], cd['close'][t]
            ent = pos['entry']
            if h > pos['peak']: pos['peak'] = h
            peak_pct = (pos['peak'] - ent) / ent * 100.0
            
            # Escalator logic
            if peak_pct >= 35.0:
                pos['sl'] = max(pos['sl'], ent * 1.25)
            elif peak_pct >= lock2_trig:
                pos['sl'] = max(pos['sl'], ent * (1.0 + lock2_val / 100.0))
            elif peak_pct >= lock1_trig:
                pos['sl'] = max(pos['sl'], ent * (1.0 + lock1_val / 100.0))
            elif peak_pct >= be_trig:
                pos['sl'] = max(pos['sl'], ent * (1.0 + be_lock / 100.0))
                
            if peak_pct >= 50.0:
                pos['sl'] = max(pos['sl'], pos['peak'] * 0.92)
                
            exit_p = None
            reason = ''
            if l <= pos['sl']:
                exit_p = pos['sl']
                reason = 'ESCALATOR' if pos['sl'] > ent else 'SL'
            elif t - pos['entry_t'] >= timeout_candles:
                exit_p = c
                reason = 'TIMEOUT'
                
            if exit_p is not None:
                cost = pos['size']
                gross = (exit_p / ent) * cost
                fee = (cost * FEE) + (gross * FEE)
                pnl = gross - fee - cost
                balance += pnl
                trades.append({'pnl': pnl, 'pct': (exit_p - ent)/ent*100, 'reason': reason, 'coin': pos['coin_idx']})
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
                if bull and rvol >= 1.8 and v_vel >= 0.12 and cmo >= 35 and 0.5 <= chg <= 18.0:
                    sc = rvol * 10 + cmo + (v_vel * 100)
                    if sc > best_sc:
                        best_sc = sc
                        best_c = idx
            if best_c is not None:
                ent = coins_data[best_c]['close'][t]
                pos = {'coin_idx': best_c, 'entry': ent, 'entry_t': t, 'size': balance, 'peak': ent, 'sl': ent * (1.0 - 0.025)}
                
    wins = [tr for tr in trades if tr['pnl'] > 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    tot_w = sum(tr['pnl'] for tr in wins)
    tot_l = abs(sum(tr['pnl'] for tr in trades if tr['pnl'] <= 0)) if trades else 0.001
    pf = tot_w / tot_l if tot_l > 0 else 0
    return balance, wr, pf, max_dd, len(trades), trades

print("Scanning Escalator tuning parameters...")
grid = []
for be_trig in [3.0, 3.5, 4.0, 4.5, 5.0]:
    for be_lock in [0.4, 0.8, 1.2]:
        for l1_t in [6.0, 7.0, 8.0]:
            for l1_v in [3.0, 4.0, 5.0]:
                for l2_t in [12.0, 15.0, 18.0]:
                    for l2_v in [8.0, 10.0, 12.0]:
                        for to in [6, 8, 12]:
                            b, wr, pf, dd, nt, trs = run_test(be_trig, be_lock, l1_t, l1_v, l2_t, l2_v, timeout_h=to)
                            grid.append((b, wr, pf, dd, nt, be_trig, be_lock, l1_t, l1_v, l2_t, l2_v, to))

grid.sort(key=lambda x: x[0], reverse=True)
print(f"Top 10 Escalator Configurations on Clean Dataset:")
for g in grid[:10]:
    print(f"Final: ${g[0]:.2f} (+{g[0]-100:.1f}%) | WR: {g[1]:.1f}% | PF: {g[2]:.2f} | DD: {g[3]:.1f}% | Tr: {g[4]} | BE_trig:{g[5]}% lock:{g[6]}% | L1:{g[7]}%->{g[8]}% | L2:{g[9]}%->{g[10]}% | TO:{g[11]}h")
