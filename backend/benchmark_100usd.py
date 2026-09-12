import pickle
import numpy as np
import pandas as pd
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

import os
CACHE_FILE = "spot_backtest_cache.pkl" if os.path.exists("spot_backtest_cache.pkl") else os.path.join(os.path.dirname(__file__), "spot_backtest_cache.pkl")
with open(CACHE_FILE, "rb") as f:
    raw_dataset = pickle.load(f)

# Build pre-computed candle arrays
coins_data = []
for idx, df in enumerate(raw_dataset):
    df = df.sort_values("ts").reset_index(drop=True)
    bb_mid = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    bb_lower = bb_mid - (bb_std * 2.0)
    ema50 = df['close'].ewm(span=50, adjust=False).mean()

    # Volume Velocity: 1h / 24h
    vol_1h = df['baseVol'].rolling(4).sum()
    vol_24h = df['baseVol'].rolling(96).sum()
    vol_vel = vol_1h / (vol_24h + 1e-9)

    # CMO
    diff = df['close'].diff()
    up = diff.clip(lower=0)
    down = (-diff).clip(lower=0)
    sum_up = up.rolling(14).sum()
    sum_down = down.rolling(14).sum()
    cmo = 100 * (sum_up - sum_down) / (sum_up + sum_down + 1e-9)

    coins_data.append({
        'id': idx,
        'ts': df['ts'].to_numpy(),
        'high': df['high'].to_numpy(dtype=float),
        'low': df['low'].to_numpy(dtype=float),
        'close': df['close'].to_numpy(dtype=float),
        'open': df['open'].to_numpy(dtype=float),
        'rsi': df['rsi'].to_numpy(dtype=float),
        'rvol': df['rvol'].to_numpy(dtype=float),
        'wick': df['lower_wick_ratio'].to_numpy(dtype=float),
        'bb_lower': bb_lower.to_numpy(dtype=float),
        'bb_up': df['bb_up'].to_numpy(dtype=float),
        'ema50': ema50.to_numpy(dtype=float),
        'trend_bull': df['trend_bullish'].to_numpy(dtype=bool),
        'chg': df['chg_24h'].to_numpy(dtype=float),
        'v_vel': vol_vel.to_numpy(dtype=float),
        'cmo': cmo.to_numpy(dtype=float),
        'length': len(df)
    })

NUM_CANDLES = min(c['length'] for c in coins_data)
FEE = 0.001 # 0.10% buy + 0.10% sell = 0.20% roundtrip

def run_simulation(strat_name, strat_config):
    """
    Simulates chronological portfolio trading starting at $100.00.
    """
    balance = 100.00
    peak_balance = 100.00
    max_drawdown_pct = 0.0
    trades = []

    pos = None

    for t in range(50, NUM_CANDLES):
        if pos is not None:
            c_idx = pos['coin_idx']
            cd = coins_data[c_idx]
            h = cd['high'][t]
            l = cd['low'][t]
            c = cd['close'][t]

            pos['hold_candles'] += 1
            if h > pos['peak_price']:
                pos['peak_price'] = h

            if strat_config.get('use_dca', False):
                so_drop = strat_config['so_drop']
                if pos['so_step'] == 1 and l <= (pos['avg_entry'] * (1 - so_drop)):
                    so_cost = pos['initial_balance'] * strat_config['so_weights'][1]
                    p_exec = pos['avg_entry'] * (1 - so_drop)
                    pos['coins'] += so_cost / p_exec
                    pos['total_invested'] += so_cost
                    pos['avg_entry'] = pos['total_invested'] / pos['coins']
                    pos['so_step'] = 2

                elif pos['so_step'] == 2 and l <= (pos['avg_entry'] * (1 - so_drop)):
                    so_cost = pos['initial_balance'] * strat_config['so_weights'][2]
                    p_exec = pos['avg_entry'] * (1 - so_drop)
                    pos['coins'] += so_cost / p_exec
                    pos['total_invested'] += so_cost
                    pos['avg_entry'] = pos['total_invested'] / pos['coins']
                    pos['so_step'] = 3

            avg_e = pos['avg_entry']
            tp_pct = strat_config['tp_pct']
            sl_pct = strat_config['sl_pct']

            be_trigger = strat_config.get('be_trigger', None)
            if be_trigger and pos['peak_price'] >= avg_e * (1 + be_trigger):
                pos['sl_price'] = max(pos['sl_price'], avg_e * 1.004)

            if strat_config.get('is_hybrid', False):
                if not pos.get('half_sold', False) and h >= avg_e * (1 + tp_pct):
                    sold_coins = pos['coins'] * 0.5
                    sell_rev = sold_coins * avg_e * (1 + tp_pct)
                    sell_fee = sell_rev * FEE
                    pos['realized_cash'] += (sell_rev - sell_fee)
                    pos['coins'] -= sold_coins
                    pos['half_sold'] = True
                    pos['sl_price'] = avg_e * 1.004

                if pos.get('half_sold', False):
                    trail_dist = strat_config.get('trail_dist', 0.025)
                    runner_sl = pos['peak_price'] * (1 - trail_dist)
                    pos['sl_price'] = max(pos['sl_price'], runner_sl)

            is_exit = False
            exit_price = 0.0
            exit_reason = ""

            if strat_config.get('type') == 'PREDATOR_ESCALATOR':
                peak_pct = (pos['peak_price'] - avg_e) / avg_e * 100.0
                if peak_pct >= 35.0:
                    pos['sl_price'] = max(pos['sl_price'], avg_e * 1.25)
                elif peak_pct >= 18.0:
                    pos['sl_price'] = max(pos['sl_price'], avg_e * 1.12)
                elif peak_pct >= 10.0:
                    pos['sl_price'] = max(pos['sl_price'], avg_e * 1.07)
                elif peak_pct >= 5.5:
                    pos['sl_price'] = max(pos['sl_price'], avg_e * 1.032)
                elif peak_pct >= 2.5:
                    pos['sl_price'] = max(pos['sl_price'], avg_e * 1.005)

                if peak_pct >= 50.0:
                    pos['sl_price'] = max(pos['sl_price'], pos['peak_price'] * 0.92)

                if l <= pos['sl_price']:
                    exit_price = pos['sl_price']
                    exit_reason = "ESCALATOR_LOCK" if pos['sl_price'] > avg_e else "INITIAL_SL"
                    is_exit = True
                elif pos['hold_candles'] >= strat_config.get('timeout_candles', 48):
                    exit_price = c
                    exit_reason = "TIMEOUT"
                    is_exit = True

            elif not strat_config.get('is_hybrid', False):
                if h >= avg_e * (1 + tp_pct):
                    exit_price = avg_e * (1 + tp_pct)
                    exit_reason = "TP"
                    is_exit = True
                elif l <= pos['sl_price']:
                    exit_price = pos['sl_price']
                    exit_reason = "SL"
                    is_exit = True
                elif pos['hold_candles'] >= strat_config.get('timeout_candles', 48):
                    exit_price = c
                    exit_reason = "TIMEOUT"
                    is_exit = True
            else:
                if not pos.get('half_sold', False):
                    if l <= pos['sl_price']:
                        exit_price = pos['sl_price']
                        exit_reason = "INITIAL_SL"
                        is_exit = True
                    elif pos['hold_candles'] >= strat_config.get('timeout_candles', 48):
                        exit_price = c
                        exit_reason = "TIMEOUT"
                        is_exit = True
                else:
                    if l <= pos['sl_price']:
                        exit_price = pos['sl_price']
                        exit_reason = "RUNNER_SL"
                        is_exit = True
                    elif pos['hold_candles'] >= strat_config.get('timeout_candles', 48):
                        exit_price = c
                        exit_reason = "RUNNER_TIMEOUT"
                        is_exit = True

            if is_exit:
                if not strat_config.get('is_hybrid', False):
                    gross_rev = pos['coins'] * exit_price
                    total_fee = (pos['total_invested'] * FEE) + (gross_rev * FEE)
                    net_return = gross_rev - total_fee
                    pnl_usd = net_return - pos['total_invested']
                    balance = (balance - pos['total_invested']) + net_return
                else:
                    if not pos.get('half_sold', False):
                        gross_rev = pos['coins'] * exit_price
                        total_fee = (pos['total_invested'] * FEE) + (gross_rev * FEE)
                        net_return = gross_rev - total_fee
                        pnl_usd = net_return - pos['total_invested']
                        balance = (balance - pos['total_invested']) + net_return
                    else:
                        rem_rev = pos['coins'] * exit_price
                        rem_fee = rem_rev * FEE
                        total_cash = pos['realized_cash'] + rem_rev - rem_fee
                        pnl_usd = total_cash - pos['total_invested']
                        balance = (balance - pos['total_invested']) + total_cash

                trades.append({
                    'pnl': pnl_usd,
                    'win': pnl_usd > 0,
                    'reason': exit_reason,
                    'balance_after': balance
                })
                pos = None

                if balance > peak_balance:
                    peak_balance = balance
                dd = (peak_balance - balance) / peak_balance * 100.0
                if dd > max_drawdown_pct:
                    max_drawdown_pct = dd

        if pos is None and balance >= 10.0:
            best_candidate = None
            best_score = -999

            for idx, cd in enumerate(coins_data):
                c = cd['close'][t]
                rsi = cd['rsi'][t]
                rvol = cd['rvol'][t]
                wick = cd['wick'][t]
                bb_low = cd['bb_lower'][t]
                bb_up = cd['bb_up'][t]
                ema50 = cd['ema50'][t]
                chg = cd['chg'][t]
                bull = cd['trend_bull'][t]

                signal = False
                score = 0

                strat_type = strat_config['type']
                if strat_type == "DCA_DIP" or strat_type == "HYBRID_DIP":
                    if -6.0 < chg < 16.0 and (rsi <= 36 or c <= bb_low * 1.008) and wick >= 1.1 and rvol >= 1.1 and c >= ema50 * 0.96:
                        signal = True
                        score = (40 - rsi) * 2 + (wick * 5) + (rvol * 5)

                elif strat_type == "WHALE_BREAKOUT":
                    if rvol >= 2.5 and 50 <= rsi <= 72 and bull and 2.0 <= chg <= 15.0 and c >= bb_up * 0.995:
                        signal = True
                        score = rvol * 10 + (rsi - 50)

                elif strat_type == "TREND_PULLBACK":
                    if bull and c >= ema50 and 42 <= rsi <= 55 and rvol >= 1.2 and wick >= 1.1:
                        signal = True
                        score = rvol * 5 + wick * 5

                elif strat_type == "MOONSHOT_SNIPER":
                    if -5.0 < chg < 15.0 and (rsi <= 35 or c <= bb_low * 1.005) and wick >= 1.2 and rvol >= 1.3:
                        signal = True
                        score = (35 - rsi) * 2 + rvol * 5

                elif strat_type == "PREDATOR_ESCALATOR":
                    v_vel = cd['v_vel'][t]
                    cmo_val = cd['cmo'][t]
                    if bull and rvol >= 1.8 and v_vel >= 0.12 and cmo_val >= 35 and 0.5 <= chg <= 18.0:
                        signal = True
                        score = rvol * 10 + cmo_val + (v_vel * 100)

                if signal and score > best_score:
                    best_score = score
                    best_candidate = (idx, c)

            if best_candidate is not None:
                c_idx, entry_p = best_candidate
                initial_capital = balance

                if strat_config.get('use_dca', False):
                    b_weight = strat_config['so_weights'][0]
                    base_usd = initial_capital * b_weight
                    pos = {
                        'coin_idx': c_idx,
                        'initial_balance': initial_capital,
                        'total_invested': base_usd,
                        'coins': base_usd / entry_p,
                        'avg_entry': entry_p,
                        'so_step': 1,
                        'sl_price': entry_p * (1 - strat_config['sl_pct']),
                        'peak_price': entry_p,
                        'hold_candles': 0,
                        'realized_cash': 0.0
                    }
                else:
                    pos = {
                        'coin_idx': c_idx,
                        'initial_balance': initial_capital,
                        'total_invested': initial_capital,
                        'coins': initial_capital / entry_p,
                        'avg_entry': entry_p,
                        'so_step': 0,
                        'sl_price': entry_p * (1 - strat_config['sl_pct']),
                        'peak_price': entry_p,
                        'hold_candles': 0,
                        'realized_cash': 0.0
                    }

    wins = [t for t in trades if t['win']]
    losses = [t for t in trades if not t['win']]
    tot_trades = len(trades)
    wr = len(wins) / tot_trades * 100 if tot_trades > 0 else 0
    tot_win_pnl = sum(t['pnl'] for t in wins)
    tot_loss_pnl = abs(sum(t['pnl'] for t in losses))
    pf = tot_win_pnl / tot_loss_pnl if tot_loss_pnl > 0 else 0
    roi = (balance - 100.00) / 100.00 * 100.0

    return {
        'name': strat_name,
        'final_balance': balance,
        'roi': roi,
        'trades': tot_trades,
        'win_rate': wr,
        'pf': pf,
        'max_dd': max_drawdown_pct,
        'wins': len(wins),
        'losses': len(losses),
        'avg_win': tot_win_pnl / len(wins) if wins else 0,
        'avg_loss': tot_loss_pnl / len(losses) if losses else 0
    }

strategies = [
    (
        "1. 3-Tier DCA Sweet Spot (+1.8% TP)",
        {
            'type': "DCA_DIP",
            'use_dca': True,
            'so_weights': [0.25, 0.35, 0.40],
            'so_drop': 0.018,
            'tp_pct': 0.018,
            'sl_pct': 0.050,
            'be_trigger': 0.012,
            'timeout_candles': 48
        }
    ),
    (
        "2. Ultra-High WR DCA (+0.9% Scalp)",
        {
            'type': "DCA_DIP",
            'use_dca': True,
            'so_weights': [0.25, 0.35, 0.40],
            'so_drop': 0.015,
            'tp_pct': 0.009,
            'sl_pct': 0.055,
            'timeout_candles': 48
        }
    ),
    (
        "3. Beefy DCA Scalper (+2.5% TP)",
        {
            'type': "DCA_DIP",
            'use_dca': True,
            'so_weights': [0.25, 0.35, 0.40],
            'so_drop': 0.018,
            'tp_pct': 0.025,
            'sl_pct': 0.050,
            'be_trigger': 0.015,
            'timeout_candles': 48
        }
    ),
    (
        "4. Hybrid Scalp & Moonshot (50% TP, 50% Runner)",
        {
            'type': "HYBRID_DIP",
            'use_dca': True,
            'is_hybrid': True,
            'so_weights': [0.25, 0.35, 0.40],
            'so_drop': 0.018,
            'tp_pct': 0.020,
            'trail_dist': 0.025,
            'sl_pct': 0.050,
            'timeout_candles': 60
        }
    ),
    (
        "5. Single-Bullet Whale Breakout (All-in $100, +8% TP)",
        {
            'type': "WHALE_BREAKOUT",
            'use_dca': False,
            'tp_pct': 0.080,
            'sl_pct': 0.030,
            'be_trigger': 0.030,
            'timeout_candles': 48
        }
    ),
    (
        "6. Trend-Follow Momentum (All-in $100, +5% TP)",
        {
            'type': "TREND_PULLBACK",
            'use_dca': False,
            'tp_pct': 0.050,
            'sl_pct': 0.025,
            'be_trigger': 0.025,
            'timeout_candles': 48
        }
    ),
    (
        "7. Asymmetric Moonshot (All-in $100, +25% TP, -3% SL)",
        {
            'type': "MOONSHOT_SNIPER",
            'use_dca': False,
            'tp_pct': 0.250,
            'sl_pct': 0.030,
            'be_trigger': 0.040,
            'timeout_candles': 72
        }
    ),
    (
        "8. Predator Moonshot Escalator (All-in $100, Dynamic Trail)",
        {
            'type': "PREDATOR_ESCALATOR",
            'use_dca': False,
            'tp_pct': 0.50,
            'sl_pct': 0.025,
            'timeout_candles': 48
        }
    )
]

print("\n" + "="*105)
print(" 🏁 HASIL SUPER HEAD-TO-HEAD BACKTEST: MODAL AWAL $100.00 (48 KOIN SPOT, 7.3 HARI)")
print("="*105)
print(f"{'Nama Strategi':<36} | {'Modal Awal':<10} | {'UANG AKHIR':<11} | {'ROI (%)':<9} | {'WinRate':<7} | {'PF':<5} | {'Trades':<6} | {'MaxDD':<6}")
print("-" * 105)

results = []
for name, cfg in strategies:
    res = run_simulation(name, cfg)
    results.append(res)
    print(f"{res['name']:<36} | ${100.00:<9.2f} | ${res['final_balance']:<10.2f} | {res['roi']:+8.2f}% | {res['win_rate']:5.1f}% | {res['pf']:4.2f} | {res['trades']:<6} | {res['max_dd']:4.1f}%")

print("="*105 + "\n")
