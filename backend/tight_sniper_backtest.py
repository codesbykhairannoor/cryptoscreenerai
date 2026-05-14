import requests
import pandas as pd
import numpy as np

print("\n" + "="*80)
print("BACKTEST: TIGHT SNIPER v37.0 (THE 1:5 RISK-REWARD RATIO)")
print("Target: Membuktikan Ketahanan Saldo $10 dengan SL Ketat")
print("="*80)

def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1000"
    try:
        r = requests.get(url, timeout=10).json()
        df = pd.DataFrame(r, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        df['atr'] = (df['h'] - df['l']).rolling(14).mean()
        df['atr_pct'] = (df['atr'] / df['c']) * 100
        df['rvol'] = df['v'] / df['v'].rolling(20).mean()
        
        # Simulasikan Pump Score ML Lokal
        df['low24h'] = df['l'].rolling(96).min()
        df['high24h'] = df['h'].rolling(96).max()
        df['vol24h'] = df['v'].rolling(96).sum() * df['c']
        df['pct24h'] = (df['c'] - df['c'].shift(96)) / df['c'].shift(96) * 100
        df['range_pct'] = (df['high24h'] - df['low24h']) / df['low24h'] * 100
        
        return symbol, df.dropna().set_index('ts')
    except Exception: return symbol, None

def calc_pump_score(row):
    score = 0.0
    rng, vol, price, high, low, pct, rvol = row['range_pct'], row['vol24h'], row['c'], row['high24h'], row['low24h'], row['pct24h'], row['rvol']
    if rng >= 7: score += 20
    if vol >= 20_000_000: score += 20
    if high > low:
        pos = (price - low) / (high - low) * 100
        if 10 <= pos <= 50: score += 25
    if rvol >= 2.0: score += 20
    if pct > 0: score += 15
    return min(100, score)

def run_simulation():
    # 20 koin teraktif
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr").json()
        symbols = pd.DataFrame(r).sort_values(by='quoteVolume', ascending=False).head(20)['symbol'].tolist()
        symbols = [s for s in symbols if s.endswith('USDT')]
    except: symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

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
    
    # PARAMETER TIGHT SNIPER v37.0
    SL_PCT = 0.008 # 0.8% Harga (8.0% PnL) -> Rugi $0.40
    TP_PCT = 0.040 # 4.0% Harga (40.0% PnL) -> Untung $2.00
    
    for ts in sorted_ts:
        if active_pos:
            df = market_data[active_pos['sym']]
            if ts in df.index:
                row = df.loc[ts]
                # Cek Exit
                if row['l'] <= active_pos['sl']:
                    net = -SL_PCT * lev * margin
                    wallet += net
                    trades.append(net)
                    active_pos = None
                elif row['h'] >= active_pos['tp']:
                    net = TP_PCT * lev * margin
                    wallet += net
                    trades.append(net)
                    active_pos = None
            continue

        if active_pos is None and wallet >= margin:
            for sym, df in market_data.items():
                if ts not in df.index: continue
                row = df.loc[ts]
                
                # Logic THE TRUTH
                score = calc_pump_score(row)
                if row['atr_pct'] > 0.5 and row['rvol'] > 1.2: score += 20
                else: score -= 50
                
                if score >= 75: # Sniper Entry
                    active_pos = {
                        'sym': sym, 'ent': row['c'],
                        'sl': row['c'] * (1 - SL_PCT),
                        'tp': row['c'] * (1 + TP_PCT)
                    }
                    break

    print(f"Total Trade        : {len(trades)}")
    if trades:
        win_trades = [t for t in trades if t > 0]
        print(f"Win Rate           : {len(win_trades)/len(trades)*100:.1f}%")
        print(f"Average Profit     : ${np.mean([t for t in trades if t > 0]):.2f}")
        print(f"Average Loss       : ${np.mean([t for t in trades if t <= 0]):.2f}")
    
    print(f"SALDO AKHIR        : ${wallet:.2f} (Modal: $10.00)")
    print("="*80 + "\n")

if __name__ == "__main__":
    run_simulation()
