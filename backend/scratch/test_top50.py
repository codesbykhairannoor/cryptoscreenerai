import requests
import concurrent.futures
import time
import sys
import numpy as np
import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

print("="*90)
print(" 🚀 DOWNLOADING WIDE UNIVERSE SPOT CANDLES (TOP 150 LIQUID PAIRS) ")
print("="*90)

# 1. Fetch Tickers
r = requests.get('https://api.gateio.ws/api/v4/spot/tickers', timeout=8)
tickers = [t for t in r.json() if t['currency_pair'].endswith('_USDT')]
# Filter min volume $400,000 to avoid illiquid dead coins
tickers = [t for t in tickers if float(t.get('quote_volume', 0) or 0) >= 400000]
tickers.sort(key=lambda x: float(x.get('quote_volume', 0) or 0), reverse=True)
pairs_to_fetch = [t['currency_pair'] for t in tickers[:50]]

print(f"[*] Total koin terpilih untuk universe luas: {len(pairs_to_fetch)} koin spot.")
print(f"[*] Mengunduh 800 candle 15M (~8.3 hari) secara paralel...", flush=True)

t0 = time.time()

def fetch_pair_data(pair):
    url = f'https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}&interval=15m&limit=800'
    try:
        res = requests.get(url, timeout=6)
        if res.status_code == 200:
            data = res.json()
            if len(data) >= 500:
                # Gate.io: [ts, quote_vol, close, high, low, open, base_vol, closed]
                df = pd.DataFrame(data, columns=['ts', 'quote_vol', 'close', 'high', 'low', 'open', 'vol', 'closed'])
                df[['close', 'high', 'low', 'open', 'vol']] = df[['close', 'high', 'low', 'open', 'vol']].astype(float)
                df['ts'] = df['ts'].astype(int)
                df = df.sort_values('ts').reset_index(drop=True)
                return pair, df
    except:
        pass
    return pair, None

raw_data = []
with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
    results = list(ex.map(fetch_pair_data, pairs_to_fetch))

for pair, df in results:
    if df is not None:
        raw_data.append((pair, df))

t1 = time.time()
print(f"[+] Selesai! Berhasil mengunduh {len(raw_data)} koin spot dalam {round(t1 - t0, 1)} detik.")

# Precompute Indicators
coins_data = []
for pair, df in raw_data:
    # BB
    bb_mid = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    bb_up = bb_mid + (bb_std * 2.0)
    bb_low = bb_mid - (bb_std * 2.0)
    
    # EMA 50
    ema50 = df['close'].ewm(span=50, adjust=False).mean()
    
    # Volume Velocity: 1h / 24h
    vol_1h = df['vol'].rolling(4).sum()
    vol_24h = df['vol'].rolling(96).sum()
    vol_vel = vol_1h / (vol_24h + 1e-9)
    
    # RVOL
    avg_vol_20 = df['vol'].rolling(20).mean()
    rvol = df['vol'] / (avg_vol_20 + 1e-9)
    
    # CMO
    diff = df['close'].diff()
    up = diff.clip(lower=0)
    down = (-diff).clip(lower=0)
    sum_up = up.rolling(14).sum()
    sum_down = down.rolling(14).sum()
    cmo = 100 * (sum_up - sum_down) / (sum_up + sum_down + 1e-9)
    
    # 24h Change proxy (96 candles)
    chg_24h = (df['close'] - df['close'].shift(96)) / (df['close'].shift(96) + 1e-9) * 100.0
    
    # Wick ratio
    body = (df['close'] - df['open']).abs()
    lower_wick = df[['close', 'open']].min(axis=1) - df['low']
    wick_ratio = lower_wick / (body + 1e-9)
    
    trend_bull = (df['close'] > ema50) & (df['close'] > bb_mid)
    
    coins_data.append({
        'pair': pair,
        'high': df['high'].to_numpy(dtype=float),
        'low': df['low'].to_numpy(dtype=float),
        'close': df['close'].to_numpy(dtype=float),
        'open': df['open'].to_numpy(dtype=float),
        'rvol': rvol.to_numpy(dtype=float),
        'v_vel': vol_vel.to_numpy(dtype=float),
        'cmo': cmo.to_numpy(dtype=float),
        'chg': chg_24h.to_numpy(dtype=float),
        'wick': wick_ratio.to_numpy(dtype=float),
        'bb_up': bb_up.to_numpy(dtype=float),
        'bb_low': bb_low.to_numpy(dtype=float),
        'trend_bull': trend_bull.to_numpy(dtype=bool),
        'length': len(df)
    })

NUM_CANDLES = min(c['length'] for c in coins_data)
FEE = 0.0010 # 0.10% buy + 0.10% sell = 0.20% round-trip

print(f"[*] Panjang lilin candle yang disinkronkan: {NUM_CANDLES} candle 15M ({round(NUM_CANDLES * 15 / 60 / 24, 1)} hari).")
print(f"[*] Memulai simulasi portofolio sekuensial saldo $100.00...\n")

def simulate_strat(name, use_escalator=True, tp_pct=0.009, sl_pct=0.025):
    balance = 100.00
    peak_bal = 100.00
    max_dd = 0.0
    trades = []
    pos = None
    
    for t in range(96, NUM_CANDLES):
        if pos is not None:
            cd = coins_data[pos['coin_idx']]
            h, l, c = cd['high'][t], cd['low'][t], cd['close'][t]
            ent = pos['entry']
            if h > pos['peak_price']: pos['peak_price'] = h
            peak_gain = (pos['peak_price'] - ent) / ent * 100.0
            
            if use_escalator:
                # Dynamic Moonshot Escalator
                if peak_gain >= 35.0:
                    pos['current_sl'] = max(pos['current_sl'], ent * 1.25)
                elif peak_gain >= 18.0:
                    pos['current_sl'] = max(pos['current_sl'], ent * 1.12)
                elif peak_gain >= 10.0:
                    pos['current_sl'] = max(pos['current_sl'], ent * 1.07)
                elif peak_gain >= 5.5:
                    pos['current_sl'] = max(pos['current_sl'], ent * 1.032)
                elif peak_gain >= 2.5:
                    pos['current_sl'] = max(pos['current_sl'], ent * 1.005)
                    
                if peak_gain >= 50.0:
                    pos['current_sl'] = max(pos['current_sl'], pos['peak_price'] * 0.92)
                    
                exit_price = None
                exit_reason = None
                if l <= pos['current_sl']:
                    exit_price = pos['current_sl']
                    exit_reason = "Escalator Lock" if pos['current_sl'] > ent else "Initial SL"
                elif t - pos['entry_t'] >= 48: # 12 jam timeout
                    exit_price = c
                    exit_reason = "Timeout 12h"
                    
                if exit_price is not None:
                    raw_pnl = (exit_price - ent) / ent * 100.0
                    cost = pos['size']
                    fee_usd = cost * (FEE * 2)
                    pnl_usd = cost * (raw_pnl / 100.0) - fee_usd
                    balance += pnl_usd
                    trades.append({'pnl_usd': pnl_usd, 'pnl_pct': raw_pnl, 'peak_pct': peak_gain, 'reason': exit_reason})
                    if balance > peak_bal: peak_bal = balance
                    dd = (peak_bal - balance) / peak_bal * 100.0
                    if dd > max_dd: max_dd = dd
                    pos = None
                    continue
            else:
                # Fixed TP model
                tp_price = ent * (1.0 + tp_pct)
                sl_price = ent * (1.0 - sl_pct)
                exit_price = None
                exit_reason = None
                if h >= tp_price:
                    exit_price = tp_price
                    exit_reason = "TP"
                elif l <= sl_price:
                    exit_price = sl_price
                    exit_reason = "SL"
                elif t - pos['entry_t'] >= 48:
                    exit_price = c
                    exit_reason = "Timeout"
                    
                if exit_price is not None:
                    raw_pnl = (exit_price - ent) / ent * 100.0
                    cost = pos['size']
                    fee_usd = cost * (FEE * 2)
                    pnl_usd = cost * (raw_pnl / 100.0) - fee_usd
                    balance += pnl_usd
                    trades.append({'pnl_usd': pnl_usd, 'pnl_pct': raw_pnl, 'peak_pct': peak_gain, 'reason': exit_reason})
                    if balance > peak_bal: peak_bal = balance
                    dd = (peak_bal - balance) / peak_bal * 100.0
                    if dd > max_dd: max_dd = dd
                    pos = None
                    continue
                    
        # If no open position, scan across the WIDE universe
        if pos is None and balance >= 10.0:
            best_c = None
            best_sc = -1
            
            for c_idx, cd in enumerate(coins_data):
                # Predator Filter:
                # 1. Bullish trend
                # 2. RVOL >= 1.8
                # 3. Volume velocity >= 0.12 (12% of 24h volume packed into 1h)
                # 4. CMO >= 35
                # 5. Healthy 24h change (0.5% s/d 18.0%)
                if (cd['trend_bull'][t] and 
                    cd['rvol'][t] >= 1.8 and 
                    cd['v_vel'][t] >= 0.12 and 
                    cd['cmo'][t] >= 35 and 
                    0.5 <= cd['chg'][t] <= 18.0):
                    
                    score = cd['rvol'][t] * 10 + cd['cmo'][t] + (cd['v_vel'][t] * 100)
                    if score > best_sc:
                        best_sc = score
                        best_c = c_idx
                        
            if best_c is not None:
                ent = coins_data[best_c]['close'][t]
                pos = {
                    'coin_idx': best_c,
                    'entry': ent,
                    'entry_t': t,
                    'size': balance * 0.95, # 95% modal all-in
                    'peak_price': ent,
                    'current_sl': ent * (1.0 - sl_pct) # -2.5% strict SL
                }
                
    wins = [tr for tr in trades if tr['pnl_usd'] > 0]
    losses = [tr for tr in trades if tr['pnl_usd'] <= 0]
    wr = len(wins) / len(trades) * 100.0 if trades else 0
    tot_p = sum(tr['pnl_usd'] for tr in wins)
    tot_l = abs(sum(tr['pnl_usd'] for tr in losses)) if losses else 0.001
    pf = tot_p / tot_l
    roi = (balance - 100.0) / 100.0 * 100.0
    big_wins = [tr for tr in trades if tr['pnl_pct'] >= 5.0]
    
    return {
        'name': name,
        'final_balance': balance,
        'roi': roi,
        'trades': len(trades),
        'wr': wr,
        'pf': pf,
        'max_dd': max_dd,
        'big_wins': len(big_wins)
    }

print("="*95)
print(f"{'Nama Strategi':<36} | {'Modal Awal':<10} | {'UANG AKHIR':<11} | {'ROI (%)':<9} | {'WinRate':<7} | {'PF':<5} | {'Trades':<6} | {'MaxDD':<6}")
print("-" * 95)

# Test 1: Fixed 0.9% Scalper
res_fix = simulate_strat("1. Fixed Scalper (+0.9% TP)", use_escalator=False, tp_pct=0.009, sl_pct=0.025)
print(f"{res_fix['name']:<36} | ${100.00:<9.2f} | ${res_fix['final_balance']:<10.2f} | {res_fix['roi']:+8.2f}% | {res_fix['wr']:5.1f}% | {res_fix['pf']:4.2f} | {res_fix['trades']:<6} | {res_fix['max_dd']:4.1f}%")

# Test 2: Fixed 5% Breakout
res_5 = simulate_strat("2. Fixed Breakout (+5.0% TP)", use_escalator=False, tp_pct=0.050, sl_pct=0.025)
print(f"{res_5['name']:<36} | ${100.00:<9.2f} | ${res_5['final_balance']:<10.2f} | {res_5['roi']:+8.2f}% | {res_5['wr']:5.1f}% | {res_5['pf']:4.2f} | {res_5['trades']:<6} | {res_5['max_dd']:4.1f}%")

# Test 3: Predator Moonshot Escalator
res_esc = simulate_strat("3. Predator Moonshot Escalator", use_escalator=True, sl_pct=0.025)
print(f"{res_esc['name']:<36} | ${100.00:<9.2f} | ${res_esc['final_balance']:<10.2f} | {res_esc['roi']:+8.2f}% | {res_esc['wr']:5.1f}% | {res_esc['pf']:4.2f} | {res_esc['trades']:<6} | {res_esc['max_dd']:4.1f}%")

print("="*95)
