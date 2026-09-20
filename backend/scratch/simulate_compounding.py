import os
import sys
import pickle
import numpy as np

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from backtest_institutional_quant import load_universe_dataset, cross_sectional_rank

SPOT_FEE_PCT = 0.0010
SLIPPAGE_PCT = 0.0005
INITIAL_CAPITAL = 100.0

dataset = load_universe_dataset()
num_coins = len(dataset)
min_len = min(d['length'] for d in dataset)
symbols = [d['symbol'] for d in dataset]

closes_arr = np.array([dataset[i]['close'][:min_len] for i in range(num_coins)]).T
opens_arr = np.array([dataset[i]['open'][:min_len] for i in range(num_coins)]).T
highs_arr = np.array([dataset[i]['high'][:min_len] for i in range(num_coins)]).T
lows_arr = np.array([dataset[i]['low'][:min_len] for i in range(num_coins)]).T
vols_arr = np.array([dataset[i]['volume'][:min_len] for i in range(num_coins)]).T
chgs_arr = np.array([dataset[i]['chg_24h'][:min_len] for i in range(num_coins)]).T
ema9_arr = np.array([dataset[i]['ema9'][:min_len] for i in range(num_coins)]).T
ema21_arr = np.array([dataset[i]['ema21'][:min_len] for i in range(num_coins)]).T
rvol_arr = np.array([dataset[i]['rvol'][:min_len] for i in range(num_coins)]).T

scores_arr = np.zeros((min_len, num_coins), dtype=np.float64)

for t in range(50, min_len):
    cc = closes_arr[t]
    oo = opens_arr[t]
    hh = highs_arr[t]
    ll = lows_arr[t]
    vv = vols_arr[t]
    cg = chgs_arr[t]
    
    hl = np.where(hh - ll > 0, hh - ll, cc * 0.0001)
    r_a101 = cross_sectional_rank((cc - oo) / (hl + 1e-6))
    ratio_oc = np.clip(oo / (cc + 1e-8), 0.5, 2.0)
    r_a54 = cross_sectional_rank((-1.0 * (ll - cc) * (ratio_oc ** 5)) / ((ll - hh) - 1e-8))
    r_mom = cross_sectional_rank(cross_sectional_rank(cg) * cross_sectional_rank(vv))
    r_as = cross_sectional_rank((cc - ll) / (hl + 1e-6))
    
    scores_arr[t] = (
        0.40 * r_mom +
        0.30 * r_a101 +
        0.15 * r_a54 +
        0.15 * r_as
    ) * 100.0

def run_compounding_experiment(allocation_pct, max_positions, trail_trigger=0.05, trail_dist=0.015, sl_pct=0.02):
    cash = INITIAL_CAPITAL
    open_positions = {}
    trades = []
    equity = [INITIAL_CAPITAL]
    quarantine = {}

    for t in range(50, min_len):
        cc = closes_arr[t]
        hh = highs_arr[t]
        ll = lows_arr[t]
        
        # Exits
        closed = []
        for c_idx, pos in open_positions.items():
            c_high = hh[c_idx]
            c_low = ll[c_idx]
            c_close = cc[c_idx]
            ep = pos['entry_price']
            
            gain = (c_high - ep) / ep
            if gain > pos['peak']:
                pos['peak'] = gain
                
            if pos['peak'] >= trail_trigger:
                locked_sl = ep * (1.0 + max(0.010, pos['peak'] - trail_dist))
                if locked_sl > pos['sl']:
                    pos['sl'] = locked_sl
                    
            exit_price = None
            exit_reason = None
            if c_low <= pos['sl']:
                exit_price = pos['sl'] * (1.0 - SLIPPAGE_PCT)
                exit_reason = "TRAILING_STOP" if pos['peak'] >= trail_trigger else "STOP_LOSS"
            elif (t - pos['t']) >= 96:
                exit_price = c_close * (1.0 - SLIPPAGE_PCT)
                exit_reason = "TIMEOUT"
                
            if exit_price is not None:
                net_ret = ((exit_price - ep) / ep) - (SPOT_FEE_PCT * 2.0)
                pnl_usd = pos['sz'] * net_ret
                cash += pos['sz'] + pnl_usd
                trades.append(net_ret)
                if exit_reason == "STOP_LOSS":
                    quarantine[c_idx] = t + 192
                closed.append(c_idx)
                
        for c in closed:
            del open_positions[c]
            
        # Dynamic Compounding Position Sizing:
        total_curr_equity = cash + sum(p['sz'] for p in open_positions.values())
        if len(open_positions) < max_positions and cash >= 5.0:
            sc = scores_arr[t]
            ranked = np.argsort(sc)[::-1]
            for c_idx in ranked:
                if sc[c_idx] < 70.0:
                    break
                if c_idx in open_positions:
                    continue
                if quarantine.get(c_idx, 0) > t:
                    continue
                if ema9_arr[t, c_idx] <= ema21_arr[t, c_idx]:
                    continue
                if rvol_arr[t, c_idx] < 1.4:
                    continue
                if chgs_arr[t, c_idx] <= 0:
                    continue
                    
                # Dynamic Allocation based on growing equity
                sz = min(total_curr_equity * allocation_pct, cash)
                if sz < 5.0:
                    break
                    
                ep = cc[c_idx] * (1.0 + SLIPPAGE_PCT)
                cash -= sz
                open_positions[c_idx] = {
                    'entry_price': ep,
                    'sz': sz,
                    'sl': ep * (1.0 - sl_pct),
                    'peak': 0.0,
                    't': t
                }
                if len(open_positions) >= max_positions:
                    break
                    
        curr_val = cash + sum(p['sz'] for p in open_positions.values())
        equity.append(curr_val)
        
    n = len(trades)
    wins = sum(1 for r in trades if r > 0)
    wr = wins / n * 100.0 if n > 0 else 0.0
    net_pnl = equity[-1] - INITIAL_CAPITAL
    return {
        'alloc': allocation_pct,
        'max_pos': max_positions,
        'final_equity': equity[-1],
        'net_pnl': net_pnl,
        'return_pct': (net_pnl / INITIAL_CAPITAL) * 100.0,
        'n': n,
        'wr': wr
    }

print("Simulating Compounding Levels (from 20% margin up to 90% full-throttle):")
for alloc in [0.20, 0.35, 0.50, 0.80, 0.95]:
    for max_p in [1, 2, 3]:
        r = run_compounding_experiment(alloc, max_p)
        print(f"Alloc={r['alloc']*100:2.0f}% | MaxPos={r['max_pos']} | Final: ${r['final_equity']:6.2f} (+{r['return_pct']:5.1f}%) | N={r['n']:2d} | WR={r['wr']:.1f}%")
