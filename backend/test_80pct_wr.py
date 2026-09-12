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
        'open': df['open'].to_numpy(dtype=float),
        'rsi': df['rsi'].to_numpy(dtype=float),
        'rvol': df['rvol'].to_numpy(dtype=float),
        'wick': df['lower_wick_ratio'].to_numpy(dtype=float),
        'bb_mid': bb_mid.to_numpy(dtype=float),
        'bb_lower': bb_lower.to_numpy(dtype=float),
        'ema50': ema50.to_numpy(dtype=float),
        'ema21': ema21.to_numpy(dtype=float),
        'is_bull': df['trend_bullish'].to_numpy(dtype=bool),
        'chg': df['chg_24h'].to_numpy(dtype=float),
        'length': len(df)
    })

SPOT_FEE = 0.001 # 0.1% buy + 0.1% sell = 0.2% round-trip
TRADE_SIZE = 150.0

def run_simulation(bb_dev=1.000, max_rsi=38, tp_pct=0.015, sl_pct=0.040, be_trigger=0.009, exit_on_mid=True, require_bull=True):
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
        bb_mids = d['bb_mid']
        bb_lowers = d['bb_lower']
        ema50s = d['ema50']
        bulls = d['is_bull']
        chgs = d['chg']
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

                # Breakeven Ratchet (Kunci +0.3% begitu profit naik ke be_trigger)
                if be_trigger < 0.9 and peak_gain >= be_trigger:
                    sl_price = max(sl_price, entry_price * 1.003)

                # Exit kondisi
                hit_tp = h >= tp_price
                hit_mid = exit_on_mid and (c >= bb_mids[i]) and (c > entry_price * 1.006) # Profit minimal di BB Mid
                hit_sl = l <= sl_price
                timeout = hold_candles >= 48 # 12 jam max

                if hit_tp or hit_mid or hit_sl or timeout:
                    if hit_tp:
                        exit_price = tp_price
                    elif hit_mid:
                        exit_price = c
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
                # ENTRY CONDITION:
                # 1. Diskon harga: Menyentuh/di bawah Lower BB
                # 2. RSI Oversold
                # 3. Koin tidak sedang crash parah
                # 4. Optional Trend Filter
                trend_ok = bulls[i] if require_bull else (c >= ema50s[i] * 0.95)
                dip_ok = (c <= bb_lowers[i] * bb_dev) or (rsis[i] <= max_rsi)
                chg_ok = -8.0 < chgs[i] < 16.0

                if trend_ok and dip_ok and chg_ok and wicks[i] >= 1.0:
                    in_trade = True
                    entry_price = c
                    tp_price = c * (1 + tp_pct)
                    sl_price = c * (1 - sl_pct)
                    peak_gain = 0.0
                    hold_candles = 0

    total_trades = wins + losses
    if total_trades == 0: return None
    wr = (wins / total_trades) * 100
    gross_win = sum(r for r in trade_returns if r > 0)
    gross_loss = abs(sum(r for r in trade_returns if r < 0))
    pf = (gross_win / gross_loss) if gross_loss > 0 else 99.0
    return total_trades, wr, pf, total_pnl

print("=" * 88)
print("  GRID OPTIMIZER: MENCARI FORMULA WIN RATE > 80% PADA SPOT CRYPTO")
print("  Data Riil 48 Koin Spot Likuid | Modal $150/trade | Round-trip Fee 0.20%")
print("=" * 88)
print(f"{'BB_Dev':>6} {'RSI':>4} {'TP%':>5} {'SL%':>5} {'BE_Trig':>8} {'MidExit':>8} {'Trades':>7} {'WinRate':>9} {'PF':>6} {'Net PnL ($)':>12}")
print("-" * 88)

results_80 = []

for bb_dev in [1.000, 0.995]:
    for rsi in [32, 35, 38]:
        for tp in [0.012, 0.015, 0.018]:
            for sl in [0.035, 0.045, 0.055]:
                for be in [0.008, 0.010, 99.0]:
                    for mid in [True, False]:
                        for req_bull in [True, False]:
                            res = run_simulation(bb_dev, rsi, tp, sl, be, exit_on_mid=mid, require_bull=req_bull)
                            if res and res[0] >= 20 and res[1] >= 80.0:
                                t, wr, pf, pnl = res
                                results_80.append((bb_dev, rsi, tp, sl, be, mid, req_bull, t, wr, pf, pnl))
                                print(f"{bb_dev:>6.3f} {rsi:>4} {tp*100:>4.1f}% {sl*100:>4.1f}% {be*100:>7.1f}% {str(mid):>8} {t:>7} {wr:>8.1f}% {pf:>6.2f} ${pnl:>11.2f}", flush=True)

if not results_80:
    print("\nTidak ada konfigurasi dengan WR >= 80.0%. Menurunkan ambang ke WR >= 72.0%...")
    for bb_dev in [1.000, 0.995]:
        for rsi in [35, 38]:
            for tp in [0.012, 0.015]:
                for sl in [0.040, 0.050]:
                    for be in [0.008, 99.0]:
                        res = run_simulation(bb_dev, rsi, tp, sl, be, exit_on_mid=True, require_bull=False)
                        if res and res[0] >= 25 and res[1] >= 70.0:
                            t, wr, pf, pnl = res
                            print(f"{bb_dev:>6.3f} {rsi:>4} {tp*100:>4.1f}% {sl*100:>4.1f}% {be*100:>7.1f}% {str(True):>8} {t:>7} {wr:>8.1f}% {pf:>6.2f} ${pnl:>11.2f}", flush=True)
