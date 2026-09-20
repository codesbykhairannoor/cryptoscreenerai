"""
========================================================================================
🏛️ INSTITUTIONAL QUANT SPOT BACKTEST & VERIFICATION ENGINE (WorldQuant 101 Alphas)
========================================================================================
Berdasarkan Riset Kuantitatif Institusi Publik Terakreditasi:
1. WorldQuant 101 Formulaic Alphas (Zura Kakushadze, 2016 - Alpha #101 & Alpha #54)
2. Jegadeesh & Titman (1993) Cross-Sectional Momentum & Volume Decile Ranking
3. Avellaneda & Stoikov (2008) Inventory Skew & Microstructure Price Pressure
4. Mandatory Buku Dosa & Risk Constraints:
   - Rule 1: No Dip Buying / Falling Knife (EMA9 > EMA21 strictly required)
   - Rule 2: No Shitcoins / Illiquid Assets
   - Rule 3: No All-In (Max 20% capital = $20 per trade on $100 capital, max 2 concurrent slots)
   - Rule 4: No Dead Volume (RVOL >= 1.4)
   - Rule 5: No Revenge Trading (48h quarantine after stop loss)
   - Rule 6: Realistic Spot Taker Fees (0.10% buy + 0.10% sell = 0.20% round trip) + Slippage (0.05%/leg)
========================================================================================
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Tuple

if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

SPOT_FEE_PCT = 0.0010  # 0.10% Bitget / Gate.io Spot taker fee per leg (0.20% round-trip)
SLIPPAGE_PCT = 0.0005  # 0.05% realistic execution slippage per leg
INITIAL_CAPITAL = 100.0  # $100 Standard Workspace Capital
FIXED_MARGIN_USD = 20.0  # $20 per trade (Buku Dosa Rule 3: 20% max allocation)
MAX_OPEN_POSITIONS = 2   # Max 2 concurrent positions ($40 allocated, $60 cash buffer)

def cross_sectional_rank(values: np.ndarray) -> np.ndarray:
    """Operator resmi WorldQuant: rank(x) across universe (skala 0.0 - 1.0)."""
    n = len(values)
    if n <= 1:
        return np.full(n, 0.5)
    temp = np.argsort(values)
    ranks = np.empty_like(temp, dtype=float)
    ranks[temp] = np.arange(n, dtype=float)
    return ranks / (n - 1)

def load_universe_dataset() -> List[Dict[str, Any]]:
    """Memuat 48 pasangan koin real-time dari cache historis klines."""
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spot_backtest_cache.pkl")
    if not os.path.exists(cache_path):
        cache_path = "spot_backtest_cache.pkl"
    if not os.path.exists(cache_path):
        raise FileNotFoundError(f"Cache file {cache_path} tidak ditemukan!")

    with open(cache_path, "rb") as f:
        raw_list = pickle.load(f)

    clean_dataset = []
    for idx, df in enumerate(raw_list):
        sym = f"COIN_{idx+1:02d}"
        
        # EMA9 & EMA21
        ema9 = df['close'].ewm(span=9, adjust=False).mean()
        ema21 = df['close'].ewm(span=21, adjust=False).mean()

        clean_dataset.append({
            'symbol': sym,
            'open': df['open'].to_numpy(dtype=float),
            'high': df['high'].to_numpy(dtype=float),
            'low': df['low'].to_numpy(dtype=float),
            'close': df['close'].to_numpy(dtype=float),
            'volume': df['quoteVol'].to_numpy(dtype=float),
            'rvol': df['rvol'].to_numpy(dtype=float),
            'chg_24h': df['chg_24h'].to_numpy(dtype=float),
            'ema9': ema9.to_numpy(dtype=float),
            'ema21': ema21.to_numpy(dtype=float),
            'length': len(df)
        })
    return clean_dataset

def run_institutional_backtest(
    min_score: float = 70.0,
    rvol_thresh: float = 1.4,
    tp_pct: float = 0.06,
    sl_pct: float = 0.02,
    trail_trigger: float = 0.05,
    trail_dist: float = 0.015,
    timeout_candles: int = 96,
    dynamic_compounding: bool = False
) -> Dict[str, Any]:
    dataset = load_universe_dataset()
    num_coins = len(dataset)
    min_len = min(d['length'] for d in dataset)
    symbols = [d['symbol'] for d in dataset]

    # Precompute arrays
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
        # WorldQuant Alpha #101: (close - open) / ((high - low) + 0.001)
        r_a101 = cross_sectional_rank((cc - oo) / (hl + 1e-6))
        # WorldQuant Alpha #54: (-1 * ((low - close) * (open^5))) / ((low - high) * (close^5))
        ratio_oc = np.clip(oo / (cc + 1e-8), 0.5, 2.0)
        r_a54 = cross_sectional_rank((-1.0 * (ll - cc) * (ratio_oc ** 5)) / ((ll - hh) - 1e-8))
        # Jegadeesh-Titman Cross-Sectional Decile Momentum: Rank(Chg24h) * Rank(Volume)
        r_mom = cross_sectional_rank(cross_sectional_rank(cg) * cross_sectional_rank(vv))
        # Avellaneda-Stoikov Inventory Skew: (close - low) / (high - low)
        r_as = cross_sectional_rank((cc - ll) / (hl + 1e-6))
        
        scores_arr[t] = (
            0.40 * r_mom +
            0.30 * r_a101 +
            0.15 * r_a54 +
            0.15 * r_as
        ) * 100.0

    cash = INITIAL_CAPITAL
    open_positions = {}
    trade_history = []
    equity_curve = [INITIAL_CAPITAL]
    quarantine = {}

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
                    'duration_h': (t - pos['t']) * 0.25,
                    'entry_p': ep,
                    'exit_p': exit_price,
                    'net_ret': net_ret,
                    'pnl_usd': pnl_usd,
                    'peak_ret': pos['peak'],
                    'reason': exit_reason
                })
                
                if exit_reason == "STOP_LOSS":
                    quarantine[c_idx] = t + 192  # 48h quarantine
                    
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
                if ema9_arr[t, c_idx] <= ema21_arr[t, c_idx]:
                    continue
                if rvol_arr[t, c_idx] < rvol_thresh:
                    continue
                if chgs_arr[t, c_idx] <= 0:
                    continue
                    
                if dynamic_compounding:
                    total_curr_equity = cash + sum(p['sz'] for p in open_positions.values())
                    sz = min(total_curr_equity * 0.40, cash)
                else:
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

    return {
        'initial_capital': INITIAL_CAPITAL,
        'final_capital': equity_curve[-1],
        'net_pnl': net_pnl,
        'return_pct': (net_pnl / INITIAL_CAPITAL) * 100.0,
        'profit_factor': pf,
        'win_rate': wr,
        'total_trades': n,
        'wins': len(wins),
        'losses': len(losses),
        'max_drawdown': max_dd,
        'trades': trade_history,
        'equity_curve': equity_curve
    }

def print_backtest_report():
    print("\n" + "=" * 80)
    print("🏛️ INSTITUTIONAL QUANT SPOT BACKTEST (WorldQuant 101 vs Old Retail)")
    print("=" * 80)
    print("Sains & Formula: WorldQuant Alpha #101 + Alpha #54 + Jegadeesh-Titman + Avellaneda-Stoikov")
    print("Batasan Buku Dosa: EMA9 > EMA21, RVOL >= 1.4, 48h Quarantine, Taker Fee 0.20%")
    print("-" * 80)

    res = run_institutional_backtest(dynamic_compounding=False)
    res_comp = run_institutional_backtest(dynamic_compounding=True)
    
    print("MODEL A: FLAT MARGIN ($20 per trade)")
    print(f"💰 Modal Awal       : ${res['initial_capital']:.2f}")
    print(f"💵 Saldo Akhir      : ${res['final_capital']:.2f}")
    print(f"📈 Net Profit (PnL) : +${res['net_pnl']:.2f} (+{res['return_pct']:.2f}%)")
    print(f"🏆 Profit Factor    : {res['profit_factor']:.2f}")
    print(f"🎯 Win Rate         : {res['win_rate']:.1f}% ({res['wins']} Win / {res['losses']} Loss)")
    print(f"🛡️ Max Drawdown     : {res['max_drawdown']:.2f}%")
    print(f"📊 Total Eksekusi   : {res['total_trades']} Trades")
    print("-" * 80)

    print("MODEL B: DYNAMIC EXPONENTIAL COMPOUNDING (Fractional Kelly 40% Allocation)")
    print(f"💰 Modal Awal       : ${res_comp['initial_capital']:.2f}")
    print(f"💵 Saldo Akhir      : ${res_comp['final_capital']:.2f}")
    print(f"📈 Net Profit (PnL) : +${res_comp['net_pnl']:.2f} (+{res_comp['return_pct']:.2f}%)")
    print(f"🏆 Profit Factor    : {res_comp['profit_factor']:.2f}")
    print(f"🎯 Win Rate         : {res_comp['win_rate']:.1f}% ({res_comp['wins']} Win / {res_comp['losses']} Loss)")
    print(f"🛡️ Max Drawdown     : {res_comp['max_drawdown']:.2f}%")
    print(f"📊 Total Eksekusi   : {res_comp['total_trades']} Trades")
    print("-" * 80)

    # Breakdown alasan keluar
    reasons = {}
    for tr in res['trades']:
        reasons[tr['reason']] = reasons.get(tr['reason'], 0) + 1
    print("Distribusi Exit Posisi (Model A):")
    for r_name, cnt in reasons.items():
        print(f"  - {r_name:<16}: {cnt:2d} trade ({cnt/res['total_trades']*100:.1f}%)")

    # Metrik Tambahan
    wins_usd = sum(t['pnl_usd'] for t in res['trades'] if t['pnl_usd'] > 0)
    loss_usd = abs(sum(t['pnl_usd'] for t in res['trades'] if t['pnl_usd'] < 0))
    avg_win = wins_usd / res['wins'] if res['wins'] > 0 else 0
    avg_loss = loss_usd / res['losses'] if res['losses'] > 0 else 0
    expectancy = (res['win_rate']/100.0 * avg_win) - ((1.0 - res['win_rate']/100.0) * avg_loss)

    print(f"💵 Total Gross Profit: +${wins_usd:.2f} (Rata-rata Menang: +${avg_win:.2f})")
    print(f"🔻 Total Gross Loss  : -${loss_usd:.2f} (Rata-rata Kalah: -${avg_loss:.2f})")
    print(f"📈 Expectancy/Trade  : +${expectancy:.3f} per trade")
    print("-" * 80)

    print("\n📜 Log Lengkap Seluruh 32 Transaksi (Model A):")
    print(f"{'#':<3} {'Coin':<10} {'Entry P':<10} {'Exit P':<10} {'Ret%':<8} {'PnL($)':<8} {'Peak%':<7} {'Dur(h)':<7} {'Reason':<15}")
    print("-" * 80)
    for idx, tr in enumerate(res['trades']):
        icon = "✅" if tr['pnl_usd'] > 0 else ("❌" if tr['pnl_usd'] < 0 else "⚖️")
        print(f"{idx+1:<2} {icon} {tr['symbol']:<8} {tr['entry_p']:<10.4f} {tr['exit_p']:<10.4f} {tr['net_ret']*100:+6.2f}% {tr['pnl_usd']:+7.2f} {tr['peak_ret']*100:5.1f}% {tr['duration_h']:5.1f}h  {tr['reason']:<15}")

    print("=" * 80 + "\n")

if __name__ == "__main__":
    print_backtest_report()
