import requests
import pandas as pd
import numpy as np
from datetime import datetime

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

print("\n" + "="*80)
print("DAILY PERFORMANCE AUDIT: STRATEGI JUARA v39.0")
print("Target: Cek Ritme Trade Harian & Win Rate per Hari")
print("="*80)

def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1000"
    try:
        r = requests.get(url, timeout=10, verify=False).json()
        if not isinstance(r, list): return symbol, None
        df = pd.DataFrame(r, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        
        # Indikator
        df['atr'] = (df['h'] - df['l']).rolling(14).mean()
        df['atr_pct'] = (df['atr'] / df['c']) * 100
        df['rvol'] = df['v'] / df['v'].rolling(20).mean()
        
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        
        return symbol, df.dropna()
    except Exception as e: 
        return symbol, None

def run_daily_audit():
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", verify=False).json()
        symbols = [s['symbol'] for s in sorted(r, key=lambda x: float(x['quoteVolume']), reverse=True)[:50] if s['symbol'].endswith('USDT')]
    except: symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    market_data = {}
    all_ts = set()
    max_rsi_found = 0
    max_rvol_found = 0
    
    for s in symbols:
        sym, df = fetch_data(s)
        if df is not None and not df.empty:
            df = df.set_index('ts')
            market_data[sym] = df
            all_ts.update(df.index.tolist())
            max_rsi_found = max(max_rsi_found, df['rsi'].max())
            max_rvol_found = max(max_rvol_found, df['rvol'].max())
            
    print(f"Statistik Pasar Terdeteksi: Max RSI={max_rsi_found:.1f}, Max RVOL={max_rvol_found:.1f}x")
    
    sorted_ts = sorted(list(all_ts))
    wallet = 10.0
    margin = 5.0
    lev = 10
    active_pos = None
    trade_logs = []
    
    # Param Juara
    TP_PCT = 1.04
    SL_PCT = 0.95
    FEE = 0.06

    for ts in sorted_ts:
        if active_pos:
            df = market_data[active_pos['sym']]
            if ts in df.index:
                row = df.loc[ts]
                ep = 0
                if row['l'] <= active_pos['sl']: ep = active_pos['sl']
                elif row['h'] >= active_pos['tp']: ep = active_pos['tp']
                
                if ep > 0:
                    f_pnl = ((ep - active_pos['ent'])/active_pos['ent']) * lev * 100
                    net = (f_pnl/100 * margin) - FEE
                    wallet += net
                    trade_logs.append({
                        'date': ts.date(),
                        'sym': active_pos['sym'],
                        'net': net,
                        'win': 1 if net > 0 else 0
                    })
                    active_pos = None
            continue

        if active_pos is None and wallet >= margin:
            for sym, df in market_data.items():
                if ts not in df.index: continue
                row = df.loc[ts]
                if row['rsi'] > 65 and row['rvol'] > 2.0 and row['atr_pct'] > 0.5:
                    active_pos = {
                        'sym': sym, 'ent': row['c'],
                        'sl': row['c'] * SL_PCT,
                        'tp': row['c'] * TP_PCT
                    }
                    break

    # Group by Date
    if not trade_logs:
        print("Tidak ada trade yang terdeteksi.")
        return

    audit_df = pd.DataFrame(trade_logs)
    daily = audit_df.groupby('date').agg({
        'net': 'sum',
        'win': ['count', 'sum']
    })
    daily.columns = ['Total PnL', 'Trades', 'Wins']
    daily['Win Rate %'] = (daily['Wins'] / daily['Trades'] * 100).round(1)
    
    print(daily.to_string())
    print("\n" + "="*80)
    print(f"SALDO AKHIR: ${wallet:.2f}")
    print("="*80)

if __name__ == "__main__":
    run_daily_audit()
