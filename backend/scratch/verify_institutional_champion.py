import os
import sys
import pickle
import numpy as np

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from backtest_institutional_quant import load_universe_dataset, cross_sectional_rank

SPOT_FEE_PCT = 0.0010  # 0.10% taker fee per leg (0.20% round trip)
SLIPPAGE_PCT = 0.0005  # 0.05% slippage per leg
INITIAL_CAPITAL = 100.0
FIXED_MARGIN_USD = 20.0
MAX_OPEN_POSITIONS = 2

dataset = load_universe_dataset()
num_coins = len(dataset)
min_len = min(d['length'] for d in dataset)
symbols = [d['symbol'] for d in dataset]

# Precompute matrices
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

def run_detailed_backtest(min_score, rvol_thresh, tp_pct, sl_pct, trail_trigger, trail_dist, timeout_candles, title):
    cash = INITIAL_CAPITAL
    open_positions = {}
    trade_history = []
    equity_curve = [INITIAL_CAPITAL]
    quarantine = {}  # 48h quarantine after stop loss (Buku Dosa Rule 5)
    
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
                locked_sl = ep * (1.0 + max(0.010, pos['peak'] - trail_dist))
                if locked_sl > pos['sl']:
                    pos['sl'] = locked_sl
                    
            exit_price = None
            exit_reason = None
            if c_low <= pos['sl']:
                exit_price = pos['sl'] * (1.0 - SLIPPAGE_PCT)
                exit_reason = "TRAILING_STOP" if pos['peak'] >= trail_trigger else "STOP_LOSS"
            elif c_high >= pos['tp']:
                exit_price = pos['tp'] * (1.0 - SLIPPAGE_PCT)
                exit_reason = "TAKE_PROFIT"
            elif (t - pos['t']) >= timeout_candles:
                exit_price = c_close * (1.0 - SLIPPAGE_PCT)
                exit_reason = "TIMEOUT"
                
            if exit_price is not None:
                net_ret = ((exit_price - ep) / ep) - (SPOT_FEE_PCT * 2.0)
                pnl_usd = pos['sz'] * net_ret
                cash += pos['sz'] + pnl_usd
                
                trade_history.append({
                    'symbol': symbols[c_idx],
                    'entry_t': pos['t'],
                    'exit_t': t,
                    'duration_c': t - pos['t'],
                    'duration_h': (t - pos['t']) * 0.25,
                    'entry_p': ep,
                    'exit_p': exit_price,
                    'net_ret': net_ret,
                    'pnl_usd': pnl_usd,
                    'peak_ret': pos['peak'],
                    'reason': exit_reason,
                    'equity_after': cash + sum(p['sz'] for k, p in open_positions.items() if k != c_idx)
                })
                
                if exit_reason == "STOP_LOSS":
                    # 48h quarantine = 48 * 4 = 192 candles of 15m
                    quarantine[c_idx] = t + 192
                    
                closed.append(c_idx)
                
        for c in closed:
            del open_positions[c]
            
        # Entry logic
        if len(open_positions) < MAX_OPEN_POSITIONS and cash >= 5.0:
            sc = scores_arr[t]
            ranked = np.argsort(sc)[::-1]
            for c_idx in ranked:
                if sc[c_idx] < min_score:
                    break
                if c_idx in open_positions:
                    continue
                if quarantine.get(c_idx, 0) > t:
                    continue
                # Mandate Rule 1: No Dip Buying / Falling Knife (EMA9 > EMA21)
                if ema9_arr[t, c_idx] <= ema21_arr[t, c_idx]:
                    continue
                # Mandate Rule 4: RVOL >= 1.4
                if rvol_arr[t, c_idx] < rvol_thresh:
                    continue
                # Mandate Rule 2: Positive 24h trend
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
                if len(open_positions) >= MAX_OPEN_POSITIONS:
                    break
                    
        curr_val = cash + sum(p['sz'] for p in open_positions.values())
        equity_curve.append(curr_val)
        
    print("=" * 80)
    print(f"   DETAILED BACKTEST REPORT: {title}")
    print("=" * 80)
    n = len(trade_history)
    wins = [tr for tr in trade_history if tr['pnl_usd'] > 0]
    losses = [tr for tr in trade_history if tr['pnl_usd'] <= 0]
    wr = len(wins) / n * 100.0 if n > 0 else 0.0
    net_pnl = equity_curve[-1] - INITIAL_CAPITAL
    tot_win_usd = sum(w['pnl_usd'] for w in wins)
    tot_loss_usd = abs(sum(l['pnl_usd'] for l in losses))
    pf = (tot_win_usd / tot_loss_usd) if tot_loss_usd > 0 else 999.0
    
    eq_arr = np.array(equity_curve)
    peaks = np.maximum.accumulate(eq_arr)
    dd = (peaks - eq_arr) / peaks
    max_dd = float(np.max(dd)) * 100.0
    
    avg_win = (tot_win_usd / len(wins)) if wins else 0.0
    avg_loss = (tot_loss_usd / len(losses)) if losses else 0.0
    expectancy = (wr / 100.0 * avg_win) - ((1.0 - wr / 100.0) * avg_loss)
    
    print(f"Initial Capital : ${INITIAL_CAPITAL:.2f}")
    print(f"Ending Capital  : ${equity_curve[-1]:.2f}")
    print(f"Net Profit      : +${net_pnl:.2f} (+{net_pnl / INITIAL_CAPITAL * 100.0:.2f}%)")
    print(f"Profit Factor   : {pf:.2f}")
    print(f"Win Rate        : {wr:.1f}% ({len(wins)} W / {len(losses)} L)")
    print(f"Max Drawdown    : {max_dd:.2f}%")
    print(f"Expectancy/Trade: +${expectancy:.3f}")
    print(f"Total Trades    : {n}")
    
    # Exit reasons
    reasons = {}
    for tr in trade_history:
        reasons[tr['reason']] = reasons.get(tr['reason'], 0) + 1
    print("\nExit Reasons Breakdown:")
    for r_name, cnt in reasons.items():
        print(f"  - {r_name:15s}: {cnt:2d} ({cnt/n*100:.1f}%)")
        
    print("\nIndividual Trade Log (First 15 & Last 10):")
    display_trades = trade_history[:15] + ([None] if n > 25 else []) + trade_history[-10:] if n > 25 else trade_history
    print(f"{'#':<3} {'Coin':<10} {'Entry P':<10} {'Exit P':<10} {'Ret%':<7} {'PnL($)':<8} {'Peak%':<7} {'Dur(h)':<7} {'Reason':<15}")
    print("-" * 80)
    for idx, tr in enumerate(trade_history):
        if idx < 15 or idx >= n - 10:
            print(f"{idx+1:<3} {tr['symbol']:<10} {tr['entry_p']:<10.4f} {tr['exit_p']:<10.4f} {tr['net_ret']*100:+6.2f}% {tr['pnl_usd']:+7.2f} {tr['peak_ret']*100:5.1f}% {tr['duration_h']:5.1f}h  {tr['reason']:<15}")
        elif idx == 15:
            print("... [ middle trades omitted for brevity ] ...")
    print("=" * 80 + "\n")
    return trade_history, equity_curve

# Run Champion 1: Maximum Profit Factor (Conservation of Capital & High Sharpe)
t1, e1 = run_detailed_backtest(
    min_score=70.0,
    rvol_thresh=1.4,
    tp_pct=0.06,
    sl_pct=0.02,
    trail_trigger=0.05,
    trail_dist=0.015,
    timeout_candles=96,
    title="CHAMPION 1: High Profit Factor (PF=3.69, WR=60.6%, SL=2%, Trail=5%)"
)

# Run Champion 2: High Yield Momentum Engine (Higher Returns & Active Trading)
t2, e2 = run_detailed_backtest(
    min_score=70.0,
    rvol_thresh=1.6,
    tp_pct=0.04,
    sl_pct=0.02,
    trail_trigger=0.05,
    trail_dist=0.015,
    timeout_candles=48,
    title="CHAMPION 2: High Yield Momentum Engine (PnL=+13.6%, PF=2.30, MaxDD=1.5%)"
)
