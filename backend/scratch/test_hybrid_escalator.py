import pickle
import numpy as np
import pandas as pd

with open('backend/spot_backtest_cache.pkl', 'rb') as f:
    raw_dataset = pickle.load(f)

coins_data = []
for idx, df in enumerate(raw_dataset):
    df = df.sort_values('ts').reset_index(drop=True)
    vol_1h = df['baseVol'].rolling(4).sum()
    vol_24h = df['baseVol'].rolling(96).sum()
    vol_vel = vol_1h / (vol_24h + 1e-9)
    
    diff = df['close'].diff()
    up = diff.clip(lower=0)
    down = (-diff).clip(lower=0)
    sum_up = up.rolling(14).sum()
    sum_down = down.rolling(14).sum()
    cmo = 100 * (sum_up - sum_down) / (sum_up + sum_down + 1e-9)
    
    # BB Lower and Upper
    bb_mid = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    bb_lower = bb_mid - (bb_std * 2.0)
    
    # KC
    kc_mid = df['close'].ewm(span=20, adjust=False).mean()
    kc_upper = kc_mid + (1.5 * df['atr'])
    kc_lower = kc_mid - (1.5 * df['atr'])
    squeeze_on = (bb_lower > kc_lower) & (df['bb_up'] < kc_upper)
    squeeze_fired = squeeze_on.shift(1).rolling(6).max() == 1
    
    coins_data.append({
        'id': idx,
        'high': df['high'].to_numpy(dtype=float),
        'low': df['low'].to_numpy(dtype=float),
        'close': df['close'].to_numpy(dtype=float),
        'rsi': df['rsi'].to_numpy(dtype=float),
        'rvol': df['rvol'].to_numpy(dtype=float),
        'v_vel': vol_vel.to_numpy(dtype=float),
        'cmo': cmo.to_numpy(dtype=float),
        'squeeze_fired': squeeze_fired.to_numpy(dtype=bool),
        'trend_bull': df['trend_bullish'].to_numpy(dtype=bool),
        'chg': df['chg_24h'].to_numpy(dtype=float),
        'wick': df['lower_wick_ratio'].to_numpy(dtype=float),
        'bb_low': bb_lower.to_numpy(dtype=float),
        'bb_up': df['bb_up'].to_numpy(dtype=float),
        'length': len(df)
    })

NUM_CANDLES = min(c['length'] for c in coins_data)
FEE = 0.001 # 0.20% roundtrip

def simulate_hybrid(strat="dual"):
    balance = 100.00
    peak_bal = 100.00
    max_dd = 0.0
    trades = []
    pos = None
    
    for t in range(50, NUM_CANDLES):
        if pos is not None:
            cd = coins_data[pos['coin_idx']]
            h, l, c = cd['high'][t], cd['low'][t], cd['close'][t]
            ent = pos['entry']
            if h > pos['peak_price']: pos['peak_price'] = h
            peak_pct = (pos['peak_price'] - ent) / ent * 100.0
            
            # Trailing Moonshot Escalator
            # Tier 4: Moonshot at +35% -> lock +25%
            if peak_pct >= 35.0:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.25)
            # Tier 3: at +20% -> lock +14%
            elif peak_pct >= 20.0:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.14)
            # Tier 2: at +12% -> lock +8.0%
            elif peak_pct >= 12.0:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.08)
            # Tier 1: at +6.0% -> lock +3.5%
            elif peak_pct >= 6.0:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.035)
            # Breakeven: at +2.5% -> lock +0.5% (covers all CEX fees!)
            elif peak_pct >= 2.5:
                pos['current_sl'] = max(pos['current_sl'], ent * 1.005)
                
            # Trailing stop above 45%
            if peak_pct >= 45.0:
                pos['current_sl'] = max(pos['current_sl'], pos['peak_price'] * 0.92)
                
            exit_p = None
            exit_reason = None
            
            # Check exit
            if l <= pos['current_sl']:
                exit_p = pos['current_sl']
                exit_reason = "Escalator SL" if pos['current_sl'] > ent else "Initial SL"
            elif t - pos['entry_t'] >= 48: # 12h timeout
                exit_p = c
                exit_reason = "Timeout 12h"
                
            if exit_p is not None:
                raw_pnl = (exit_p - ent) / ent * 100.0
                cost = pos['size']
                pnl_usd = cost * (raw_pnl / 100.0) - (cost * FEE * 2)
                balance += pnl_usd
                trades.append({
                    'coin': pos['coin_idx'],
                    'type': pos['type'],
                    'pnl_usd': pnl_usd,
                    'pnl_pct': raw_pnl,
                    'peak_pct': peak_pct,
                    'reason': exit_reason
                })
                if balance > peak_bal: peak_bal = balance
                dd = (peak_bal - balance) / peak_bal * 100.0
                if dd > max_dd: max_dd = dd
                pos = None
                continue
                
        if pos is None:
            # Check candidate entries
            best_c = None
            best_sc = -1
            cand_type = None
            
            for c_idx, cd in enumerate(coins_data):
                # 1. Breakout Candidate (Predator Pompa Bandar)
                # RVOL >= 1.8, Volume Velocity >= 0.10, CMO >= 30, healthy 24h change
                is_breakout = (
                    cd['trend_bull'][t] and
                    cd['rvol'][t] >= 1.8 and
                    cd['v_vel'][t] >= 0.10 and
                    cd['cmo'][t] >= 30 and
                    0.5 <= cd['chg'][t] <= 18.0
                )
                
                # 2. NFI Dip Absorption Candidate
                # Oversold RSI <= 36 or near lower BB, long lower wick rejection >= 1.2, RVOL >= 1.1
                is_dip = (
                    cd['trend_bull'][t] and
                    (cd['rsi'][t] <= 36 or cd['close'][t] <= cd['bb_low'][t] * 1.01) and
                    cd['wick'][t] >= 1.2 and
                    cd['rvol'][t] >= 1.1 and
                    -8.0 <= cd['chg'][t] <= 16.0
                )
                
                if is_breakout:
                    sc = cd['rvol'][t] * 10 + cd['cmo'][t] + (cd['v_vel'][t] * 100)
                    if sc > best_sc:
                        best_sc = sc
                        best_c = c_idx
                        cand_type = "BREAKOUT_PUMP"
                elif is_dip and best_sc < 100: # Priority to breakout if available
                    sc = (40 - cd['rsi'][t]) * 2 + (cd['wick'][t] * 10)
                    if sc > best_sc:
                        best_sc = sc
                        best_c = c_idx
                        cand_type = "NFI_DIP"
                        
            if best_c is not None:
                ent = coins_data[best_c]['close'][t]
                pos = {
                    'coin_idx': best_c,
                    'type': cand_type,
                    'entry': ent,
                    'entry_t': t,
                    'size': balance * 0.95, # 95% of total capital
                    'peak_price': ent,
                    'current_sl': ent * 0.975 # Initial SL -2.5% ($2.50 risk on $100)
                }

    win_trades = [tr for tr in trades if tr['pnl_usd'] > 0]
    loss_trades = [tr for tr in trades if tr['pnl_usd'] <= 0]
    wr = len(win_trades) / len(trades) * 100.0 if trades else 0
    tot_p = sum(tr['pnl_usd'] for tr in win_trades)
    tot_l = abs(sum(tr['pnl_usd'] for tr in loss_trades)) if loss_trades else 0.001
    pf = tot_p / tot_l
    big_wins = [tr for tr in trades if tr['pnl_pct'] >= 5.0]
    
    print(f"=== HYBRID DUAL ENGINE + MOONSHOT ESCALATOR RESULTS ===")
    print(f"Starting Capital: $100.00")
    print(f"Final Balance:    ${balance:.2f} (Net Return: {balance-100:+.2f}%)")
    print(f"Total Trades:     {len(trades)}")
    print(f"Win Rate:         {wr:.1f}% ({len(win_trades)} W / {len(loss_trades)} L)")
    print(f"Profit Factor:    {pf:.2f}x")
    print(f"Max Drawdown:     {max_dd:.2f}%")
    print(f"Big Wins (>=5%):  {len(big_wins)}")
    print("\nSample Trades:")
    for tr in trades[:10]:
        print(f"  Coin #{tr['coin']:02d} [{tr['type']}] PnL: ${tr['pnl_usd']:+.2f} ({tr['pnl_pct']:+.2f}%) | Peak: +{tr['peak_pct']:.2f}% | Exit: {tr['reason']}")

simulate_hybrid()
