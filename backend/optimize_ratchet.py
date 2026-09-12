import pickle
import numpy as np

with open("spot_backtest_cache.pkl", "rb") as f:
    raw_dataset = pickle.load(f)

numpy_dataset = []
for df in raw_dataset:
    numpy_dataset.append({
        'high': df['high'].to_numpy(dtype=float),
        'low': df['low'].to_numpy(dtype=float),
        'close': df['close'].to_numpy(dtype=float),
        'rsi': df['rsi'].to_numpy(dtype=float),
        'rvol': df['rvol'].to_numpy(dtype=float),
        'is_bull': df['trend_bullish'].to_numpy(dtype=bool),
        'chg': df['chg_24h'].to_numpy(dtype=float),
        'wick': df['lower_wick_ratio'].to_numpy(dtype=float),
        'bb_low': df['bb_low'].to_numpy(dtype=float),
        'bb_up': df['bb_up'].to_numpy(dtype=float),
        'is_sqz': df['is_squeeze'].to_numpy(dtype=bool),
        'vwap_dist': df['vwap_dist'].to_numpy(dtype=float),
        'length': len(df)
    })

SPOT_FEE = 0.001
TRADE_SIZE = 150.0

def test_combined(allow_dip=True, allow_breakout=True):
    wins = 0
    losses = 0
    total_pnl = 0.0
    trade_returns = []
    
    for d in numpy_dataset:
        highs = d['high']
        lows = d['low']
        closes = d['close']
        rsis = d['rsi']
        rvols = d['rvol']
        bulls = d['is_bull']
        chgs = d['chg']
        wicks = d['wick']
        bb_lows = d['bb_low']
        bb_ups = d['bb_up']
        is_sqzs = d['is_sqz']
        n = d['length']

        in_trade = False
        entry_price = 0.0
        tp_price = 0.0
        sl_price = 0.0
        peak_gain = 0.0
        hold_candles = 0

        for i in range(50, n):
            h = highs[i]
            l = lows[i]
            c = closes[i]

            if in_trade:
                hold_candles += 1
                curr_gain = (h - entry_price) / entry_price
                if curr_gain > peak_gain:
                    peak_gain = curr_gain

                # Institutional Breakeven Ratchet
                if peak_gain >= 0.028:
                    sl_price = max(sl_price, entry_price * 1.004) # Lock Breakeven
                if peak_gain >= 0.048:
                    sl_price = max(sl_price, entry_price * 1.025) # Lock Profit 1

                hit_tp = h >= tp_price
                hit_sl = l <= sl_price
                timeout = hold_candles >= 32

                if hit_tp or hit_sl or timeout:
                    exit_price = tp_price if hit_tp else (sl_price if hit_sl else c)
                    raw_pct = (exit_price - entry_price) / entry_price
                    net_pct = raw_pct - (SPOT_FEE * 2)
                    pnl_usd = TRADE_SIZE * net_pct
                    total_pnl += pnl_usd
                    trade_returns.append(net_pct)
                    if pnl_usd > 0: wins += 1
                    else: losses += 1
                    in_trade = False

            if not in_trade:
                signal = False
                
                # Signal 1: NFI Bullish Dip Snipe
                if allow_dip:
                    if bulls[i] and (rsis[i] < 38 or lows[i] <= bb_lows[i] * 1.005) and wicks[i] >= 1.2 and rvols[i] >= 1.1 and chgs[i] <= 15.0:
                        signal = True
                
                # Signal 2: Volatility Squeeze Breakout (Fresh Volume Expansion)
                if allow_breakout and not signal:
                    if bulls[i] and rvols[i] >= 1.8 and 52 <= rsis[i] <= 68 and c >= bb_ups[i] * 0.995 and 1.0 <= chgs[i] <= 14.0:
                        signal = True

                if signal:
                    in_trade = True
                    entry_price = c
                    tp_price = c * 1.070  # +7.0% TP
                    sl_price = c * 0.982  # -1.8% SL
                    peak_gain = 0.0
                    hold_candles = 0

    total_trades = wins + losses
    if total_trades == 0: return None
    wr = (wins / total_trades) * 100
    gross_win = sum(r for r in trade_returns if r > 0)
    gross_loss = abs(sum(r for r in trade_returns if r < 0))
    pf = (gross_win / gross_loss) if gross_loss > 0 else 99.0
    return total_trades, wr, pf, total_pnl

print("=" * 70)
print("HASIL PENGUJIAN KOMBINASI STRATEGI SPOT:")
print("-" * 70)
for d, b, name in [(True, False, "1. Pure Dip Sniping"), (False, True, "2. Pure Volatility Breakout"), (True, True, "3. Dual-Engine Hybrid (Dip + Breakout)")]:
    res = test_combined(d, b)
    if res:
        t, wr, pf, pnl = res
        print(f"{name:<40} {t:>5} trades | WR: {wr:>5.1f}% | PF: {pf:>5.2f}x | Net: ${pnl:>7.2f}")
