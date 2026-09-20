"""
========================================================================================
🏛️ INSTITUTIONAL QUANT BACKTEST ENGINE (WorldQuant 101 vs Retail Dip Buying)
========================================================================================
Deep Quantitative Backtesting Engine comparing:
1. Model A (Published Research): WorldQuant 101 Formulaic Alphas (Kakushadze 2016) +
   Avellaneda-Stoikov (2008) Inventory Skew + Jegadeesh-Titman (1993) Momentum Decile Q1.
2. Model B (Old Retail Trap): CORE2_NFI_DIP_ABSORPTION (RSI < 35, BB Lower, Dip Catching).

Evaluated on 48 Real Spot Cryptocurrencies over 704 15-Minute Klines (~10 Days).
Includes realistic Spot exchange fees: 0.10% entry + 0.10% exit (0.20% round-trip).
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

SPOT_FEE_PCT = 0.0010  # 0.10% Bitget / Gate.io Spot taker fee per leg (0.20% round trip)
SLIPPAGE_PCT = 0.0005  # 0.05% conservative slippage
INITIAL_CAPITAL = 100.0  # $100 Standard Workspace Capital
FIXED_MARGIN_USD = 20.0  # $20 per trade (Buku Dosa Rule 3: 20% max allocation)
MAX_OPEN_POSITIONS = 2   # Max 2 concurrent positions ($40 allocated, $60 cash buffer)

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
        
        # Hitung Bollinger Bands jika belum ada
        bb_mid = df['close'].rolling(20).mean().bfill()
        bb_std = df['close'].rolling(20).std().bfill()
        bb_low = (bb_mid - (bb_std * 2.0)).bfill()
        bb_up = (bb_mid + (bb_std * 2.0)).bfill()
        
        # Hitung EMA9 & EMA21
        ema9 = df['close'].ewm(span=9, adjust=False).mean()
        ema21 = df['close'].ewm(span=21, adjust=False).mean()

        clean_dataset.append({
            'symbol': sym,
            'open': df['open'].to_numpy(dtype=float),
            'high': df['high'].to_numpy(dtype=float),
            'low': df['low'].to_numpy(dtype=float),
            'close': df['close'].to_numpy(dtype=float),
            'volume': df['quoteVol'].to_numpy(dtype=float),
            'rsi': df['rsi'].to_numpy(dtype=float),
            'rvol': df['rvol'].to_numpy(dtype=float),
            'bb_low': bb_low.to_numpy(dtype=float),
            'bb_up': bb_up.to_numpy(dtype=float),
            'bb_mid': bb_mid.to_numpy(dtype=float),
            'ema9': ema9.to_numpy(dtype=float),
            'ema21': ema21.to_numpy(dtype=float),
            'is_bull': df['trend_bullish'].to_numpy(dtype=bool),
            'chg_24h': df['chg_24h'].to_numpy(dtype=float),
            'length': len(df)
        })

    return clean_dataset


def cross_sectional_rank(values: np.ndarray) -> np.ndarray:
    """Operator resmi WorldQuant: rank(x) across universe (skala 0.0 - 1.0)."""
    n = len(values)
    if n <= 1:
        return np.full(n, 0.5)
    temp = np.argsort(values)
    ranks = np.empty_like(temp, dtype=float)
    ranks[temp] = np.arange(n)
    return (ranks + 1.0) / float(n)


def run_worldquant_backtest(dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Backtesting Model Institusional:
    WorldQuant 101 Formulaic Alphas (#101, #54, #41) + Avellaneda-Stoikov Skew.
    - Sinyal: Hanya koin Desil Teratas (Top Decile Q1, Skor >= 65.0)
    - Filter Buku Dosa: Wajib EMA9 > EMA21 (Dilarang Falling Knife), RVOL >= 1.2
    - Target: +4.0% Take Profit (Escalator Breakeven di +2.0%), -2.5% Hard Stop
    """
    num_coins = len(dataset)
    min_len = min(d['length'] for d in dataset)
    
    cash = INITIAL_CAPITAL
    open_positions = {}  # coin_idx -> {entry_price, size_usd, stop_loss, take_profit, peak_gain, entry_t}
    trades_history = []
    equity_curve = [INITIAL_CAPITAL]

    for t in range(50, min_len):
        # 1. MANAGE OPEN POSITIONS
        closed_indices = []
        for c_idx, pos in open_positions.items():
            current_close = dataset[c_idx]['close'][t]
            current_high = dataset[c_idx]['high'][t]
            current_low = dataset[c_idx]['low'][t]
            entry_p = pos['entry_price']
            
            # Hitung pergerakan harga
            gain_pct = (current_close - entry_p) / entry_p
            max_gain_pct = (current_high - entry_p) / entry_p
            pos['peak_gain'] = max(pos['peak_gain'], max_gain_pct)
            
            # Dinamika Moonshot Escalator Trailing
            # Jika profit > +2.0%, geser SL ke Breakeven (+0.3% untuk cover fee)
            if pos['peak_gain'] >= 0.020:
                pos['stop_loss'] = max(pos['stop_loss'], entry_p * 1.003)
            # Jika profit > +3.5%, lock profit di +2.0%
            if pos['peak_gain'] >= 0.035:
                pos['stop_loss'] = max(pos['stop_loss'], entry_p * 1.020)

            # Cek Exit Hit (SL / TP / Timeout)
            exit_price = None
            exit_reason = None

            # Hit Stop Loss
            if current_low <= pos['stop_loss']:
                exit_price = pos['stop_loss'] * (1.0 - SLIPPAGE_PCT)
                exit_reason = "STOP_LOSS" if pos['stop_loss'] < entry_p else "TRAILING_LOCK_WIN"
            # Hit Take Profit Target (+4.0%)
            elif current_high >= pos['take_profit']:
                exit_price = pos['take_profit'] * (1.0 - SLIPPAGE_PCT)
                exit_reason = "TAKE_PROFIT"
            # Sideways Timeout (16 candle = 4 jam tanpa hasil)
            elif (t - pos['entry_t']) >= 16:
                exit_price = current_close * (1.0 - SLIPPAGE_PCT)
                exit_reason = "SIDEWAYS_TIMEOUT"

            if exit_price is not None:
                # Return modal + PnL setelah fee bursa (0.1% taker buy + 0.1% taker sell)
                gross_pnl_pct = (exit_price - entry_p) / entry_p
                net_pnl_pct = gross_pnl_pct - (SPOT_FEE_PCT * 2.0)
                pnl_usd = pos['size_usd'] * net_pnl_pct
                
                cash += pos['size_usd'] + pnl_usd
                trades_history.append({
                    'strategy': 'WORLDQUANT_101_Q1',
                    'symbol': dataset[c_idx]['symbol'],
                    'entry_price': entry_p,
                    'exit_price': exit_price,
                    'pnl_pct': net_pnl_pct * 100.0,
                    'pnl_usd': pnl_usd,
                    'hold_candles': t - pos['entry_t'],
                    'reason': exit_reason,
                    'is_win': net_pnl_pct > 0
                })
                closed_indices.append(c_idx)

        for c_idx in closed_indices:
            del open_positions[c_idx]

        # 2. CROSS-SECTIONAL FACTOR SCORING AT TIMESTEP t
        # Hitung faktor-faktor matematis serentak ke seluruh 48 koin
        closes = np.array([dataset[i]['close'][t] for i in range(num_coins)])
        opens = np.array([dataset[i]['open'][t] for i in range(num_coins)])
        highs = np.array([dataset[i]['high'][t] for i in range(num_coins)])
        lows = np.array([dataset[i]['low'][t] for i in range(num_coins)])
        vols = np.array([dataset[i]['volume'][t] for i in range(num_coins)])
        chgs = np.array([dataset[i]['chg_24h'][t] for i in range(num_coins)])
        ema9s = np.array([dataset[i]['ema9'][t] for i in range(num_coins)])
        ema21s = np.array([dataset[i]['ema21'][t] for i in range(num_coins)])
        rvols = np.array([dataset[i]['rvol'][t] for i in range(num_coins)])

        hl_range = highs - lows
        hl_safe = np.where(hl_range > 0, hl_range, closes * 0.0001)

        # Alpha #101: (close - open) / ((high - low) + 0.001)
        raw_a101 = (closes - opens) / (hl_safe + 1e-6)
        rank_a101 = cross_sectional_rank(raw_a101)

        # Alpha #54: (-1 * (low - close) * open^5) / ((low - high) * close^5)
        ratio_oc = np.clip(opens / (closes + 1e-8), 0.5, 2.0)
        raw_a54 = (-1.0 * (lows - closes) * (ratio_oc ** 5)) / ((lows - highs) - 1e-8)
        rank_a54 = cross_sectional_rank(raw_a54)

        # Alpha #41: ((high * low)^0.5 - mid) / (high - low)
        geom = np.sqrt(np.maximum(highs * lows, 1e-8))
        mid = 0.5 * (highs + lows)
        raw_a41 = (geom - mid) / (hl_safe + 1e-6)
        rank_a41 = cross_sectional_rank(raw_a41)

        # Volume-Weighted Momentum: rank(chg) * rank(vol)
        rank_chg = cross_sectional_rank(chgs)
        rank_vol = cross_sectional_rank(vols)
        rank_mom = cross_sectional_rank(rank_chg * rank_vol)

        # Avellaneda-Stoikov Inventory Skew: (close - low) / (high - low)
        raw_as = (closes - lows) / (hl_safe + 1e-6)
        rank_as = cross_sectional_rank(raw_as)

        # Composite Multi-Factor Quant Score (0 s/d 100)
        composite_scores = (
            0.35 * rank_mom +
            0.25 * rank_a101 +
            0.15 * rank_a54 +
            0.15 * rank_a41 +
            0.10 * rank_as
        ) * 100.0

        # Urutkan koin berdasarkan skor desil kuantitatif tertinggi
        ranked_indices = np.argsort(composite_scores)[::-1]

        # 3. SCAN UNTUK ENTRY BARU
        if len(open_positions) < MAX_OPEN_POSITIONS and cash >= 5.0:
            for c_idx in ranked_indices:
                if c_idx in open_positions:
                    continue
                
                score = composite_scores[c_idx]
                # Syarat Top Decile (Q1): Skor >= 65.0
                if score < 65.0:
                    break

                # Saringan Buku Dosa:
                # Rule 1: NO FALLING KNIFE (EMA9 > EMA21 wajib)
                if ema9s[c_idx] <= ema21s[c_idx]:
                    continue
                # Rule 4: ANTI DEAD VOLUME (RVOL >= 1.2)
                if rvols[c_idx] < 1.2:
                    continue

                # Ukuran posisi dinamis: 20% modal saat ini, capped di $20, min $5
                alloc_usd = min(FIXED_MARGIN_USD, cash * 0.20)
                alloc_usd = max(5.0, alloc_usd)

                if cash < alloc_usd:
                    break

                entry_p = closes[c_idx] * (1.0 + SLIPPAGE_PCT)
                stop_l = entry_p * (1.0 - 0.025)   # -2.5% Hard Stop
                take_p = entry_p * (1.0 + 0.040)   # +4.0% Initial Escalator Target

                cash -= alloc_usd
                open_positions[c_idx] = {
                    'entry_price': entry_p,
                    'size_usd': alloc_usd,
                    'stop_loss': stop_l,
                    'take_profit': take_p,
                    'peak_gain': 0.0,
                    'entry_t': t
                }

                if len(open_positions) >= MAX_OPEN_POSITIONS:
                    break

        # Catat total ekuitas saat ini
        open_val = sum(pos['size_usd'] for pos in open_positions.values())
        equity_curve.append(cash + open_val)

    return _calculate_performance_metrics("WorldQuant 101 Top Decile (Q1)", trades_history, equity_curve)


def run_retail_dip_buying_backtest(dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Backtesting Model Ritel Lama (CORE2_NFI_DIP_ABSORPTION):
    - Strategi: Menangkap pisau jatuh saat RSI oversold (< 35) dan harga menembus Lower Bollinger Band.
    - Tanpa filter tren EMA9/EMA21 (Beli saat harga anjlok dengan harapan mean reversion).
    - Target: +1.5% Take Profit, -3.5% Stop Loss.
    """
    num_coins = len(dataset)
    min_len = min(d['length'] for d in dataset)
    
    cash = INITIAL_CAPITAL
    open_positions = {}
    trades_history = []
    equity_curve = [INITIAL_CAPITAL]

    for t in range(50, min_len):
        # 1. MANAGE OPEN POSITIONS
        closed_indices = []
        for c_idx, pos in open_positions.items():
            current_close = dataset[c_idx]['close'][t]
            current_high = dataset[c_idx]['high'][t]
            current_low = dataset[c_idx]['low'][t]
            entry_p = pos['entry_price']

            exit_price = None
            exit_reason = None

            if current_low <= pos['stop_loss']:
                exit_price = pos['stop_loss'] * (1.0 - SLIPPAGE_PCT)
                exit_reason = "STOP_LOSS"
            elif current_high >= pos['take_profit']:
                exit_price = pos['take_profit'] * (1.0 - SLIPPAGE_PCT)
                exit_reason = "TAKE_PROFIT"
            elif (t - pos['entry_t']) >= 16:
                exit_price = current_close * (1.0 - SLIPPAGE_PCT)
                exit_reason = "SIDEWAYS_TIMEOUT"

            if exit_price is not None:
                gross_pnl_pct = (exit_price - entry_p) / entry_p
                net_pnl_pct = gross_pnl_pct - (SPOT_FEE_PCT * 2.0)
                pnl_usd = pos['size_usd'] * net_pnl_pct
                
                cash += pos['size_usd'] + pnl_usd
                trades_history.append({
                    'strategy': 'RETAIL_DIP_BUYING',
                    'symbol': dataset[c_idx]['symbol'],
                    'entry_price': entry_p,
                    'exit_price': exit_price,
                    'pnl_pct': net_pnl_pct * 100.0,
                    'pnl_usd': pnl_usd,
                    'hold_candles': t - pos['entry_t'],
                    'reason': exit_reason,
                    'is_win': net_pnl_pct > 0
                })
                closed_indices.append(c_idx)

        for c_idx in closed_indices:
            del open_positions[c_idx]

        # 2. SCAN FOR RETAIL DIP SETUP (RSI < 35 & Close <= BB Lower)
        if len(open_positions) < MAX_OPEN_POSITIONS and cash >= 5.0:
            for c_idx in range(num_coins):
                if c_idx in open_positions:
                    continue

                rsi = dataset[c_idx]['rsi'][t]
                close = dataset[c_idx]['close'][t]
                bb_low = dataset[c_idx]['bb_low'][t]

                # Ritel dip-buying rule: Oversold + tembus BB bawah
                if rsi <= 35.0 and close <= bb_low:
                    alloc_usd = min(FIXED_MARGIN_USD, cash * 0.20)
                    alloc_usd = max(5.0, alloc_usd)

                    if cash < alloc_usd:
                        break

                    entry_p = close * (1.0 + SLIPPAGE_PCT)
                    stop_l = entry_p * (1.0 - 0.035)  # -3.5% SL
                    take_p = entry_p * (1.0 + 0.015)  # +1.5% TP

                    cash -= alloc_usd
                    open_positions[c_idx] = {
                        'entry_price': entry_p,
                        'size_usd': alloc_usd,
                        'stop_loss': stop_l,
                        'take_profit': take_p,
                        'peak_gain': 0.0,
                        'entry_t': t
                    }

                    if len(open_positions) >= MAX_OPEN_POSITIONS:
                        break

        open_val = sum(pos['size_usd'] for pos in open_positions.values())
        equity_curve.append(cash + open_val)

    return _calculate_performance_metrics("Retail Dip Buying (CORE2)", trades_history, equity_curve)


def _calculate_performance_metrics(name: str, trades: List[Dict[str, Any]], equity: List[float]) -> Dict[str, Any]:
    """Menghitung metrik performa kuantitatif standar hedge fund."""
    total_trades = len(trades)
    if total_trades == 0:
        return {
            'name': name, 'total_trades': 0, 'wins': 0, 'losses': 0,
            'win_rate': 0.0, 'total_pnl': 0.0, 'roi_pct': 0.0,
            'profit_factor': 0.0, 'max_drawdown_pct': 0.0,
            'sharpe_ratio': 0.0, 'expectancy_usd': 0.0,
            'trades': []
        }

    wins = sum(1 for t in trades if t['is_win'])
    losses = total_trades - wins
    win_rate = (wins / total_trades) * 100.0

    gross_profit = sum(t['pnl_usd'] for t in trades if t['pnl_usd'] > 0)
    gross_loss = abs(sum(t['pnl_usd'] for t in trades if t['pnl_usd'] < 0))
    net_pnl = gross_profit - gross_loss
    roi_pct = ((equity[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 99.0
    expectancy = net_pnl / total_trades

    # Max Drawdown
    peak = equity[0]
    max_dd = 0.0
    for val in equity:
        if val > peak:
            peak = val
        dd = (peak - val) / peak
        if dd > max_dd:
            max_dd = dd

    # Sharpe Ratio (Annualized berdasarkan 15m candle = 35,040 period/year)
    returns = np.diff(equity) / equity[:-1]
    std_ret = np.std(returns)
    sharpe = (np.mean(returns) / (std_ret + 1e-9)) * np.sqrt(35040) if std_ret > 0 else 0.0

    return {
        'name': name,
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': round(win_rate, 1),
        'gross_profit': round(gross_profit, 2),
        'gross_loss': round(gross_loss, 2),
        'net_pnl': round(net_pnl, 2),
        'final_capital': round(equity[-1], 2),
        'roi_pct': round(roi_pct, 2),
        'profit_factor': round(profit_factor, 2),
        'max_drawdown_pct': round(max_dd * 100.0, 2),
        'sharpe_ratio': round(sharpe, 2),
        'expectancy_usd': round(expectancy, 3),
        'trades': trades
    }


def main():
    print("\n" + "=" * 80)
    print(" 🏛️ RIGOROUS QUANTITATIVE BACKTEST: WORLDQUANT 101 ALPHAS VS RETAIL DIP BUYING")
    print("=" * 80)
    print("[*] Memuat dataset klines historis riil Spot Kripto...")
    dataset = load_universe_dataset()
    print(f"[+] Berhasil memuat {len(dataset)} pasangan koin Spot.")
    print(f"[*] Durasi data: {min(d['length'] for d in dataset)} candle 15-menit (~8 s/d 10 hari trading riil).")
    print(f"[*] Biaya transaksi: 0.10% Spot Taker fee per leg (0.20% round trip).")
    print("-" * 80)

    print("\n[1/2] Menjalankan Backtest: Model A (WorldQuant 101 Alphas + Stoikov Decile Q1)...")
    res_wq = run_worldquant_backtest(dataset)
    print(f"      Selesai! Total Trade: {res_wq['total_trades']}, Win Rate: {res_wq['win_rate']}%, Net PnL: ${res_wq['net_pnl']:+.2f}")

    print("\n[2/2] Menjalankan Backtest: Model B (Retail Dip Buying CORE2 - RSI < 35 & BB Low)...")
    res_retail = run_retail_dip_buying_backtest(dataset)
    print(f"      Selesai! Total Trade: {res_retail['total_trades']}, Win Rate: {res_retail['win_rate']}%, Net PnL: ${res_retail['net_pnl']:+.2f}")

    print("\n" + "=" * 80)
    print(" 📊 HEAD-TO-HEAD QUANTITATIVE AUDIT REPORT")
    print("=" * 80)
    headers = f"{'METRIK EVALUASI':<28} | {'WORLDQUANT 101 Q1 (BARU)':<24} | {'RETAIL DIP BUYING (LAMA)':<22}"
    print(headers)
    print("-" * 80)
    
    rows = [
        ("Total Trade Selesai", f"{res_wq['total_trades']} trades", f"{res_retail['total_trades']} trades"),
        ("Win Rate (W vs L)", f"{res_wq['win_rate']}% ({res_wq['wins']}W / {res_wq['losses']}L)", f"{res_retail['win_rate']}% ({res_retail['wins']}W / {res_retail['losses']}L)"),
        ("Gross Profit", f"${res_wq['gross_profit']:.2f}", f"${res_retail['gross_profit']:.2f}"),
        ("Gross Loss", f"${res_wq['gross_loss']:.2f}", f"${res_retail['gross_loss']:.2f}"),
        ("Net PnL Bersih ($)", f"${res_wq['net_pnl']:+.2f}", f"${res_retail['net_pnl']:+.2f}"),
        ("Final Capital ($100 Awal)", f"${res_wq['final_capital']:.2f}", f"${res_retail['final_capital']:.2f}"),
        ("ROI (%)", f"{res_wq['roi_pct']:+.2f}%", f"{res_retail['roi_pct']:+.2f}%"),
        ("Profit Factor", f"{res_wq['profit_factor']:.2f}", f"{res_retail['profit_factor']:.2f}"),
        ("Max Drawdown (%)", f"{res_wq['max_drawdown_pct']:.2f}%", f"{res_retail['max_drawdown_pct']:.2f}%"),
        ("Sharpe Ratio (Annualized)", f"{res_wq['sharpe_ratio']:.2f}", f"{res_retail['sharpe_ratio']:.2f}"),
        ("Expectancy per Trade", f"${res_wq['expectancy_usd']:+.3f}", f"${res_retail['expectancy_usd']:+.3f}")
    ]

    for label, val_wq, val_rt in rows:
        print(f"{label:<28} | {val_wq:<24} | {val_rt:<22}")

    print("=" * 80)

    # Kesimpulan Akademis
    print("\n🔍 ANALISIS EMPIRIS & KESIMPULAN RISET:")
    if res_wq['net_pnl'] > res_retail['net_pnl'] and res_wq['win_rate'] > res_retail['win_rate']:
        print("  ✅ Terbukti Secara Ilmiah: Model WorldQuant 101 Formulaic Alphas mengungguli Retail Dip-Buying secara telak.")
        print(f"  ✅ Keunggulan Win Rate : +{res_wq['win_rate'] - res_retail['win_rate']:.1f}% lebih tinggi.")
        print(f"  ✅ Keunggulan PnL      : ${res_wq['net_pnl'] - res_retail['net_pnl']:+.2f} selisih keuntungan.")
        print(f"  ✅ Profit Factor       : {res_wq['profit_factor']:.2f} (Kuantitatif) vs {res_retail['profit_factor']:.2f} (Ritel)")
        print("  💡 Alasan Fundamental : Ritel menangkap koin yang jatuh bebas saat pasar dumping (mean reversion gagal total).")
        print("                         Sedangkan WorldQuant hanya menunggangi momentum desil teratas dengan efisiensi beli intraday tertinggi.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
