"""
========================================================================================
🔬 DEEP RESEARCH: TURNING SMALL CAPITAL ($100) INTO THOUSANDS ($1,000+)
========================================================================================
Analisis Kuantitatif: Eksperimen Geometric Compounding & Moonshot Runner Escalator
Menggunakan Data Riil 48 Koin Spot Kripto (572 Candle 15m)
Termasuk Fee Bursa Spot Bitget (0.10% buy + 0.10% sell) + Slippage (0.05%/leg)
========================================================================================
"""

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

def simulate_growth_path(
    kelly_fraction=0.45,       # 45% dari total ekuitas per posisi (Fractional Kelly)
    max_positions=2,           # Maks 2 koin jalan bareng
    sl_pct=0.020,              # Hard SL ketat di -2.0%
    trail_trigger=0.040,       # Mulai aktifkan trailing di +4.0%
    trail_dist=0.015,          # Jarak trailing 1.5% di bawah puncak
    escalator_unleash=True,    # Biarkan runner meledak tanpa batas TP atas
    timeout_candles=96,
    reinvest_all=True          # Compounding penuh
):
    cash = INITIAL_CAPITAL
    open_positions = {}
    trade_history = []
    equity_curve = [INITIAL_CAPITAL]
    quarantine = {}

    for t in range(50, min_len):
        cc = closes_arr[t]
        hh = highs_arr[t]
        ll = lows_arr[t]
        
        # Cek Exits
        closed = []
        for c_idx, pos in open_positions.items():
            c_high = hh[c_idx]
            c_low = ll[c_idx]
            c_close = cc[c_idx]
            ep = pos['entry_price']
            
            gain = (c_high - ep) / ep
            if gain > pos['peak']:
                pos['peak'] = gain
                
            # Escalator Moonshot Engine: Trailing dinamis berjenjang
            if escalator_unleash:
                if pos['peak'] >= 0.25:
                    # Super runner (>25% gain) -> Lock 20%, trail 5%
                    pos['sl'] = max(pos['sl'], ep * (1.0 + max(0.18, pos['peak'] - 0.05)))
                elif pos['peak'] >= 0.12:
                    # Expansion (>12% gain) -> Lock 8%, trail 3%
                    pos['sl'] = max(pos['sl'], ep * (1.0 + max(0.08, pos['peak'] - 0.03)))
                elif pos['peak'] >= trail_trigger:
                    # Initial trail trigger
                    pos['sl'] = max(pos['sl'], ep * (1.0 + max(0.010, pos['peak'] - trail_dist)))
            else:
                if pos['peak'] >= trail_trigger:
                    pos['sl'] = max(pos['sl'], ep * (1.0 + max(0.010, pos['peak'] - trail_dist)))
                    
            exit_price = None
            exit_reason = None
            
            if c_low <= pos['sl']:
                exit_price = pos['sl'] * (1.0 - SLIPPAGE_PCT)
                exit_reason = "TRAILING_ESCALATOR" if pos['peak'] >= trail_trigger else "STOP_LOSS"
            elif (t - pos['t']) >= timeout_candles:
                exit_price = c_close * (1.0 - SLIPPAGE_PCT)
                exit_reason = "TIMEOUT"
                
            if exit_price is not None:
                net_ret = ((exit_price - ep) / ep) - (SPOT_FEE_PCT * 2.0)
                pnl_usd = pos['sz'] * net_ret
                cash += pos['sz'] + pnl_usd
                
                trade_history.append({
                    'symbol': symbols[c_idx],
                    'entry_p': ep,
                    'exit_p': exit_price,
                    'net_ret': net_ret,
                    'pnl_usd': pnl_usd,
                    'sz': pos['sz'],
                    'peak_ret': pos['peak'],
                    'duration_h': (t - pos['t']) * 0.25,
                    'reason': exit_reason
                })
                
                if exit_reason == "STOP_LOSS":
                    quarantine[c_idx] = t + 192  # 48h karantina
                    
                closed.append(c_idx)
                
        for c in closed:
            del open_positions[c]
            
        # Entry Sizing: Reinvestasi Eksponensial (Compounding Kelly)
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
                    
                # Sizing dinamis berbanding lurus dengan pertumbuhan modal
                target_sz = total_curr_equity * kelly_fraction if reinvest_all else 20.0
                sz = min(target_sz, cash)
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
        equity_curve.append(curr_val)

    n = len(trade_history)
    wins = [tr for tr in trade_history if tr['pnl_usd'] > 0]
    losses = [tr for tr in trade_history if tr['pnl_usd'] <= 0]
    wr = len(wins) / n * 100.0 if n > 0 else 0.0
    net_pnl = equity_curve[-1] - INITIAL_CAPITAL
    gross_win = sum(w['pnl_usd'] for w in wins)
    gross_loss = abs(sum(l['pnl_usd'] for l in losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else 999.0
    
    eq_arr = np.array(equity_curve)
    peaks = np.maximum.accumulate(eq_arr)
    dd = (peaks - eq_arr) / peaks
    max_dd = float(np.max(dd)) * 100.0

    return {
        'initial': INITIAL_CAPITAL,
        'final': equity_curve[-1],
        'net_pnl': net_pnl,
        'roi_pct': (net_pnl / INITIAL_CAPITAL) * 100.0,
        'pf': pf,
        'wr': wr,
        'max_dd': max_dd,
        'trades': trade_history,
        'equity_curve': equity_curve
    }

print("=" * 80)
print("  UJI EKSPERIMEN: KOMPAUNING KELLY + MOONSHOT ESCALATOR")
print("=" * 80)

# Uji 1: Fixed Sizing ($20 per trade)
r_fixed = simulate_growth_path(reinvest_all=False)
print(f"1. Model Flat Margin ($20 tetap)      : Saldo $100 -> ${r_fixed['final']:6.2f} (+{r_fixed['roi_pct']:5.1f}%) | WR: {r_fixed['wr']:.1f}% | PF: {r_fixed['pf']:.2f} | MaxDD: {r_fixed['max_dd']:.1f}%")

# Uji 2: Moderate Compounding (30% per trade)
r_mod = simulate_growth_path(kelly_fraction=0.30, reinvest_all=True)
print(f"2. Model Moderate Kelly (30% modal)   : Saldo $100 -> ${r_mod['final']:6.2f} (+{r_mod['roi_pct']:5.1f}%) | WR: {r_mod['wr']:.1f}% | PF: {r_mod['pf']:.2f} | MaxDD: {r_mod['max_dd']:.1f}%")

# Uji 3: Aggressive Compounding (45% per trade)
r_agg = simulate_growth_path(kelly_fraction=0.45, reinvest_all=True)
print(f"3. Model Aggressive Kelly (45% modal) : Saldo $100 -> ${r_agg['final']:6.2f} (+{r_agg['roi_pct']:5.1f}%) | WR: {r_agg['wr']:.1f}% | PF: {r_agg['pf']:.2f} | MaxDD: {r_agg['max_dd']:.1f}%")

# Uji 4: Hyper Compounding (80% per trade)
r_hyp = simulate_growth_path(kelly_fraction=0.80, reinvest_all=True)
print(f"4. Model Hyper-Growth (80% modal)     : Saldo $100 -> ${r_hyp['final']:6.2f} (+{r_hyp['roi_pct']:5.1f}%) | WR: {r_hyp['wr']:.1f}% | PF: {r_hyp['pf']:.2f} | MaxDD: {r_hyp['max_dd']:.1f}%")

print("\nDetail Transaksi Model Aggressive (Sampel 10 Teratas):")
for idx, tr in enumerate(r_agg['trades'][:10]):
    print(f"#{idx+1:<2} {tr['symbol']:<8} Size: ${tr['sz']:5.1f} | Ret: {tr['net_ret']*100:+5.2f}% | PnL: ${tr['pnl_usd']:+6.2f} | Reason: {tr['reason']}")
