import pickle
import numpy as np
import pandas as pd

with open('backend/spot_backtest_cache.pkl', 'rb') as f:
    raw_dataset = pickle.load(f)

# Precompute data for 48 coins
coins_data = []
for idx, df in enumerate(raw_dataset):
    df = df.sort_values('ts').reset_index(drop=True)
    
    # Volume Velocity: 1h (4 candles) / 24h (96 candles)
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
    
    # KC & BB Squeeze
    kc_mid = df['close'].ewm(span=20, adjust=False).mean()
    kc_upper = kc_mid + (1.5 * df['atr'])
    kc_lower = kc_mid - (1.5 * df['atr'])
    squeeze_on = (df['bb_low'] > kc_lower) & (df['bb_up'] < kc_upper)
    squeeze_fired = squeeze_on.shift(1).rolling(6).max() == 1
    
    coins_data.append({
        'id': idx,
        'high': df['high'].to_numpy(dtype=float),
        'low': df['low'].to_numpy(dtype=float),
        'close': df['close'].to_numpy(dtype=float),
        'open': df['open'].to_numpy(dtype=float),
        'rsi': df['rsi'].to_numpy(dtype=float),
        'rvol': df['rvol'].to_numpy(dtype=float),
        'v_vel': vol_vel.to_numpy(dtype=float),
        'cmo': cmo.to_numpy(dtype=float),
        'squeeze_fired': squeeze_fired.to_numpy(dtype=bool),
        'trend_bull': df['trend_bullish'].to_numpy(dtype=bool),
        'chg': df['chg_24h'].to_numpy(dtype=float),
        'wick': df['lower_wick_ratio'].to_numpy(dtype=float),
        'bb_low': df['bb_low'].to_numpy(dtype=float),
        'length': len(df)
    })

NUM_CANDLES = min(c['length'] for c in coins_data)
FEE = 0.001 # 0.10% buy + 0.10% sell = 0.20% roundtrip

def run_backtest_with_escalator(
    use_escalator=True, 
    min_cmo=35, 
    min_v_vel=0.12, 
    min_rvol=1.8, 
    initial_sl_pct=2.5,
    be_trigger=2.5,
    be_lock=0.5,
    t1_trig=6.0, t1_lock=3.5,
    t2_trig=12.0, t2_lock=8.0,
    t3_trig=20.0, t3_lock=14.0,
    t4_trig=35.0, t4_lock=25.0,
    trail_pct=8.0,
    fixed_tp_pct=0.9
):
    balance = 100.00
    peak_balance = 100.00
    max_dd = 0.0
    trades = []
    
    pos = None
    
    for t in range(50, NUM_CANDLES):
        if pos is not None:
            c_idx = pos['coin_idx']
            cd = coins_data[c_idx]
            h = cd['high'][t]
            l = cd['low'][t]
            c = cd['close'][t]
            ent = pos['entry']
            
            # Track peak price
            if h > pos['peak_price']:
                pos['peak_price'] = h
                
            peak_gain_pct = (pos['peak_price'] - ent) / ent * 100.0
            
            if use_escalator:
                # Escalator Ratchet
                if peak_gain_pct >= t4_trig:
                    locked_sl = ent * (1.0 + t4_lock / 100.0)
                    pos['current_sl'] = max(pos['current_sl'], locked_sl)
                elif peak_gain_pct >= t3_trig:
                    locked_sl = ent * (1.0 + t3_lock / 100.0)
                    pos['current_sl'] = max(pos['current_sl'], locked_sl)
                elif peak_gain_pct >= t2_trig:
                    locked_sl = ent * (1.0 + t2_lock / 100.0)
                    pos['current_sl'] = max(pos['current_sl'], locked_sl)
                elif peak_gain_pct >= t1_trig:
                    locked_sl = ent * (1.0 + t1_lock / 100.0)
                    pos['current_sl'] = max(pos['current_sl'], locked_sl)
                elif peak_gain_pct >= be_trigger:
                    locked_sl = ent * (1.0 + be_lock / 100.0)
                    pos['current_sl'] = max(pos['current_sl'], locked_sl)
                
                # If above 50%, trail from peak
                if peak_gain_pct >= 50.0:
                    trail_sl = pos['peak_price'] * (1.0 - trail_pct / 100.0)
                    pos['current_sl'] = max(pos['current_sl'], trail_sl)
                
                # Check exit
                exit_price = None
                exit_reason = None
                
                # Did low touch current SL?
                if l <= pos['current_sl']:
                    exit_price = pos['current_sl']
                    exit_reason = "Escalator SL" if pos['current_sl'] > ent else "Initial SL"
                elif t - pos['entry_t'] >= 48: # 12 hours timeout
                    exit_price = c
                    exit_reason = "Time Exit"
                    
                if exit_price is not None:
                    # Calculate net PnL
                    raw_pnl_pct = (exit_price - ent) / ent * 100.0
                    cost = pos['size_usd']
                    pnl_usd = cost * (raw_pnl_pct / 100.0) - (cost * (FEE * 2))
                    balance += pnl_usd
                    trades.append({
                        'coin': c_idx,
                        'pnl_usd': pnl_usd,
                        'pnl_pct': raw_pnl_pct,
                        'peak_pct': peak_gain_pct,
                        'reason': exit_reason
                    })
                    if balance > peak_balance: peak_balance = balance
                    dd = (peak_balance - balance) / peak_balance * 100.0
                    if dd > max_dd: max_dd = dd
                    pos = None
                    continue
            else:
                # Fixed TP model
                tp_price = ent * (1.0 + fixed_tp_pct / 100.0)
                sl_price = ent * (1.0 - initial_sl_pct / 100.0)
                exit_price = None
                exit_reason = None
                if h >= tp_price:
                    exit_price = tp_price
                    exit_reason = "Fixed TP"
                elif l <= sl_price:
                    exit_price = sl_price
                    exit_reason = "SL"
                elif t - pos['entry_t'] >= 48:
                    exit_price = c
                    exit_reason = "Time Exit"
                    
                if exit_price is not None:
                    raw_pnl_pct = (exit_price - ent) / ent * 100.0
                    cost = pos['size_usd']
                    pnl_usd = cost * (raw_pnl_pct / 100.0) - (cost * (FEE * 2))
                    balance += pnl_usd
                    trades.append({
                        'coin': c_idx,
                        'pnl_usd': pnl_usd,
                        'pnl_pct': raw_pnl_pct,
                        'peak_pct': peak_gain_pct,
                        'reason': exit_reason
                    })
                    if balance > peak_balance: peak_balance = balance
                    dd = (peak_balance - balance) / peak_balance * 100.0
                    if dd > max_dd: max_dd = dd
                    pos = None
                    continue
                    
        # If no open position, scan for candidates
        if pos is None:
            best_candidate = None
            best_score = -1
            
            for c_idx, cd in enumerate(coins_data):
                # Filter conditions:
                # 1. Bullish trend
                # 2. RVOL >= min_rvol
                # 3. Volume velocity >= min_v_vel
                # 4. CMO >= min_cmo
                # 5. Healthy 24h change (0.5% to 18%)
                if (cd['trend_bull'][t] and 
                    cd['rvol'][t] >= min_rvol and 
                    cd['v_vel'][t] >= min_v_vel and 
                    cd['cmo'][t] >= min_cmo and 
                    0.5 <= cd['chg'][t] <= 18.0):
                    
                    score = cd['rvol'][t] * 10 + cd['cmo'][t] + (cd['v_vel'][t] * 100)
                    if score > best_score:
                        best_score = score
                        best_candidate = c_idx
                        
            if best_candidate is not None:
                cd = coins_data[best_candidate]
                ent = cd['close'][t]
                trade_size = balance * 0.95 # Invest 95% of available $100
                pos = {
                    'coin_idx': best_candidate,
                    'entry': ent,
                    'entry_t': t,
                    'size_usd': trade_size,
                    'peak_price': ent,
                    'current_sl': ent * (1.0 - initial_sl_pct / 100.0)
                }
                
    # Summary
    if trades:
        win_trades = [tr for tr in trades if tr['pnl_usd'] > 0]
        loss_trades = [tr for tr in trades if tr['pnl_usd'] <= 0]
        wr = len(win_trades) / len(trades) * 100.0
        tot_profit = sum(tr['pnl_usd'] for tr in win_trades)
        tot_loss = abs(sum(tr['pnl_usd'] for tr in loss_trades)) if loss_trades else 0.001
        pf = tot_profit / tot_loss
        big_wins = [tr for tr in trades if tr['pnl_pct'] >= 5.0]
        return {
            'final_balance': balance,
            'net_roi_pct': (balance - 100.0) / 100.0 * 100.0,
            'trades_count': len(trades),
            'win_rate': wr,
            'profit_factor': pf,
            'max_dd': max_dd,
            'big_wins_count': len(big_wins),
            'avg_win_pct': np.mean([tr['pnl_pct'] for tr in win_trades]) if win_trades else 0
        }
    return {'final_balance': balance, 'net_roi_pct': 0, 'trades_count': 0, 'win_rate': 0, 'profit_factor': 0, 'max_dd': 0}

print("=== RUNNING BENCHMARKS ===")
res_fixed = run_backtest_with_escalator(use_escalator=False, fixed_tp_pct=0.9, initial_sl_pct=2.5)
print(f"Fixed 0.9% TP: Balance ${res_fixed['final_balance']:.2f} ({res_fixed['net_roi_pct']:+.2f}%) | Trades: {res_fixed['trades_count']} | WR: {res_fixed['win_rate']:.1f}% | PF: {res_fixed['profit_factor']:.2f} | MaxDD: {res_fixed['max_dd']:.2f}% | BigWins: {res_fixed['big_wins_count']}")

res_esc = run_backtest_with_escalator(use_escalator=True, initial_sl_pct=2.5, be_trigger=2.5, be_lock=0.5, t1_trig=5.5, t1_lock=3.2, t2_trig=10.0, t2_lock=7.0, t3_trig=18.0, t3_lock=12.0)
print(f"Moonshot Escalator: Balance ${res_esc['final_balance']:.2f} ({res_esc['net_roi_pct']:+.2f}%) | Trades: {res_esc['trades_count']} | WR: {res_esc['win_rate']:.1f}% | PF: {res_esc['profit_factor']:.2f} | MaxDD: {res_esc['max_dd']:.2f}% | BigWins: {res_esc['big_wins_count']} | AvgWin: {res_esc['avg_win_pct']:.2f}%")
