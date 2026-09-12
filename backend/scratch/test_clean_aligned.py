import sys
if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass
import pickle
import numpy as np
import pandas as pd

with open('backend/spot_backtest_cache.pkl', 'rb') as f:
    raw_dataset = pickle.load(f)

# Filter out coin 22 (stablecoin with missing candles)
clean_dataset = [df for i, df in enumerate(raw_dataset) if i != 22]
print(f"Loaded {len(clean_dataset)} clean, perfectly timestamp-aligned coins.")

coins_data = []
for idx, df in enumerate(clean_dataset):
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
        'length': len(df)
    })

NUM_CANDLES = min(c['length'] for c in coins_data)
print(f"All coins synchronized to exact length: {NUM_CANDLES} candles ({(NUM_CANDLES*15)/(24*60):.2f} days).")

FEE = 0.001 # 0.10% each side

def simulate_spot(
    timeout_candles=24, # 6 hours max hold
    sl_pct=2.5,
    be_trigger=2.5,
    min_rvol=1.3,
    min_v_vel=0.06,
    min_cmo=20,
    max_chg=40.0,
    compound_pct=0.96
):
    cash = 100.00
    peak_cash = 100.00
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
            
            # Trailing Escalator
            if peak_pct >= 50.0:
                pos['sl'] = max(pos['sl'], pos['peak'] * 0.90)
            elif peak_pct >= 30.0:
                pos['sl'] = max(pos['sl'], ent * 1.22)
            elif peak_pct >= 18.0:
                pos['sl'] = max(pos['sl'], ent * 1.12)
            elif peak_pct >= 8.0:
                pos['sl'] = max(pos['sl'], ent * 1.05)
            elif peak_pct >= be_trigger:
                pos['sl'] = max(pos['sl'], ent * 1.004)
                
            exit_p = None
            reason = ""
            if l <= pos['sl']:
                exit_p = pos['sl']
                reason = "ESCALATOR_LOCK" if pos['sl'] > ent else "STOP_LOSS"
            elif (t - pos['entry_t']) >= timeout_candles:
                exit_p = c
                reason = "TIMEOUT_STAGNANT"
                
            if exit_p is not None:
                cost = pos['size']
                gross = (exit_p / ent) * cost
                fee = (cost * FEE) + (gross * FEE)
                net = gross - fee
                pnl = net - cost
                cash += net
                
                trades.append({
                    'coin': pos['coin_idx'],
                    'entry_t': pos['entry_t'],
                    'exit_t': t,
                    'hold_h': (t - pos['entry_t']) * 0.25,
                    'entry': ent,
                    'exit': exit_p,
                    'pct': (exit_p - ent) / ent * 100.0,
                    'peak_pct': peak_pct,
                    'cost': cost,
                    'pnl': pnl,
                    'fee': fee,
                    'cash_after': cash,
                    'reason': reason
                })
                pos = None
                
                if cash > peak_cash:
                    peak_cash = cash
                dd = (peak_cash - cash) / peak_cash * 100.0
                if dd > max_dd:
                    max_dd = dd
                continue
                
        if pos is None and cash >= 10.0:
            candidates = []
            for idx, cd in enumerate(coins_data):
                c = cd['close'][t]
                rvol = cd['rvol'][t]
                v_vel = cd['v_vel'][t]
                cmo = cd['cmo'][t]
                chg = cd['chg'][t]
                
                if (0.0 <= chg <= max_chg and 
                    rvol >= min_rvol and 
                    v_vel >= min_v_vel and 
                    cmo >= min_cmo and 
                    cd['ema9'][t] > cd['ema21'][t]):
                    sc = (rvol * 10) + cmo + (v_vel * 100)
                    candidates.append((sc, idx, c))
                    
            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                sc, best_idx, ent = candidates[0]
                slot_size = cash * compound_pct
                cash -= slot_size
                pos = {
                    'coin_idx': best_idx,
                    'entry': ent,
                    'entry_t': t,
                    'size': slot_size,
                    'peak': ent,
                    'sl': ent * (1.0 - sl_pct / 100.0)
                }
                
    if pos is not None:
        cd = coins_data[pos['coin_idx']]
        c = cd['close'][-1]
        cost = pos['size']
        gross = (c / pos['entry']) * cost
        fee = (cost * FEE) + (gross * FEE)
        net = gross - fee
        pnl = net - cost
        cash += net
        trades.append({
            'coin': pos['coin_idx'],
            'entry_t': pos['entry_t'],
            'exit_t': NUM_CANDLES - 1,
            'hold_h': (NUM_CANDLES - 1 - pos['entry_t']) * 0.25,
            'entry': pos['entry'],
            'exit': c,
            'pct': (c - pos['entry']) / pos['entry'] * 100.0,
            'peak_pct': (pos['peak'] - pos['entry']) / pos['entry'] * 100.0,
            'cost': cost,
            'pnl': pnl,
            'fee': fee,
            'cash_after': cash,
            'reason': 'FINAL_CLOSE'
        })
        
    wins = [tr for tr in trades if tr['pnl'] > 0]
    losses = [tr for tr in trades if tr['pnl'] <= 0]
    wr = len(wins) / len(trades) * 100.0 if trades else 0.0
    tot_win = sum(tr['pnl'] for tr in wins)
    tot_loss = abs(sum(tr['pnl'] for tr in losses)) if losses else 0.001
    pf = tot_win / tot_loss
    return cash, wr, pf, max_dd, len(trades), trades

bal, wr, pf, dd, nt, trs = simulate_spot()
print(f"\nSimulation Result: Final Cash = ${bal:.2f} | WR: {wr:.1f}% | PF: {pf:.2f} | MaxDD: {dd:.1f}% | Trades: {nt}")
print("\nFirst 10 and Last 5 Trades:")
for i, tr in enumerate(trs[:10] + trs[-5:]):
    flag = "[WIN]" if tr['pnl'] > 0 else "[LOSS]"
    print(f"Trade #{i+1} | Coin {tr['coin']} | Hold: {tr['hold_h']:.1f}h | Gain: {tr['pct']:+5.1f}% | PnL: ${tr['pnl']:+6.2f} | Bal: ${tr['cash_after']:.2f} | {tr['reason']}")
