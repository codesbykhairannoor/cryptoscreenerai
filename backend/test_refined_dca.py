import pickle
import numpy as np

with open("spot_backtest_cache.pkl", "rb") as f:
    raw_dataset = pickle.load(f)

dataset = []
for df in raw_dataset:
    bb_mid = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    bb_lower = bb_mid - (bb_std * 2.0)
    ema50 = df['close'].ewm(span=50, adjust=False).mean()

    dataset.append({
        'high': df['high'].to_numpy(dtype=float),
        'low': df['low'].to_numpy(dtype=float),
        'close': df['close'].to_numpy(dtype=float),
        'rsi': df['rsi'].to_numpy(dtype=float),
        'rvol': df['rvol'].to_numpy(dtype=float),
        'wick': df['lower_wick_ratio'].to_numpy(dtype=float),
        'bb_lower': bb_lower.to_numpy(dtype=float),
        'ema50': ema50.to_numpy(dtype=float),
        'is_bull': df['trend_bullish'].to_numpy(dtype=bool),
        'chg': df['chg_24h'].to_numpy(dtype=float),
        'length': len(df)
    })

SPOT_FEE = 0.001

def test_ultra_dca(so_drop=0.015, tp_target=0.009, hard_sl=0.055, min_rvol=1.1, min_wick=1.1):
    wins = 0
    losses = 0
    total_pnl = 0.0
    trade_returns = []
    so_weights = [35.0, 50.0, 65.0]

    for d in dataset:
        highs = d['high']
        lows = d['low']
        closes = d['close']
        rsis = d['rsi']
        rvols = d['rvol']
        wicks = d['wick']
        bb_lowers = d['bb_lower']
        ema50s = d['ema50']
        bulls = d['is_bull']
        chgs = d['chg']
        n = d['length']

        in_trade = False
        orders_filled = 0
        total_cost = 0.0
        total_coins = 0.0
        avg_entry = 0.0
        hold_candles = 0

        for i in range(50, n):
            h = highs[i]
            l = lows[i]
            c = closes[i]

            if in_trade:
                hold_candles += 1

                # SO 1
                if orders_filled == 1 and l <= (avg_entry * (1 - so_drop)):
                    p = avg_entry * (1 - so_drop)
                    cost = so_weights[1]
                    total_coins += cost / p
                    total_cost += cost
                    avg_entry = total_cost / total_coins
                    orders_filled = 2

                # SO 2
                elif orders_filled == 2 and l <= (avg_entry * (1 - so_drop)):
                    p = avg_entry * (1 - so_drop)
                    cost = so_weights[2]
                    total_coins += cost / p
                    total_cost += cost
                    avg_entry = total_cost / total_coins
                    orders_filled = 3

                tp_price = avg_entry * (1 + tp_target)
                sl_price = avg_entry * (1 - hard_sl)

                hit_tp = h >= tp_price
                hit_sl = l <= sl_price
                timeout = hold_candles >= 48

                if hit_tp or hit_sl or timeout:
                    exit_price = tp_price if hit_tp else (sl_price if hit_sl else c)
                    revenue = total_coins * exit_price
                    fee = (total_cost * SPOT_FEE) + (revenue * SPOT_FEE)
                    net_pnl = (revenue - total_cost) - fee
                    pct_pnl = (net_pnl / total_cost) * 100.0

                    total_pnl += net_pnl
                    trade_returns.append(pct_pnl)
                    if net_pnl > 0: wins += 1
                    else: losses += 1
                    in_trade = False

            if not in_trade:
                # Syarat Kualitas Tinggi:
                # 1. Koin tidak sedang dumping parah
                # 2. RSI Oversold <= 36 atau menyentuh Lower Band
                # 3. Ada Lower Wick Rejection (pembeli mulai memantulkan harga)
                # 4. Ada Volume RVOL >= min_rvol
                if -6.0 < chgs[i] < 16.0 and (rsis[i] <= 36 or c <= bb_lowers[i] * 1.005) and wicks[i] >= min_wick and rvols[i] >= min_rvol and c >= ema50s[i] * 0.96:
                    in_trade = True
                    orders_filled = 1
                    cost = so_weights[0]
                    total_coins = cost / c
                    total_cost = cost
                    avg_entry = c
                    hold_candles = 0

    total_trades = wins + losses
    if total_trades == 0: return None
    wr = (wins / total_trades) * 100
    gross_win = sum(r for r in trade_returns if r > 0)
    gross_loss = abs(sum(r for r in trade_returns if r < 0))
    pf = (gross_win / gross_loss) if gross_loss > 0 else 99.0
    return total_trades, wr, pf, total_pnl

print("=" * 85)
print("TEST REFINED HIGH WIN RATE SPOT DCA (TARGET > 85% WR)")
print("=" * 85)
for so_drop in [0.012, 0.015, 0.018]:
    for tp in [0.008, 0.010, 0.012]:
        for sl in [0.050, 0.060]:
            res = test_ultra_dca(so_drop=so_drop, tp_target=tp, hard_sl=sl, min_rvol=1.1, min_wick=1.1)
            if res and res[1] >= 80.0:
                t, wr, pf, pnl = res
                print(f"SO: {so_drop*100:>4.1f}% | TP: {tp*100:>4.1f}% | SL: {sl*100:>4.1f}% | Trades: {t:>4} | WinRate: {wr:>5.1f}% | PF: {pf:>5.2f}x | Net PnL: ${pnl:>7.2f}")
