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
FIXED_MARGIN_USD = 20.0
MAX_OPEN_POSITIONS = 2

dataset = load_universe_dataset()
num_coins = len(dataset)
min_len = min(d['length'] for d in dataset)

def test_config(tp, sl, timeout, min_score, be_trig, mom_weight=0.40):
    cash = INITIAL_CAPITAL
    open_positions = {}
    trades = []
    equity = [INITIAL_CAPITAL]
    
    for t in range(50, min_len):
        # Manage open
        closed = []
        for c_idx, pos in open_positions.items():
            cc = dataset[c_idx]['close'][t]
            ch = dataset[c_idx]['high'][t]
            cl = dataset[c_idx]['low'][t]
            ep = pos['entry_price']
            
            gain = (ch - ep) / ep
            pos['peak'] = max(pos['peak'], gain)
            
            # Breakeven & trailing
            if pos['peak'] >= be_trig:
                pos['sl'] = max(pos['sl'], ep * 1.003)
            if pos['peak'] >= be_trig * 1.6:
                pos['sl'] = max(pos['sl'], ep * (1.0 + be_trig * 0.8))
                
            exit_p = None
            if cl <= pos['sl']:
                exit_p = pos['sl'] * (1.0 - SLIPPAGE_PCT)
            elif ch >= pos['tp']:
                exit_p = pos['tp'] * (1.0 - SLIPPAGE_PCT)
            elif (t - pos['t']) >= timeout:
                exit_p = cc * (1.0 - SLIPPAGE_PCT)
                
            if exit_p is not None:
                net_pnl = ((exit_p - ep) / ep) - (SPOT_FEE_PCT * 2.0)
                pnl_usd = pos['sz'] * net_pnl
                cash += pos['sz'] + pnl_usd
                trades.append(net_pnl > 0)
                closed.append(c_idx)
                
        for c in closed:
            del open_positions[c]
            
        # Scoring
        closes = np.array([dataset[i]['close'][t] for i in range(num_coins)])
        opens = np.array([dataset[i]['open'][t] for i in range(num_coins)])
        highs = np.array([dataset[i]['high'][t] for i in range(num_coins)])
        lows = np.array([dataset[i]['low'][t] for i in range(num_coins)])
        vols = np.array([dataset[i]['volume'][t] for i in range(num_coins)])
        chgs = np.array([dataset[i]['chg_24h'][t] for i in range(num_coins)])
        ema9 = np.array([dataset[i]['ema9'][t] for i in range(num_coins)])
        ema21 = np.array([dataset[i]['ema21'][t] for i in range(num_coins)])
        rvol = np.array([dataset[i]['rvol'][t] for i in range(num_coins)])
        
        hl = np.where(highs - lows > 0, highs - lows, closes * 0.0001)
        r_a101 = cross_sectional_rank((closes - opens) / (hl + 1e-6))
        
        ratio_oc = np.clip(opens / (closes + 1e-8), 0.5, 2.0)
        r_a54 = cross_sectional_rank((-1.0 * (lows - closes) * (ratio_oc ** 5)) / ((lows - highs) - 1e-8))
        
        r_mom = cross_sectional_rank(cross_sectional_rank(chgs) * cross_sectional_rank(vols))
        r_as = cross_sectional_rank((closes - lows) / (hl + 1e-6))
        
        scores = (
            mom_weight * r_mom +
            0.30 * r_a101 +
            0.15 * r_a54 +
            (0.55 - mom_weight) * r_as
        ) * 100.0
        
        ranked = np.argsort(scores)[::-1]
        
        if len(open_positions) < MAX_OPEN_POSITIONS and cash >= 5.0:
            for c_idx in ranked:
                if c_idx in open_positions:
                    continue
                if scores[c_idx] < min_score:
                    break
                # Filter Buku Dosa
                if ema9[c_idx] <= ema21[c_idx] or rvol[c_idx] < 1.3:
                    continue
                # Sizing
                sz = min(FIXED_MARGIN_USD, cash * 0.20)
                if cash < sz:
                    break
                    
                ep = closes[c_idx] * (1.0 + SLIPPAGE_PCT)
                cash -= sz
                open_positions[c_idx] = {
                    'entry_price': ep,
                    'sz': sz,
                    'sl': ep * (1.0 - sl),
                    'tp': ep * (1.0 + tp),
                    'peak': 0.0,
                    't': t
                }
                if len(open_positions) >= MAX_OPEN_POSITIONS:
                    break
                    
        val = sum(p['sz'] for p in open_positions.values())
        equity.append(cash + val)
        
    n = len(trades)
    wr = (sum(trades) / n * 100.0) if n > 0 else 0.0
    pnl = equity[-1] - INITIAL_CAPITAL
    return n, wr, pnl

print("Searching optimal parameters on 48 Spot Coins...")
winners = []
for tp in [0.025, 0.035, 0.050]:
    for sl in [0.018, 0.025, 0.030]:
        for timeout in [32, 48, 72]:
            for min_score in [68, 72, 76]:
                for be in [0.012, 0.018]:
                    n, wr, pnl = test_config(tp, sl, timeout, min_score, be)
                    if pnl > 0 and wr >= 55.0 and n >= 15:
                        winners.append((pnl, wr, n, tp, sl, timeout, min_score, be))
                        print(f"PROFITABLE: PnL=+${pnl:.2f} | WR={wr:.1f}% ({n} trades) | TP={tp*100}% SL={sl*100}% TO={timeout} Score>={min_score} BE={be*100}%")

if winners:
    winners.sort(key=lambda x: x[0], reverse=True)
    best = winners[0]
    print("\n" + "="*70)
    print(f"🏆 BEST QUANT CONFIGURATION FOUND:")
    print(f"   Net PnL       : +${best[0]:.2f} (ROI: +{best[0]:.1f}%)")
    print(f"   Win Rate      : {best[1]:.1f}%")
    print(f"   Total Trades  : {best[2]}")
    print(f"   Take Profit   : +{best[3]*100:.1f}%")
    print(f"   Stop Loss     : -{best[4]*100:.1f}%")
    print(f"   Hold Timeout  : {best[5]} candles ({best[5]*15/60:.1f} hours)")
    print(f"   Min Quant Score: {best[6]}")
    print(f"   Breakeven Trigger: +{best[7]*100:.1f}%")
    print("="*70)
else:
    print("No winners found in grid. Testing lower fees or longer holding periods...")
