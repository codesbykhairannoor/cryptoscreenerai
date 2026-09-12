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
    ema21 = df['close'].ewm(span=21, adjust=False).mean()

    dataset.append({
        'high': df['high'].to_numpy(dtype=float),
        'low': df['low'].to_numpy(dtype=float),
        'close': df['close'].to_numpy(dtype=float),
        'rsi': df['rsi'].to_numpy(dtype=float),
        'rvol': df['rvol'].to_numpy(dtype=float),
        'wick': df['lower_wick_ratio'].to_numpy(dtype=float),
        'bb_lower': bb_lower.to_numpy(dtype=float),
        'ema50': ema50.to_numpy(dtype=float),
        'ema21': ema21.to_numpy(dtype=float),
        'is_bull': df['trend_bullish'].to_numpy(dtype=bool),
        'chg': df['chg_24h'].to_numpy(dtype=float),
        'length': len(df)
    })

SPOT_FEE = 0.001

def test_dca_multi_so(so_drop=0.015, tp_target=0.010, hard_sl=0.060, max_so=2):
    wins = 0
    losses = 0
    total_pnl = 0.0
    trade_returns = []

    # Alokasi: Base $30, SO1 $45, SO2 $75 (Total $150 modal per coin)
    so_weights = [30.0, 45.0, 75.0]

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

                # Safety Order Triggers
                if orders_filled == 1 and l <= (avg_entry * (1 - so_drop)):
                    p = avg_entry * (1 - so_drop)
                    cost = so_weights[1]
                    total_coins += cost / p
                    total_cost += cost
                    avg_entry = total_cost / total_coins
                    orders_filled = 2

                elif orders_filled == 2 and max_so >= 2 and l <= (avg_entry * (1 - so_drop)):
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
                # Filter: Beli saat harga menyentuh support / oversold
                if -8.0 < chgs[i] < 15.0 and (rsis[i] <= 36 or c <= bb_lowers[i] * 1.006) and wicks[i] >= 1.0:
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

print("=" * 88)
print("  UJI SMART MULTI-SAFETY ORDER (REDDIT/3COMMAS SECRET) PADA SPOT CRYPTO")
print("  Total Modal $150 ($30 Base + $45 SO1 + $75 SO2) | Spot Fee 0.20%")
print("=" * 88)
print(f"{'SO Drop%':>9} {'TP Target%':>11} {'Hard SL%':>10} {'Max SO':>7} {'Trades':>8} {'Win Rate':>10} {'PF':>6} {'Net PnL ($)':>12}")
print("-" * 88)

for so_drop in [0.012, 0.015, 0.018]:
    for tp in [0.008, 0.010, 0.012, 0.015]:
        for sl in [0.050, 0.060, 0.070]:
            for m_so in [1, 2]:
                res = test_dca_multi_so(so_drop, tp, sl, m_so)
                if res and res[1] >= 80.0:
                    t, wr, pf, pnl = res
                    print(f"{so_drop*100:>8.1f}% {tp*100:>10.1f}% {sl*100:>9.1f}% {m_so:>7} {t:>8} {wr:>9.1f}% {pf:>6.2f} ${pnl:>11.2f}", flush=True)
