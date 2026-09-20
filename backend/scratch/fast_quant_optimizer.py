import os
import sys
import pickle
import numpy as np

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from backtest_institutional_quant import load_universe_dataset, cross_sectional_rank

SPOT_FEE_PCT = 0.0010  # 0.1% taker fee per leg
SLIPPAGE_PCT = 0.0005  # 0.05% slippage
INITIAL_CAPITAL = 100.0
FIXED_MARGIN_USD = 20.0
MAX_OPEN_POSITIONS = 2

print("Loading dataset...")
dataset = load_universe_dataset()
num_coins = len(dataset)
min_len = min(d['length'] for d in dataset)
symbols = [d['symbol'] for d in dataset]

print(f"Precomputing 2D tensors for {num_coins} coins, {min_len} candles...")
closes_arr = np.array([dataset[i]['close'][:min_len] for i in range(num_coins)]).T   # (min_len, num_coins)
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

print("Precomputation complete. Running ultra-fast grid simulation...")

def simulate_fast(min_score, rvol_thresh, tp_pct, sl_pct, trail_trigger, trail_dist, timeout_candles, max_pos=2):
    cash = INITIAL_CAPITAL
    open_positions = {}
    trades = []
    pnl_usd_list = []
    equity_curve = [INITIAL_CAPITAL]
    
    for t in range(50, min_len):
        cc = closes_arr[t]
        hh = highs_arr[t]
        ll = lows_arr[t]
        
        # Check exits
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
                # Dynamic lock-in
                locked_sl = ep * (1.0 + max(0.010, pos['peak'] - trail_dist))
                if locked_sl > pos['sl']:
                    pos['sl'] = locked_sl
                    
            exit_price = None
            if c_low <= pos['sl']:
                exit_price = pos['sl'] * (1.0 - SLIPPAGE_PCT)
            elif c_high >= pos['tp']:
                exit_price = pos['tp'] * (1.0 - SLIPPAGE_PCT)
            elif (t - pos['t']) >= timeout_candles:
                exit_price = c_close * (1.0 - SLIPPAGE_PCT)
                
            if exit_price is not None:
                net_ret = ((exit_price - ep) / ep) - (SPOT_FEE_PCT * 2.0)
                pnl_usd = pos['sz'] * net_ret
                cash += pos['sz'] + pnl_usd
                trades.append(net_ret)
                pnl_usd_list.append(pnl_usd)
                closed.append(c_idx)
                
        for c in closed:
            del open_positions[c]
            
        # Entry check
        if len(open_positions) < max_pos and cash >= 5.0:
            sc = scores_arr[t]
            ranked = np.argsort(sc)[::-1]
            for c_idx in ranked:
                if sc[c_idx] < min_score:
                    break
                if c_idx in open_positions:
                    continue
                if ema9_arr[t, c_idx] <= ema21_arr[t, c_idx]:
                    continue
                if rvol_arr[t, c_idx] < rvol_thresh:
                    continue
                if chgs_arr[t, c_idx] <= 0:
                    continue
                    
                sz = min(FIXED_MARGIN_USD, cash * 0.20)
                if cash < sz or sz < 5.0:
                    break
                    
                ep = cc[c_idx] * (1.0 + SLIPPAGE_PCT)
                cash -= sz
                open_positions[c_idx] = {
                    'entry_price': ep,
                    'sz': sz,
                    'sl': ep * (1.0 - sl_pct),
                    'tp': ep * (1.0 + tp_pct),
                    'peak': 0.0,
                    't': t
                }
                if len(open_positions) >= max_pos:
                    break
                    
        curr_val = cash + sum(p['sz'] for p in open_positions.values())
        equity_curve.append(curr_val)
        
    n = len(trades)
    if n < 15:
        return None
    wins = sum(1 for r in trades if r > 0)
    wr = wins / n * 100.0
    net_pnl = equity_curve[-1] - INITIAL_CAPITAL
    gross_win = sum(p for p in pnl_usd_list if p > 0)
    gross_loss = abs(sum(p for p in pnl_usd_list if p < 0))
    pf = (gross_win / gross_loss) if gross_loss > 0 else 999.0
    
    # Max Drawdown
    eq_arr = np.array(equity_curve)
    peaks = np.maximum.accumulate(eq_arr)
    dd = (peaks - eq_arr) / peaks
    max_dd = float(np.max(dd)) * 100.0
    
    return {
        'n': n,
        'wr': wr,
        'pnl': net_pnl,
        'pf': pf,
        'max_dd': max_dd,
        'min_score': min_score,
        'rvol_thresh': rvol_thresh,
        'tp_pct': tp_pct,
        'sl_pct': sl_pct,
        'trail_trigger': trail_trigger,
        'trail_dist': trail_dist,
        'timeout': timeout_candles
    }

results = []
for min_s in [70.0, 75.0, 80.0, 85.0]:
    for rvol_t in [1.2, 1.4, 1.6, 1.8]:
        for tp in [0.04, 0.06, 0.08, 0.12]:
            for sl in [0.020, 0.025, 0.030]:
                for trail_trig in [0.030, 0.040, 0.050]:
                    for trail_d in [0.015, 0.020]:
                        for to in [32, 48, 64, 96]:
                            res = simulate_fast(min_s, rvol_t, tp, sl, trail_trig, trail_d, to)
                            if res and res['pnl'] > 2.0 and res['pf'] > 1.2:
                                results.append(res)

print(f"\nTotal qualifying profitable parameter sets: {len(results)}")

# Sort by PnL descending
results.sort(key=lambda x: x['pnl'], reverse=True)

print("\n=== TOP 15 PROFITABLE CONFIGURATIONS (BY NET PNL) ===")
for r in results[:15]:
    print(f"PnL=+${r['pnl']:5.2f} (+{r['pnl']:.1f}%) | WR={r['wr']:4.1f}% | PF={r['pf']:4.2f} | MaxDD={r['max_dd']:3.1f}% | N={r['n']:2d} trades | "
          f"Score>={r['min_score']} RVOL>={r['rvol_thresh']} TP={r['tp_pct']*100:.1f}% SL={r['sl_pct']*100:.1f}% "
          f"Trig={r['trail_trigger']*100:.1f}% Dist={r['trail_dist']*100:.1f}% TO={r['timeout']}c")

# Sort by Profit Factor
results.sort(key=lambda x: x['pf'], reverse=True)
print("\n=== TOP 10 CONFIGURATIONS (BY PROFIT FACTOR) ===")
for r in results[:10]:
    print(f"PF={r['pf']:4.2f} | PnL=+${r['pnl']:5.2f} | WR={r['wr']:4.1f}% | MaxDD={r['max_dd']:3.1f}% | N={r['n']:2d} trades | "
          f"Score>={r['min_score']} RVOL>={r['rvol_thresh']} TP={r['tp_pct']*100:.1f}% SL={r['sl_pct']*100:.1f}% "
          f"Trig={r['trail_trigger']*100:.1f}% Dist={r['trail_dist']*100:.1f}% TO={r['timeout']}c")
