import pickle
import numpy as np

with open("spot_backtest_cache.pkl", "rb") as f:
    raw_dataset = pickle.load(f)

# Convert to fast numpy arrays
dataset = []
for df in raw_dataset:
    # hitung bb_mid dan bb_lowerband standar (20, 2)
    typical = (df['high'] + df['low'] + df['close']) / 3
    bb_mid = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    bb_lower = bb_mid - (bb_std * 2.0)
    ema50 = df['close'].ewm(span=50, adjust=False).mean()

    dataset.append({
        'high': df['high'].to_numpy(dtype=float),
        'low': df['low'].to_numpy(dtype=float),
        'close': df['close'].to_numpy(dtype=float),
        'open': df['open'].to_numpy(dtype=float),
        'rsi': df['rsi'].to_numpy(dtype=float),
        'rvol': df['rvol'].to_numpy(dtype=float),
        'bb_mid': bb_mid.to_numpy(dtype=float),
        'bb_lower': bb_lower.to_numpy(dtype=float),
        'ema50': ema50.to_numpy(dtype=float),
        'length': len(df)
    })

SPOT_FEE = 0.001
TRADE_SIZE = 150.0

def test_cluc_mean_reversion(bb_mult, rsi_max, tp_pct, sl_pct):
    wins = 0
    losses = 0
    total_pnl = 0.0
    trade_returns = []

    for d in dataset:
        highs = d['high']
        lows = d['low']
        closes = d['close']
        rsis = d['rsi']
        rvols = d['rvol']
        bb_mids = d['bb_mid']
        bb_lowers = d['bb_lower']
        ema50s = d['ema50']
        n = d['length']

        in_trade = False
        entry_price = 0.0
        tp_price = 0.0
        sl_price = 0.0
        hold_candles = 0

        for i in range(50, n):
            h = highs[i]
            l = lows[i]
            c = closes[i]

            if in_trade:
                hold_candles += 1
                # Exit kondisi: hit TP ATAU harga tembus kembali ke BB Mid
                hit_tp = (h >= tp_price) or (c >= bb_mids[i])
                hit_sl = (l <= sl_price)
                timeout = hold_candles >= 48 # 12 jam

                if hit_tp or hit_sl or timeout:
                    if hit_tp:
                        exit_price = max(c, tp_price if h >= tp_price else c)
                    elif hit_sl:
                        exit_price = sl_price
                    else:
                        exit_price = c

                    raw_pct = (exit_price - entry_price) / entry_price
                    net_pct = raw_pct - (SPOT_FEE * 2)
                    pnl = TRADE_SIZE * net_pct
                    total_pnl += pnl
                    trade_returns.append(net_pct)
                    if pnl > 0: wins += 1
                    else: losses += 1
                    in_trade = False

            if not in_trade:
                # Combined Cluc + BinHV + Trend Oversold:
                # 1. Harga di bawah Lower BB dengan diskon (c < bb_lower * bb_mult)
                # 2. RSI oversold (rsi <= rsi_max)
                # 3. Koin tidak crash di bawah EMA50 terlalu jauh (c >= ema50 * 0.94)
                if c < (bb_lowers[i] * bb_mult) and rsis[i] <= rsi_max and c >= (ema50s[i] * 0.94):
                    in_trade = True
                    entry_price = c
                    tp_price = c * (1 + tp_pct)
                    sl_price = c * (1 - sl_pct)
                    hold_candles = 0

    total_trades = wins + losses
    if total_trades == 0: return None
    wr = (wins / total_trades) * 100
    gross_win = sum(r for r in trade_returns if r > 0)
    gross_loss = abs(sum(r for r in trade_returns if r < 0))
    pf = (gross_win / gross_loss) if gross_loss > 0 else 99.0
    return total_trades, wr, pf, total_pnl

print("=" * 80)
print(f"{'bb_mult':>8} {'rsi':>5} {'tp%':>5} {'sl%':>5} {'trades':>7} {'winrate':>8} {'PF':>6} {'Net PnL ($)':>12}")
print("-" * 80)

for bb_mult in [1.000, 0.995, 0.990]:
    for rsi in [35, 40, 45]:
        for tp in [0.015, 0.020, 0.025]:
            for sl in [0.030, 0.040, 0.050]:
                res = test_cluc_mean_reversion(bb_mult, rsi, tp, sl)
                if res and res[0] >= 10:
                    t, wr, pf, pnl = res
                    print(f"{bb_mult:>8.3f} {rsi:>5} {tp*100:>4.1f}% {sl*100:>4.1f}% {t:>7} {wr:>7.1f}% {pf:>6.2f} ${pnl:>10.2f}", flush=True)
