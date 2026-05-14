import requests
import pandas as pd
import numpy as np

# --- WAR GAMES v31.9: GRANULAR SCORING AUDIT ---

def fetch_history(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1000"
    try:
        r = requests.get(url, timeout=10).json()
        df = pd.DataFrame(r, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
        
        # Technicals
        df['ema_9'] = df['c'].ewm(span=9).mean()
        df['ema_21'] = df['c'].ewm(span=21).mean()
        df['ema_200'] = df['c'].ewm(span=200).mean()
        df['atr'] = (df['h'] - df['l']).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (df['c'].diff().where(df['c'].diff() > 0, 0).rolling(14).mean() / -df['c'].diff().where(df['c'].diff() < 0, 0).rolling(14).mean())))
        df['vwap'] = (df['c'] * df['v']).cumsum() / df['v'].cumsum()
        
        return symbol, df.dropna()
    except: return symbol, None

def run_scenario(name, threshold, market_data, sorted_ts):
    wallet = 10.0
    active_pos = None
    trades = []
    lev = 10
    fee = 0.0006
    margin = 5.0

    for ts in sorted_ts:
        if active_pos:
            df = market_data[active_pos['sym']]
            if ts in df.index:
                row = df.loc[ts]
                exit_p = 0
                if active_pos['side'] == 'buy':
                    if row['l'] <= active_pos['sl']: exit_p = active_pos['sl']
                    elif row['h'] >= active_pos['tp']: exit_p = active_pos['tp']
                
                if exit_p > 0:
                    pnl = ((exit_p - active_pos['ent'])/active_pos['ent']) * lev * 100
                    net = (pnl/100 * margin) - (margin * lev * fee * 2)
                    wallet += net
                    trades.append(net)
                    active_pos = None
            continue

        if active_pos is None and wallet >= margin:
            candidates = []
            for sym, df in market_data.items():
                if ts not in df.index: continue
                row = df.loc[ts]
                
                # Granular Scoring (v31.9)
                ls = 0
                if row['ema_9'] > row['ema_21']: ls += 15
                if row['c'] > row['ema_200']: ls += 15
                if row['rsi'] < 45: ls += 15
                if row['c'] < row['vwap']: ls += 15
                if row['l'] < df['l'].shift(1).loc[ts] and row['c'] > df['l'].shift(1).loc[ts]: ls += 40
                
                if ls >= threshold:
                    candidates.append({'sym': sym, 'score': ls, 'row': row})
            
            if candidates:
                best = max(candidates, key=lambda x: x['score'])
                active_pos = {
                    'sym': best['sym'], 'side': 'buy', 'ent': best['row']['c'],
                    'sl': best['row']['c'] - (best['row']['c'] * 0.015), # Strict 15%
                    'tp': best['row']['c'] + (best['row']['atr'] * 4.0),
                    'margin': margin, 'peak': 0
                }

    win = len([t for t in trades if t > 0])
    wr = (win / len(trades) * 100) if trades else 0
    return {'name': name, 'wr': wr, 'trades': len(trades), 'bal': wallet}

def main():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    symbols = [s['symbol'] for s in requests.get(url).json() if s['symbol'].endswith('USDT')][:15]
    
    market_data = {}; all_ts = set()
    for s in symbols:
        sym, df = fetch_history(s)
        if df is not None:
            market_data[sym] = df; all_ts.update(df.index.tolist())
    
    sorted_ts = sorted(list(all_ts))
    
    print("\n" + "="*85)
    print("WAR GAMES v31.9: THE 80% WIN RATE AUDIT")
    print("="*85)
    print(f"{'SCENARIO':<30} | {'WIN RATE %':<12} | {'TRADES':<8} | {'FINAL BAL'}")
    print("-" * 85)
    
    scenarios = [
        ("C: AGGRESSIVE (Score > 40)", 40),
        ("B: BALANCED   (Score > 65)", 65),
        ("A: CONSERVATIVE (Score > 85)", 85)
    ]
    
    for name, threshold in scenarios:
        res = run_scenario(name, threshold, market_data, sorted_ts)
        print(f"{res['name']:<30} | {res['wr']:>10.1f}% | {res['trades']:>8} | ${res['bal']:>9.2f}")
    
    print("="*85 + "\n")

if __name__ == "__main__":
    main()
