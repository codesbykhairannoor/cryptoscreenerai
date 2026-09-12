import sys
sys.path.append('.')
if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

import pickle
import numpy as np

from backend.scratch.maximize_returns import coins_data, NUM_CANDLES, FEE

def run_detailed():
    balance = 100.00
    peak_balance = 100.00
    max_dd = 0.0
    pos = None
    trades = []
    
    # Best params: MaxChg:32.0% RV:1.8 VV:0.12 | BE:4.0% | L1:7.0%->7.0% | TO:4h SL:2.5%
    max_chg = 32.0
    min_rvol = 1.8
    min_v_vel = 0.12
    min_cmo = 30
    be_trig = 4.0
    be_lock = 0.4
    l1_trig = 7.0
    l1_lock = 7.0
    to_candles = 16 # 4 hours
    sl_pct = 2.5
    
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
                trades.append({
                    't': t,
                    'coin': pos['coin_idx'],
                    'hold': (t - pos['entry_t']) * 0.25,
                    'pnl': pnl,
                    'pct': (exit_p - ent)/ent*100,
                    'peak_pct': peak_pct,
                    'reason': reason,
                    'bal': balance
                })
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
                pos = {'coin_idx': best_c, 'entry': ent, 'entry_t': t, 'size': balance * 0.98, 'peak': ent, 'sl': ent * (1.0 - sl_pct / 100.0)}
                
    wins = [tr for tr in trades if tr['pnl'] > 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    tot_w = sum(tr['pnl'] for tr in wins)
    tot_l = abs(sum(tr['pnl'] for tr in trades if tr['pnl'] <= 0)) if trades else 0.001
    pf = tot_w / tot_l if tot_l > 0 else 0
    return balance, wr, pf, max_dd, len(trades), trades

bal, wr, pf, dd, nt, trs = run_detailed()
print(f"=== FULL AUDIT LOG: START $100.00 -> FINAL ${bal:.2f} (+{bal-100:.2f}%) ===")
print(f"Trades: {nt} | Win Rate: {wr:.1f}% | Profit Factor: {pf:.2f} | Max DD: {dd:.1f}%\n")
print(f"{'#':<3} | {'Coin':<7} | {'Hold':<5} | {'Peak%':<7} | {'Gain%':<7} | {'PnL $':<8} | {'Balance $':<9} | {'Exit Reason':<12}")
print("-" * 75)
for i, tr in enumerate(trs):
    flag = "WIN " if tr['pnl'] > 0 else "LOSS"
    print(f"{i+1:<3} | Coin_{tr['coin']:<2} | {tr['hold']:3.1f}h | {tr['peak_pct']:+5.1f}% | {tr['pct']:+5.1f}% | ${tr['pnl']:+6.2f} | ${tr['bal']:<8.2f} | [{flag}] {tr['reason']}")
