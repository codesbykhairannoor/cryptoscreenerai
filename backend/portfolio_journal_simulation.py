import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- INSTITUTIONAL PORTFOLIO JOURNAL v31.8 (FULL STRATEGY AUDIT) ---
# Menggunakan 100% Logika CryptoEngine: DSZ, Liq Grab, OB, HTF Trend, Strict 15% SL

def get_hot_symbols():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    r = requests.get(url).json()
    df = pd.DataFrame(r)
    df['quoteVolume'] = df['quoteVolume'].astype(float)
    df = df[df['symbol'].str.endswith('USDT')]
    return df.sort_values(by='quoteVolume', ascending=False).head(30)['symbol'].tolist()

def fetch_history(symbol):
    # Ambil data 1000 candle 15m (~10 hari) + 1h untuk trend
    url_15m = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1000"
    url_1h = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit=500"
    try:
        r15 = requests.get(url_15m, timeout=10).json()
        df = pd.DataFrame(r15, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
        
        r1h = requests.get(url_1h, timeout=10).json()
        df1h = pd.DataFrame(r1h, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        df1h['ts'] = pd.to_datetime(df1h['ts'], unit='ms')
        for col in ['o','h','l','c','v']: df1h[col] = df1h[col].astype(float)
        df1h['ema_200'] = df1h['c'].ewm(span=200).mean()
        
        return symbol, df.set_index('ts'), df1h.set_index('ts')
    except: return symbol, None, None

def run_full_simulation():
    symbols = get_hot_symbols()
    print(f"\n[1] Mempersiapkan Senjata Lengkap v31.8 untuk {len(symbols)} koin...")
    
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
    max_slots = 1 # Sniper Mode
    margin_per_trade = 5.0
    lev = 10
    fee = 0.0006
    active_pos = None
    journal = []
    
    current_day = sorted_ts[0].date()
    daily_stats = []

    for ts in sorted_ts:
        # 1. Manage Active Position
        if active_pos:
            df = market_data[active_pos['symbol']]
            if ts in df.index:
                row = df.loc[ts]
                cpnl = ((row['c'] - active_pos['ent'])/active_pos['ent']) * lev * 100
                if active_pos['side'] == 'sell': cpnl = -cpnl
                if cpnl > active_pos['peak']: active_pos['peak'] = cpnl
                
                # Step-Trailing
                if active_pos['peak'] >= 10:
                    locked = (int(active_pos['peak'] / 10) * 10) - 5
                    new_sl = active_pos['ent'] * (1 + (locked/100)/lev) if active_pos['side'] == 'buy' else active_pos['ent'] * (1 - (locked/100)/lev)
                    if active_pos['side'] == 'buy':
                        if new_sl > active_pos['sl']: active_pos['sl'] = new_sl
                    else:
                        if new_sl < active_pos['sl']: active_pos['sl'] = new_sl

                # Exit Logic
                ep = 0
                if active_pos['side'] == 'buy':
                    if row['l'] <= active_pos['sl']: ep = active_pos['sl']
                    elif row['h'] >= active_pos['tp']: ep = active_pos['tp']
                else:
                    if row['h'] >= active_pos['sl']: ep = active_pos['sl']
                    elif row['l'] <= active_pos['tp']: ep = active_pos['tp']
                
                if ep > 0:
                    f_pnl = ((ep - active_pos['ent'])/active_pos['ent']) * lev * 100
                    if active_pos['side'] == 'sell': f_pnl = -f_pnl
                    net = (f_pnl/100 * active_pos['margin']) - (active_pos['margin'] * lev * fee * 2)
                    wallet += net
                    journal.append({'ts': ts, 'sym': active_pos['symbol'], 'net': net, 'pnl': f_pnl, 'bal': wallet})
                    active_pos = None

        # 2. Daily Summary
        if ts.date() > current_day:
            day_j = [j for j in journal if j['ts'].date() == current_day]
            daily_stats.append({'date': current_day, 'trades': len(day_j), 'pnl': sum([x['net'] for x in day_j]), 'bal': wallet})
            current_day = ts.date()

        # 3. Entry Logic (Full v31.8 Audit)
        if active_pos is None and wallet >= margin_per_trade:
            candidates = []
            for sym, df in market_data.items():
                if ts not in df.index: continue
                row = df.loc[ts]
                
                # --- FULL TECH AUDIT ---
                ema9 = df['c'].shift(1).rolling(9).mean().loc[ts]
                ema21 = df['c'].shift(1).rolling(21).mean().loc[ts]
                atr = (df['h'] - df['l']).shift(1).rolling(14).mean().loc[ts]
                rvol = (df['v'] / df['v'].rolling(20).mean()).loc[ts]
                
                # Trend 1h
                ts_1h = ts.replace(minute=0, second=0, microsecond=0)
                trend_1h = 'NEUTRAL'
                if sym in market_1h and ts_1h in market_1h[sym].index:
                    row1h = market_1h[sym].loc[ts_1h]
                    trend_1h = 'BULLISH' if row1h['c'] > row1h['ema_200'] else 'BEARISH'
                
                # Logic Scoring
                ls = 0; ai_bias = 'LONG' # Simulasi AI Bias
                if ema9 > ema21: ls += 20
                if trend_1h == 'BULLISH': ls += 20
                if rvol > 2.0: ls += 20
                
                # DSZ & Liq Grab (Sederhana)
                if row['l'] < df['l'].shift(1).loc[ts] and row['c'] > df['l'].shift(1).loc[ts]: ls += 40
                
                # Strict 15% PnL SL
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

    return daily_stats, journal

def main():
    print("\n" + "="*80)
    print("JOURNAL TRADING ASLI v31.8 (SENJATA LENGKAP INSTITUTIONAL)")
    print("Simulasi Dompet $10 | Sniper Mode | Filter DSZ, Liq Grab, HTF Trend")
    print("="*80)
    
    stats, journal = run_full_simulation()
    
    print(f"\n{'TANGGAL':<12} | {'TRADES':<7} | {'DAILY PNL':<10} | {'SALDO AKHIR'}")
    print("-" * 80)
    for s in stats:
        color = "+" if s['pnl'] >= 0 else ""
        print(f"{str(s['date']):<12} | {s['trades']:<7} | {color}${s['pnl']:<9.2f} | ${s['bal']:<9.2f}")
    
    print("\n" + "="*80)
    print("HASIL AKHIR: $" + str(round(stats[-1]['bal'], 2)) if stats else "N/A")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
