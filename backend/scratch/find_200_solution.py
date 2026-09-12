import pickle
import numpy as np
import pandas as pd
import sys

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
    
    ema9 = df['close'].ewm(span=9, adjust=False).mean()
    ema21 = df['close'].ewm(span=21, adjust=False).mean()
    high_20 = df['high'].rolling(20).max()
    
    coins_data.append({
        'id': idx,
        'ts': df['ts'].to_numpy(),
        'high': df['high'].to_numpy(dtype=float),
        'low': df['low'].to_numpy(dtype=float),
        'close': df['close'].to_numpy(dtype=float),
        'open': df['open'].to_numpy(dtype=float),
        'baseVol': df['baseVol'].to_numpy(dtype=float),
        'rsi': df['rsi'].to_numpy(dtype=float),
        'rvol': df['rvol'].to_numpy(dtype=float),
        'v_vel': vol_vel.to_numpy(dtype=float),
        'cmo': cmo.to_numpy(dtype=float),
        'ema9': ema9.to_numpy(dtype=float),
        'ema21': ema21.to_numpy(dtype=float),
        'high_20': high_20.to_numpy(dtype=float),
        'trend_bull': df['trend_bullish'].to_numpy(dtype=bool),
        'chg': df['chg_24h'].to_numpy(dtype=float),
        'wick': df['lower_wick_ratio'].to_numpy(dtype=float),
        'length': len(df)
    })

NUM_CANDLES = min(c['length'] for c in coins_data)
FEE = 0.001 # 0.10% each side

def test_engine(
    entry_mode='breakout',
    timeout_candles=16,
    sl_pct=2.0,
    be_trigger=2.5,
    trail_trigger=8.0,
    trail_dist=0.03,
    min_rvol=1.5,
    min_v_vel=0.06,
    min_cmo=20,
    max_chg=30.0,
    min_chg=0.0,
    compound_ratio=0.98
):
    balance = 100.00
    peak_balance = 100.00
    max_dd = 0.0
    trades = []
    pos = None
    
    for t in range(50, NUM_CANDLES):
        if pos is not None:
            cd = coins_data[pos['coin_idx']]
            h, l, c = cd['high'][t], cd['low'][t], cd['close'][t]
            ent = pos['entry']
            if h > pos['peak']:
                pos['peak'] = h
            
            peak_pct = (pos['peak'] - ent) / ent * 100.0
            
            # Dynamic Escalator
            if peak_pct >= 50.0:
                pos['sl'] = max(pos['sl'], pos['peak'] * 0.90)
            elif peak_pct >= 30.0:
                pos['sl'] = max(pos['sl'], ent * 1.22)
            elif peak_pct >= 18.0:
                pos['sl'] = max(pos['sl'], ent * 1.12)
            elif peak_pct >= trail_trigger:
                pos['sl'] = max(pos['sl'], ent * (1.0 + (trail_trigger * 0.6) / 100.0))
            elif peak_pct >= be_trigger:
                pos['sl'] = max(pos['sl'], ent * 1.004) # Breakeven fee covered
                
            exit_p = None
            reason = ""
            if l <= pos['sl']:
                exit_p = pos['sl']
                reason = "SL/TRAIL"
            elif (t - pos['entry_t']) >= timeout_candles:
                exit_p = c
                reason = "TIMEOUT"
                
            if exit_p is not None:
                cost = pos['size']
                gross = (exit_p / ent) * cost
                fee = (cost * FEE) + (gross * FEE)
                net = gross - fee
                pnl = net - cost
                balance = (balance - cost) + net
                
                trades.append({
                    'pnl': pnl,
                    'pct': (exit_p - ent) / ent * 100.0,
                    'peak_pct': peak_pct,
                    'reason': reason,
                    'hold': t - pos['entry_t'],
                    'coin': pos['coin_idx'],
                    'bal': balance
                })
                if balance > peak_balance:
                    peak_balance = balance
                dd = (peak_balance - balance) / peak_balance * 100.0
                if dd > max_dd:
                    max_dd = dd
                pos = None
                continue
                
        if pos is None and balance >= 10.0:
            best_c = None
            best_score = -999
            
            for idx, cd in enumerate(coins_data):
                c = cd['close'][t]
                rvol = cd['rvol'][t]
                v_vel = cd['v_vel'][t]
                cmo = cd['cmo'][t]
                chg = cd['chg'][t]
                bull = cd['trend_bull'][t]
                rsi = cd['rsi'][t]
                
                signal = False
                score = 0
                
                if entry_mode == 'breakout':
                    # Volume velocity + CMO momentum
                    if (min_chg <= chg <= max_chg and 
                        rvol >= min_rvol and 
                        v_vel >= min_v_vel and 
                        cmo >= min_cmo and 
                        cd['ema9'][t] > cd['ema21'][t]):
                        signal = True
                        score = (rvol * 10) + cmo + (v_vel * 100)
                        
                elif entry_mode == 'high_break':
                    # Breakout above 20-period High with volume
                    if (c >= cd['high_20'][t-1] and 
                        rvol >= min_rvol and 
                        v_vel >= min_v_vel and 
                        min_chg <= chg <= max_chg):
                        signal = True
                        score = rvol * 10 + (v_vel * 100)
                        
                elif entry_mode == 'volume_surge':
                    # Pure volume surge with positive momentum
                    if rvol >= min_rvol and v_vel >= min_v_vel and cmo >= 10 and min_chg <= chg <= max_chg:
                        signal = True
                        score = v_vel * 100 + rvol * 10
                        
                elif entry_mode == 'dip_snipe':
                    # Dip bounce
                    if rsi <= 35 and cd['wick'][t] >= 1.2 and rvol >= 1.2 and chg >= -8.0:
                        signal = True
                        score = (35 - rsi) * 3 + cd['wick'][t] * 10
                        
                if signal and score > best_score:
                    best_score = score
                    best_c = idx
                    
            if best_c is not None:
                ent = coins_data[best_c]['close'][t]
                size = balance * compound_ratio
                pos = {
                    'coin_idx': best_c,
                    'entry': ent,
                    'entry_t': t,
                    'size': size,
                    'peak': ent,
                    'sl': ent * (1.0 - sl_pct / 100.0)
                }
                
    wins = [tr for tr in trades if tr['pnl'] > 0]
    losses = [tr for tr in trades if tr['pnl'] <= 0]
    wr = len(wins) / len(trades) * 100.0 if trades else 0.0
    tot_win = sum(tr['pnl'] for tr in wins)
    tot_loss = abs(sum(tr['pnl'] for tr in losses)) if losses else 0.001
    pf = tot_win / tot_loss
    return balance, wr, pf, max_dd, len(trades), trades

print("Testing configurations...")
grid = []
for mode in ['breakout', 'high_break', 'volume_surge']:
    for timeout in [8, 12, 16, 24, 36]:
        for sl in [1.5, 2.0, 2.5, 3.0]:
            for rv in [1.3, 1.6, 2.0]:
                for vv in [0.06, 0.09, 0.12]:
                    for mx_chg in [25.0, 40.0, 60.0]:
                        b, wr, pf, dd, nt, trs = test_engine(
                            entry_mode=mode,
                            timeout_candles=timeout,
                            sl_pct=sl,
                            min_rvol=rv,
                            min_v_vel=vv,
                            max_chg=mx_chg
                        )
                        if b > 115.0:
                            grid.append((b, wr, pf, dd, nt, mode, timeout, sl, rv, vv, mx_chg))

grid.sort(key=lambda x: x[0], reverse=True)
print(f"Total winning configs with > $115 balance: {len(grid)}")
print("\nTOP 15 BEST CONFIGS:")
for g in grid[:15]:
    print(f"Final: ${g[0]:.2f} (+{g[0]-100:.1f}%) | WR: {g[1]:.1f}% | PF: {g[2]:.2f} | DD: {g[3]:.1f}% | Tr: {g[4]} | Mode:{g[5]} TO:{g[6]*15/60:.1f}h SL:{g[7]}% RVOL:{g[8]} V-Vel:{g[9]} MaxChg:{g[10]}%")
