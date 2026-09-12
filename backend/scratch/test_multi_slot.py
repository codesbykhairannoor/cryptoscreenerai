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
FEE = 0.001

def test_multi_slot(
    max_slots=2,
    timeout_candles=16,
    sl_pct=2.0,
    be_trigger=2.5,
    min_rvol=1.3,
    min_v_vel=0.06,
    min_cmo=20,
    max_chg=40.0
):
    cash = 100.00
    positions = []
    trades = []
    peak_val = 100.00
    max_dd = 0.0
    
    for t in range(50, NUM_CANDLES):
        # 1. Update active positions
        closed_indices = []
        for p_i, pos in enumerate(positions):
            cd = coins_data[pos['coin_idx']]
            h, l, c = cd['high'][t], cd['low'][t], cd['close'][t]
            ent = pos['entry']
            if h > pos['peak']:
                pos['peak'] = h
            
            peak_pct = (pos['peak'] - ent) / ent * 100.0
            
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
                cash += net
                trades.append({
                    'pnl': pnl,
                    'pct': (exit_p - ent) / ent * 100.0,
                    'peak_pct': peak_pct,
                    'reason': reason,
                    'coin': pos['coin_idx']
                })
                closed_indices.append(p_i)
                
        for p_i in sorted(closed_indices, reverse=True):
            positions.pop(p_i)
            
        # Check total portfolio value
        curr_val = cash
        for pos in positions:
            c = coins_data[pos['coin_idx']]['close'][t]
            curr_val += (c / pos['entry']) * pos['size']
        if curr_val > peak_val:
            peak_val = curr_val
        dd = (peak_val - curr_val) / peak_val * 100.0
        if dd > max_dd:
            max_dd = dd
            
        # 2. Open new positions if slots available
        open_slots = max_slots - len(positions)
        if open_slots > 0 and cash >= 10.0:
            active_coins = {p['coin_idx'] for p in positions}
            candidates = []
            
            for idx, cd in enumerate(coins_data):
                if idx in active_coins:
                    continue
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
                    
            candidates.sort(key=lambda x: x[0], reverse=True)
            for sc, c_idx, ent in candidates[:open_slots]:
                slot_size = (cash / (max_slots - len(positions))) * 0.96
                if slot_size >= 10.0 and cash >= slot_size:
                    cash -= slot_size
                    positions.append({
                        'coin_idx': c_idx,
                        'entry': ent,
                        'entry_t': t,
                        'size': slot_size,
                        'peak': ent,
                        'sl': ent * (1.0 - sl_pct / 100.0)
                    })
                    
    # Final liquidation
    for pos in positions:
        c = coins_data[pos['coin_idx']]['close'][-1]
        cost = pos['size']
        gross = (c / pos['entry']) * cost
        fee = (cost * FEE) + (gross * FEE)
        net = gross - fee
        pnl = net - cost
        cash += net
        trades.append({
            'pnl': pnl,
            'pct': (c - pos['entry']) / pos['entry'] * 100.0,
            'peak_pct': (pos['peak'] - pos['entry']) / pos['entry'] * 100.0,
            'reason': 'FINAL_CLOSE',
            'coin': pos['coin_idx']
        })
        
    wins = [tr for tr in trades if tr['pnl'] > 0]
    losses = [tr for tr in trades if tr['pnl'] <= 0]
    wr = len(wins) / len(trades) * 100.0 if trades else 0.0
    tot_win = sum(tr['pnl'] for tr in wins)
    tot_loss = abs(sum(tr['pnl'] for tr in losses)) if losses else 0.001
    pf = tot_win / tot_loss
    return cash, wr, pf, max_dd, len(trades)

print("=== MULTI-SLOT COMPARING 1 vs 2 vs 3 SLOTS ===")
for slots in [1, 2, 3]:
    for to in [12, 16, 24]:
        for sl in [1.5, 2.0, 2.5]:
            bal, wr, pf, dd, nt = test_multi_slot(max_slots=slots, timeout_candles=to, sl_pct=sl)
            print(f"Slots: {slots} | Timeout: {to*15/60:.1f}h | SL: {sl}% -> Final: ${bal:.2f} (+{bal-100:.1f}%) | WR: {wr:.1f}% | PF: {pf:.2f} | DD: {dd:.1f}% | Trades: {nt}")
