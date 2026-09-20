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
MAX_OPEN_POSITIONS = 3

dataset = load_universe_dataset()
num_coins = len(dataset)
min_len = min(d['length'] for d in dataset)

print(f"Loaded {num_coins} coins, minimum length = {min_len} candles.")

def run_simulation(exit_mode='trend_exhaustion', tp_pct=0.04, sl_pct=0.025, min_score=70.0, mom_weight=0.40):
    cash = INITIAL_CAPITAL
    open_positions = {}
    trades = []
    equity = [INITIAL_CAPITAL]
    
    # Statistics
    wins = 0
    losses = 0
    pnl_list = []
    exit_reasons = {}

    for t in range(50, min_len):
        # 1. Precalculate Cross-Sectional Alpha for candle t
        closes = np.array([dataset[i]['close'][t] for i in range(num_coins)])
        opens = np.array([dataset[i]['open'][t] for i in range(num_coins)])
        highs = np.array([dataset[i]['high'][t] for i in range(num_coins)])
        lows = np.array([dataset[i]['low'][t] for i in range(num_coins)])
        vols = np.array([dataset[i]['volume'][t] for i in range(num_coins)])
        chgs = np.array([dataset[i]['chg_24h'][t] for i in range(num_coins)])
        ema9 = np.array([dataset[i]['ema9'][t] for i in range(num_coins)])
        ema21 = np.array([dataset[i]['ema21'][t] for i in range(num_coins)])
        rvol = np.array([dataset[i]['rvol'][t] for i in range(num_coins)])
        
        # WorldQuant Alpha#101: (close - open) / ((high - low) + 0.001)
        hl = np.where(highs - lows > 0, highs - lows, closes * 0.0001)
        r_a101 = cross_sectional_rank((closes - opens) / (hl + 1e-6))
        
        # WorldQuant Alpha#54: (-1 * (low - close) * (open^5)) / ((low - high) * (close^5))
        ratio_oc = np.clip(opens / (closes + 1e-8), 0.5, 2.0)
        r_a54 = cross_sectional_rank((-1.0 * (lows - closes) * (ratio_oc ** 5)) / ((lows - highs) - 1e-8))
        
        # Cross-Sectional Momentum (Jegadeesh & Titman): Rank(Rank(Return) * Rank(Volume))
        r_mom = cross_sectional_rank(cross_sectional_rank(chgs) * cross_sectional_rank(vols))
        
        # Microstructure Skew (Avellaneda-Stoikov): (close - low) / (high - low)
        r_as = cross_sectional_rank((closes - lows) / (hl + 1e-6))
        
        # Institutional Multi-Factor Alpha Score
        scores = (
            mom_weight * r_mom +
            0.30 * r_a101 +
            0.15 * r_a54 +
            (0.55 - mom_weight) * r_as
        ) * 100.0
        
        # 2. Check and Manage Open Positions
        closed_indices = []
        for c_idx, pos in open_positions.items():
            cc = closes[c_idx]
            ch = highs[c_idx]
            cl = lows[c_idx]
            ep = pos['entry_price']
            
            gain = (ch - ep) / ep
            pos['peak'] = max(pos['peak'], gain)
            
            # Trailing Profit Lock:
            # If peak >= 1.5%, move stop to breakeven + 0.3% (covers fees)
            if pos['peak'] >= 0.015:
                pos['sl'] = max(pos['sl'], ep * 1.003)
            # If peak >= 2.5%, lock 1.2%
            if pos['peak'] >= 0.025:
                pos['sl'] = max(pos['sl'], ep * 1.012)
            # If peak >= 4.0%, lock 2.5%
            if pos['peak'] >= 0.040:
                pos['sl'] = max(pos['sl'], ep * 1.025)

            exit_price = None
            reason = None
            
            # Check Hard Stop Loss or Trailing Stop
            if cl <= pos['sl']:
                exit_price = pos['sl'] * (1.0 - SLIPPAGE_PCT)
                reason = "STOP_LOSS / TRAILING_LOCK"
            # Check Take Profit
            elif ch >= pos['tp']:
                exit_price = pos['tp'] * (1.0 - SLIPPAGE_PCT)
                reason = "TAKE_PROFIT"
            else:
                # Dynamic Quant Exit logic
                if exit_mode == 'trend_exhaustion':
                    # Exit when momentum trend breaks: EMA9 crosses below EMA21
                    if ema9[c_idx] < ema21[c_idx] and (t - pos['t']) >= 4: # at least 1 hour hold
                        exit_price = cc * (1.0 - SLIPPAGE_PCT)
                        reason = "TREND_EXHAUSTION_EMA_CROSS"
                elif exit_mode == 'rank_decay':
                    # Exit when Alpha Rank drops below 50th percentile
                    if scores[c_idx] < 50.0 and (t - pos['t']) >= 4:
                        exit_price = cc * (1.0 - SLIPPAGE_PCT)
                        reason = "ALPHA_RANK_DECAY"
                elif exit_mode == 'fixed_timeout':
                    if (t - pos['t']) >= 32: # 8 hours
                        exit_price = cc * (1.0 - SLIPPAGE_PCT)
                        reason = "TIMEOUT_8H"

            if exit_price is not None:
                # Net PnL after 0.20% round trip fees
                pct_return = ((exit_price - ep) / ep) - (SPOT_FEE_PCT * 2.0)
                pnl_usd = pos['sz'] * pct_return
                cash += pos['sz'] + pnl_usd
                
                trades.append(pct_return)
                pnl_list.append(pnl_usd)
                if pct_return > 0:
                    wins += 1
                else:
                    losses += 1
                exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
                closed_indices.append(c_idx)

        for c in closed_indices:
            del open_positions[c]

        # 3. New Position Entries
        if len(open_positions) < MAX_OPEN_POSITIONS and cash >= 5.0:
            ranked_indices = np.argsort(scores)[::-1]
            for c_idx in ranked_indices:
                if c_idx in open_positions:
                    continue
                if scores[c_idx] < min_score:
                    break  # rest are below threshold
                
                # Institutional Filters (Buku Dosa Compliance):
                # 1. Trend confirmation (EMA9 > EMA21)
                if ema9[c_idx] <= ema21[c_idx]:
                    continue
                # 2. Relative Volume confirmation (RVOL >= 1.3)
                if rvol[c_idx] < 1.3:
                    continue

                # Sizing: 20% of cash or FIXED_MARGIN_USD, minimum $5
                avail_size = min(FIXED_MARGIN_USD, cash * 0.20)
                if cash < avail_size or avail_size < 5.0:
                    break

                ep = closes[c_idx] * (1.0 + SLIPPAGE_PCT)
                cash -= avail_size
                open_positions[c_idx] = {
                    'symbol': dataset[c_idx]['symbol'],
                    'entry_price': ep,
                    'sz': avail_size,
                    'sl': ep * (1.0 - sl_pct),
                    'tp': ep * (1.0 + tp_pct),
                    'peak': 0.0,
                    't': t
                }
                if len(open_positions) >= MAX_OPEN_POSITIONS:
                    break

        curr_equity = cash + sum(p['sz'] for p in open_positions.values())
        equity.append(curr_equity)

    total_trades = wins + losses
    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
    net_pnl = equity[-1] - INITIAL_CAPITAL
    profit_factor = 0.0
    gross_win = sum(p for p in pnl_list if p > 0)
    gross_loss = abs(sum(p for p in pnl_list if p < 0))
    if gross_loss > 0:
        profit_factor = gross_win / gross_loss

    return {
        'exit_mode': exit_mode,
        'trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'net_pnl': net_pnl,
        'roi_pct': (net_pnl / INITIAL_CAPITAL) * 100.0,
        'profit_factor': profit_factor,
        'final_equity': equity[-1],
        'exit_reasons': exit_reasons
    }

print("\n" + "="*80)
print("TESTING DIFFERENT INSTITUTIONAL QUANT EXIT MECHANISMS")
print("="*80)

for mode in ['trend_exhaustion', 'rank_decay', 'fixed_timeout']:
    for min_s in [65.0, 70.0, 75.0]:
        for tp in [0.035, 0.05, 0.07]:
            for sl in [0.02, 0.025]:
                res = run_simulation(exit_mode=mode, tp_pct=tp, sl_pct=sl, min_score=min_s)
                if res['trades'] >= 10:
                    print(f"Mode={mode:18} | MinScore={min_s:2.0f} | TP={tp*100:3.1f}% | SL={sl*100:3.1f}% | "
                          f"Trades={res['trades']:3d} | WR={res['win_rate']:5.1f}% | PF={res['profit_factor']:4.2f} | "
                          f"PnL=${res['net_pnl']:+6.2f} ({res['roi_pct']:+5.1f}%)")
