import sys
sys.path.append('.')
if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

from backend.scratch.maximize_returns import coins_data, NUM_CANDLES, FEE

print("Testing Runner Escalators (Higher TP / Dynamic Trailing)...")

def test_runner_escalator(trail_dist=0.035, min_trigger=0.05, timeout_h=6):
    balance = 100.00
    peak_balance = 100.00
    max_dd = 0.0
    pos = None
    trades = []
    to_candles = timeout_h * 4
    
    for t in range(50, NUM_CANDLES):
        if pos is not None:
            cd = coins_data[pos['coin_idx']]
            h, l, c = cd['high'][t], cd['low'][t], cd['close'][t]
            ent = pos['entry']
            if h > pos['peak']: pos['peak'] = h
            peak_pct = (pos['peak'] - ent) / ent
            
            # Dynamic trailing: once peak >= min_trigger, trail by trail_dist
            if peak_pct >= min_trigger:
                trail_sl = pos['peak'] * (1.0 - trail_dist)
                pos['sl'] = max(pos['sl'], trail_sl)
            elif peak_pct >= 0.035:
                pos['sl'] = max(pos['sl'], ent * 1.004) # Breakeven
                
            exit_p = None
            reason = ''
            if l <= pos['sl']:
                exit_p = pos['sl']
                reason = 'TRAIL' if pos['sl'] > ent else 'SL'
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
                if bull and rvol >= 1.8 and v_vel >= 0.12 and cmo >= 30 and 0.5 <= chg <= 32.0:
                    sc = rvol * 10 + cmo + (v_vel * 100)
                    if sc > best_sc:
                        best_sc = sc
                        best_c = idx
            if best_c is not None:
                ent = coins_data[best_c]['close'][t]
                pos = {'coin_idx': best_c, 'entry': ent, 'entry_t': t, 'size': balance * 0.98, 'peak': ent, 'sl': ent * (1.0 - 0.025)}
                
    wins = [tr for tr in trades if tr['pnl'] > 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    tot_w = sum(tr['pnl'] for tr in wins)
    tot_l = abs(sum(tr['pnl'] for tr in trades if tr['pnl'] <= 0)) if trades else 0.001
    pf = tot_w / tot_l if tot_l > 0 else 0
    return balance, wr, pf, max_dd, len(trades)

for td in [0.02, 0.025, 0.03, 0.035, 0.04, 0.05]:
    for trig in [0.04, 0.06, 0.08, 0.10, 0.12]:
        for to in [4, 6, 8]:
            bal, wr, pf, dd, nt = test_runner_escalator(trail_dist=td, min_trigger=trig, timeout_h=to)
            if bal > 135.0:
                print(f"TrailDist: {td*100:.1f}% | Trigger: {trig*100:.1f}% | TO: {to}h -> Final: ${bal:.2f} (+{bal-100:.1f}%) | WR: {wr:.1f}% | PF: {pf:.2f} | DD: {dd:.1f}% | Tr: {nt}")
