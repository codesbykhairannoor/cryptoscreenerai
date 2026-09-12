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
        'is_bull': df['trend_bullish'].to_numpy(dtype=bool),
        'chg': df['chg_24h'].to_numpy(dtype=float),
        'length': len(df)
    })

SPOT_FEE = 0.001

def test_elite_dca(so_drop=0.018, tp_pct=0.012, max_so=2, base=40.0, so1=50.0, so2=60.0):
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
        wicks = d['wick']
        bb_lowers = d['bb_lower']
        ema50s = d['ema50']
        bulls = d['is_bull']
        chgs = d['chg']
        n = d['length']

        in_trade = False
        num_so = 0
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

                # SO 1 (-1.8% dari entry)
                if num_so == 0 and l <= (avg_entry * (1 - so_drop)):
                    p = avg_entry * (1 - so_drop)
                    total_coins += so1 / p
                    total_cost += so1
                    avg_entry = total_cost / total_coins
                    num_so = 1

                # SO 2 (-1.8% lagi dari entry baru)
                elif num_so == 1 and max_so >= 2 and l <= (avg_entry * (1 - so_drop)):
                    p = avg_entry * (1 - so_drop)
                    total_coins += so2 / p
                    total_cost += so2
                    avg_entry = total_cost / total_coins
                    num_so = 2

                tp_price = avg_entry * (1 + tp_pct)
                sl_price = avg_entry * 0.940 # Hard SL -6.0%

                hit_tp = h >= tp_price
                hit_sl = l <= sl_price
                timeout = hold_candles >= 48 # 12 jam

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
                # Elite Reddit Filter:
                # 1. Tren dasar Bullish
                # 2. Oversold Dip ke Lower Band atau RSI < 38
                # 3. Lower Wick Rejection (buyers present)
                if bulls[i] and (rsis[i] < 38 or closes[i] <= bb_lowers[i] * 1.005) and wicks[i] >= 1.1 and rvols[i] >= 1.1 and -6.0 < chgs[i] < 15.0:
                    in_trade = True
                    num_so = 0
                    base_coins = base / c
                    total_coins = base_coins
                    total_cost = base
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
print("ELITE SPOT DCA WITH TREND CONFIRMATION & SAFETY ORDERS")
print("Data Riil 48 Koin Spot Likuid | Fee 0.20% Round-trip")
print("=" * 85)
print(f"{'SO Drop%':>9} {'TP Target%':>11} {'Max SO':>7} {'Trades':>8} {'Win Rate':>10} {'PF':>6} {'Net PnL ($)':>13}")
print("-" * 85)

for so_drop in [0.015, 0.018, 0.022]:
    for tp in [0.010, 0.012, 0.015, 0.018]:
        for m_so in [1, 2]:
            res = test_elite_dca(so_drop, tp, m_so)
            if res:
                t, wr, pf, pnl = res
                print(f"{so_drop*100:>8.1f}% {tp*100:>10.1f}% {m_so:>7} {t:>8} {wr:>9.1f}% {pf:>6.2f} ${pnl:>11.2f}", flush=True)
