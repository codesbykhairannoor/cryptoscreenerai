import os
import sys
import pickle
import numpy as np

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from backtest_institutional_quant import load_universe_dataset, cross_sectional_rank

SPOT_FEE_PCT = 0.0010  # 0.1% taker fee per leg (0.2% round trip)
SLIPPAGE_PCT = 0.0005  # 0.05% slippage
INITIAL_CAPITAL = 100.0
FIXED_MARGIN_USD = 20.0
MAX_OPEN_POSITIONS = 2

dataset = load_universe_dataset()
num_coins = len(dataset)
min_len = min(d['length'] for d in dataset)

def run_selective_test(min_score=80.0, rvol_thresh=1.5, tp_pct=0.06, sl_pct=0.025, trail_trigger=0.035, timeout_candles=64):
    cash = INITIAL_CAPITAL
    open_positions = {}
    trades = []
    equity = [INITIAL_CAPITAL]
    pnl_usd_list = []
    
    exit_reasons = {}

    for t in range(50, min_len):
        closes = np.array([dataset[i]['close'][t] for i in range(num_coins)])
        opens = np.array([dataset[i]['open'][t] for i in range(num_coins)])
        highs = np.array([dataset[i]['high'][t] for i in range(num_coins)])
        lows = np.array([dataset[i]['low'][t] for i in range(num_coins)])
        vols = np.array([dataset[i]['volume'][t] for i in range(num_coins)])
        chgs = np.array([dataset[i]['chg_24h'][t] for i in range(num_coins)])
        ema9 = np.array([dataset[i]['ema9'][t] for i in range(num_coins)])
        ema21 = np.array([dataset[i]['ema21'][t] for i in range(num_coins)])
        rvol = np.array([dataset[i]['rvol'][t] for i in range(num_coins)])
        
        # Alphas
        hl = np.where(highs - lows > 0, highs - lows, closes * 0.0001)
        r_a101 = cross_sectional_rank((closes - opens) / (hl + 1e-6))
        ratio_oc = np.clip(opens / (closes + 1e-8), 0.5, 2.0)
        r_a54 = cross_sectional_rank((-1.0 * (lows - closes) * (ratio_oc ** 5)) / ((lows - highs) - 1e-8))
        r_mom = cross_sectional_rank(cross_sectional_rank(chgs) * cross_sectional_rank(vols))
        r_as = cross_sectional_rank((closes - lows) / (hl + 1e-6))
        
        scores = (
            0.40 * r_mom +
            0.30 * r_a101 +
            0.15 * r_a54 +
            0.15 * r_as
        ) * 100.0
        
        # Check existing positions
        closed = []
        for c_idx, pos in open_positions.items():
            cc = closes[c_idx]
            ch = highs[c_idx]
            cl = lows[c_idx]
            ep = pos['entry_price']
            
            gain = (ch - ep) / ep
            pos['peak'] = max(pos['peak'], gain)
            
            # Trailing stop only activates once price reaches trail_trigger (e.g. +3.5%)
            if pos['peak'] >= trail_trigger:
                # Lock in at least 1.5% profit, trailing 1.5% below peak
                pos['sl'] = max(pos['sl'], ep * (1.0 + max(0.015, pos['peak'] - 0.020)))
                
            exit_price = None
            reason = None
            
            if cl <= pos['sl']:
                exit_price = pos['sl'] * (1.0 - SLIPPAGE_PCT)
                reason = "STOP_OR_TRAILING"
            elif ch >= pos['tp']:
                exit_price = pos['tp'] * (1.0 - SLIPPAGE_PCT)
                reason = "TAKE_PROFIT"
            elif (t - pos['t']) >= timeout_candles:
                exit_price = cc * (1.0 - SLIPPAGE_PCT)
                reason = "TIMEOUT"
                
            if exit_price is not None:
                net_ret = ((exit_price - ep) / ep) - (SPOT_FEE_PCT * 2.0)
                pnl_usd = pos['sz'] * net_ret
                cash += pos['sz'] + pnl_usd
                trades.append(net_ret)
                pnl_usd_list.append(pnl_usd)
                exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
                closed.append(c_idx)
                
        for c in closed:
            del open_positions[c]
            
        # Entry logic
        if len(open_positions) < MAX_OPEN_POSITIONS and cash >= 5.0:
            ranked = np.argsort(scores)[::-1]
            for c_idx in ranked:
                if c_idx in open_positions:
                    continue
                if scores[c_idx] < min_score:
                    break
                # Strict institutional volume & trend confirmation
                if ema9[c_idx] <= ema21[c_idx]:
                    continue
                if rvol[c_idx] < rvol_thresh:
                    continue
                if chgs[c_idx] <= 0: # positive 24h momentum only
                    continue
                    
                sz = min(FIXED_MARGIN_USD, cash * 0.20)
                if cash < sz or sz < 5.0:
                    break
                    
                ep = closes[c_idx] * (1.0 + SLIPPAGE_PCT)
                cash -= sz
                open_positions[c_idx] = {
                    'symbol': dataset[c_idx]['symbol'],
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
        equity.append(curr_val)
        
    n = len(trades)
    wins = sum(1 for r in trades if r > 0)
    wr = (wins / n * 100.0) if n > 0 else 0.0
    net_pnl = equity[-1] - INITIAL_CAPITAL
    gross_win = sum(p for p in pnl_usd_list if p > 0)
    gross_loss = abs(sum(p for p in pnl_usd_list if p < 0))
    pf = (gross_win / gross_loss) if gross_loss > 0 else 999.0
    avg_win = (gross_win / wins) if wins > 0 else 0.0
    avg_loss = (gross_loss / (n - wins)) if (n - wins) > 0 else 0.0
    
    return {
        'n': n,
        'wr': wr,
        'pnl': net_pnl,
        'pf': pf,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'exits': exit_reasons
    }

print("Running Selective High-Conviction Quant Grid...")
for min_s in [75.0, 80.0, 85.0]:
    for rvol_t in [1.3, 1.5, 1.8]:
        for tp in [0.04, 0.06, 0.08, 0.10]:
            for sl in [0.02, 0.025, 0.03]:
                for trail in [0.025, 0.035, 0.045]:
                    for to in [32, 48, 64, 96]:
                        res = run_selective_test(min_score=min_s, rvol_thresh=rvol_t, tp_pct=tp, sl_pct=sl, trail_trigger=trail, timeout_candles=to)
                        if res['pnl'] > 0.50 and res['wr'] >= 45.0 and res['n'] >= 10:
                            print(f"✅ PROFITABLE: PnL=+${res['pnl']:.2f} | WR={res['wr']:.1f}% | PF={res['pf']:.2f} | N={res['n']:2d} | "
                                  f"Score>={min_s} RVOL>={rvol_t} TP={tp*100:.1f}% SL={sl*100:.1f}% Trail={trail*100:.1f}% TO={to}c | "
                                  f"AvgWin=${res['avg_win']:.2f} AvgLoss=${res['avg_loss']:.2f}")
