import requests
import pandas as pd
import numpy as np
from datetime import datetime

print("\n" + "="*80)
print("FINAL BACKTEST: THE TRUTH (v36.0) - ZERO FEE EDITION")
print("="*80)

def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1000"
    try:
        r = requests.get(url, timeout=10).json()
        df = pd.DataFrame(r, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        
        # Indikator Dasar
        df['atr'] = (df['h'] - df['l']).rolling(14).mean()
        df['atr_pct'] = (df['atr'] / df['c']) * 100
        df['rvol'] = df['v'] / df['v'].rolling(20).mean()
        
        # Hitung RSI
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        
        # Metrik 24 Jam untuk Kalkulasi Pump Score Lokal (96 candle 15m = 24 jam)
        df['low24h'] = df['l'].rolling(96).min()
        df['high24h'] = df['h'].rolling(96).max()
        df['vol24h'] = df['v'].rolling(96).sum() * df['c'] # Estimasi Quote Volume
        df['pct24h'] = (df['c'] - df['c'].shift(96)) / df['c'].shift(96) * 100
        df['range_pct'] = (df['high24h'] - df['low24h']) / df['low24h'] * 100
        
        return symbol, df.dropna().set_index('ts')
    except Exception: 
        return symbol, None

def calc_pump_score(row):
    score = 0.0
    rng = row['range_pct']
    vol = row['vol24h']
    price = row['c']
    high = row['high24h']
    low = row['low24h']
    pct = row['pct24h']
    rvol = row['rvol']
    
    # 1. VOLATILITAS RANGE (max 30 poin)
    if rng >= 20: score += 30
    elif rng >= 15: score += 25
    elif rng >= 10: score += 20
    elif rng >= 7: score += 15
    elif rng >= 5: score += 10
    
    # 2. VOLUME ABSOLUT (max 25 poin)
    if vol >= 100000000: score += 25
    elif vol >= 50000000: score += 20
    elif vol >= 20000000: score += 15
    elif vol >= 10000000: score += 10
    
    # 3. POSISI HARGA (max 25 poin)
    if high > low:
        pos = (price - low) / (high - low) * 100
        if rvol >= 3.0:
            if pos >= 80: score += 25
            elif 50 <= pos < 80: score += 15
        else:
            if 10 <= pos <= 35: score += 25
            elif 35 < pos <= 50: score += 18
            
    # 4. MOMENTUM (max 40 poin)
    if rvol >= 5.0: score += 40
    elif rvol >= 3.0: score += 30
    elif rvol >= 2.0: score += 15
    
    if 1.5 <= pct <= 6: score += 20
    elif 0.5 <= pct < 1.5: score += 12
    elif 6 < pct <= 12: score += 8
    elif pct < 0: score += 5
    
    return min(100, score)

def run_simulation():
    # Gunakan 20 koin teratas
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr").json()
        df_tickers = pd.DataFrame(r)
        df_tickers['quoteVolume'] = df_tickers['quoteVolume'].astype(float)
        symbols = df_tickers[df_tickers['symbol'].str.endswith('USDT')].sort_values(by='quoteVolume', ascending=False).head(20)['symbol'].tolist()
    except:
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    market_data = {}
    all_ts = set()
    for s in symbols:
        sym, df = fetch_data(s)
        if df is not None:
            market_data[sym] = df
            all_ts.update(df.index.tolist())
            
    sorted_ts = sorted(list(all_ts))
    wallet = 10.0
    margin = 5.0
    lev = 10
    active_pos = None
    trades = []
    
    for ts in sorted_ts:
        if active_pos:
            df = market_data[active_pos['sym']]
            if ts in df.index:
                row = df.loc[ts]
                
                cpnl = ((row['c'] - active_pos['ent'])/active_pos['ent']) * lev * 100
                if cpnl > active_pos['peak']: active_pos['peak'] = cpnl
                
                # --- PURE SCALPER v38.0: NO TRAILING SL ---
                # Kita biarkan Limit Order TP dan SL yang bekerja murni.
                
                # Exit Check
                ep = 0
                if row['l'] <= active_pos['sl']: ep = active_pos['sl']
                elif row['h'] >= active_pos['tp']: ep = active_pos['tp']
                
                if ep > 0:
                    f_pnl = ((ep - active_pos['ent'])/active_pos['ent']) * lev * 100
                    # Hitung Net Profit (DIKURANGI FEE BURSA $0.06 PER TRADE)
                    net = (f_pnl/100 * margin) - 0.06
                    wallet += net
                    trades.append({'sym': active_pos['sym'], 'pnl': f_pnl, 'net': net, 'ts': ts})
                    active_pos = None
            continue

        if active_pos is None and wallet >= margin:
            candidates = []
            for sym, df in market_data.items():
                if ts not in df.index: continue
                row = df.loc[ts]
                
                # --- THE HOLY GRAIL v38.0 (Crypto Engine Logic) ---
                if row.get('rsi', 0) > 65 and row['rvol'] > 2.0 and row['atr_pct'] > 0.5:
                    candidates.append({
                        'sym': sym, 'score': 100, 'row': row,
                        'sl': row['c'] * 0.95, # v39.0 CHAMPION: SL 5.0% (50% PnL)
                        'tp': row['c'] * 1.04  # v39.0 CHAMPION: TP 4.0% (40% PnL)
                    })
            
            if candidates:
                best = max(candidates, key=lambda x: x['score'])
                active_pos = {
                    'sym': best['sym'], 'ent': best['row']['c'], 'peak': 0,
                    'sl': best['sl'], 'tp': best['tp']
                }

    print(f"Total Trade        : {len(trades)}")
    if len(trades) > 0:
        win_trades = [t for t in trades if t['net'] > 0]
        wr = len(win_trades) / len(trades) * 100
        print(f"Win Rate           : {wr:.1f}%")
        print(f"Rata-rata Profit   : ${np.mean([t['net'] for t in win_trades]):.2f} per trade menang")
        if len(trades) > len(win_trades):
            loss_trades = [t for t in trades if t['net'] <= 0]
            print(f"Rata-rata Loss     : ${np.mean([t['net'] for t in loss_trades]):.2f} per trade kalah")
    
    print(f"\nSALDO AKHIR        : ${wallet:.2f} (Dari Modal $10.00)")
    print("="*80 + "\n")

if __name__ == "__main__":
    run_simulation()
