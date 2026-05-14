import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def get_hot_symbols():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    try:
        r = requests.get(url).json()
        df = pd.DataFrame(r)
        df['quoteVolume'] = df['quoteVolume'].astype(float)
        df = df[df['symbol'].str.endswith('USDT')]
        return df.sort_values(by='quoteVolume', ascending=False).head(20)['symbol'].tolist()
    except: return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

def fetch_history(symbol):
    url_15m = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1000"
    url_1h = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit=500"
    try:
        r15 = requests.get(url_15m, timeout=10).json()
        df = pd.DataFrame(r15, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
        
        df['ema_9'] = df['c'].ewm(span=9).mean()
        df['ema_21'] = df['c'].ewm(span=21).mean()
        df['atr'] = (df['h'] - df['l']).rolling(14).mean()
        df['vwap'] = (df['c'] * df['v']).cumsum() / df['v'].cumsum()
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        
        r1h = requests.get(url_1h, timeout=10).json()
        df1h = pd.DataFrame(r1h, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        df1h['ts'] = pd.to_datetime(df1h['ts'], unit='ms')
        for col in ['o','h','l','c','v']: df1h[col] = df1h[col].astype(float)
        df1h['ema_200'] = df1h['c'].ewm(span=200).mean()
        
        return symbol, df.set_index('ts'), df1h.set_index('ts')
    except: return symbol, None, None

def run_full_simulation():
    symbols = get_hot_symbols()
    market_data = {}
    market_1h = {}
    all_ts = set()
    for s in symbols:
        sym, df, df1h = fetch_history(s)
        if df is not None:
            market_data[sym] = df
            market_1h[sym] = df1h
            all_ts.update(df.index.tolist())
    
    sorted_ts = sorted(list(all_ts))
    wallet = 10.0
    max_slots = 1
    margin_per_trade = 5.0
    lev = 10
    fee = 0.0006
    active_pos = None
    journal = []
    
    current_day = sorted_ts[0].date() if sorted_ts else datetime.now().date()
    daily_stats = []

    for ts in sorted_ts:
        if active_pos:
            df = market_data[active_pos['symbol']]
            if ts in df.index:
                row = df.loc[ts]
                cpnl = ((row['c'] - active_pos['ent'])/active_pos['ent']) * lev * 100
                if cpnl > active_pos['peak']: active_pos['peak'] = cpnl
                
                # --- STEP-TRAILING SL (Kunci Profit) ---
                if active_pos['peak'] >= 10:
                    locked = (int(active_pos['peak'] / 10) * 10) - 5
                    new_sl = active_pos['ent'] * (1 + (locked/100)/lev)
                    if new_sl > active_pos['sl']: active_pos['sl'] = new_sl

                # Exit Logic
                exit_price = 0
                if row['l'] <= active_pos['sl']: exit_price = active_pos['sl']
                elif row['h'] >= active_pos['tp']: exit_price = active_pos['tp']
                
                if exit_price > 0:
                    f_pnl = ((exit_price - active_pos['ent'])/active_pos['ent']) * lev * 100
                    net = (f_pnl/100 * active_pos['margin']) - (active_pos['margin'] * lev * fee * 2)
                    wallet += net
                    journal.append({'ts': ts, 'sym': active_pos['symbol'], 'net': net, 'bal': wallet})
                    active_pos = None
            continue

        if active_pos is None and wallet >= margin_per_trade:
            candidates = []
            for sym, df in market_data.items():
                if ts not in df.index: continue
                row = df.loc[ts]
                
                ema9 = row['ema_9']
                ema21 = row['ema_21']
                atr = row['atr']
                rsi = row['rsi']
                vwap = row['vwap']
                rvol = (df['v'] / df['v'].rolling(20).mean()).loc[ts]
                
                ts_1h = ts.replace(minute=0, second=0, microsecond=0)
                trend_1h = 'NEUTRAL'
                if sym in market_1h and ts_1h in market_1h[sym].index:
                    row1h = market_1h[sym].loc[ts_1h]
                    trend_1h = 'BULLISH' if row1h['c'] > row1h['ema_200'] else 'BEARISH'
                
                ls = 0
                if ema9 > ema21: ls += 20
                if trend_1h == 'BULLISH': ls += 20
                if rvol > 1.8: ls += 20
                if row['c'] > vwap: ls += 20 
                if 50 <= rsi <= 65: ls += 20 
                
                # DNA Match Bonus
                if ema9 > ema21 and row['c'] > vwap and 50 <= rsi <= 65:
                    ls += 100

                if ls >= 65:
                    sl_dist = min(atr * 1.5, row['c'] * 0.015)
                    candidates.append({
                        'sym': sym, 'score': ls, 'row': row, 
                        'sl': row['c'] - sl_dist, 'tp': row['c'] + (atr * 4.0)
                    })
            
            if candidates:
                best = max(candidates, key=lambda x: x['score'])
                active_pos = {
                    'symbol': best['sym'], 'side': 'buy', 'ent': best['row']['c'],
                    'peak': 0, 'sl': best['sl'], 'tp': best['tp'], 'margin': margin_per_trade
                }

        if ts.date() > current_day:
            day_j = [j for j in journal if j['ts'].date() == current_day]
            daily_stats.append({'date': current_day, 'trades': len(day_j), 'pnl': sum([x['net'] for x in day_j]), 'bal': wallet})
            current_day = ts.date()

    return daily_stats, journal

def main():
    print("\n" + "="*80)
    print("JOURNAL TRADING v32.1: THE WINNING DNA + TRAILING SL")
    print("="*80)
    summary, journal = run_full_simulation()
    for s in summary:
        color = "+" if s['pnl'] >= 0 else ""
        print(f"{s['date']} | Trades: {s['trades']} | PnL: {color}${s['pnl']:.2f} | Bal: ${s['bal']:.2f}")
    
    if summary:
        print(f"\nFINAL BAL: ${summary[-1]['bal']:.2f}")

if __name__ == "__main__":
    main()



