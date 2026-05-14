import requests
import pandas as pd
import numpy as np
import urllib3
import sys

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_rsi(series, period=14):
    delta = series.diff()
    u = delta.clip(lower=0)
    d = -delta.clip(upper=0)
    ma_u = u.ewm(com=period-1, adjust=False).mean()
    ma_d = d.ewm(com=period-1, adjust=False).mean()
    rs = ma_u / ma_d
    return 100 - (100 / (1 + rs))

def run_audit():
    print("\n--- INITIATING FORCED AUDIT ---")
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "MATICUSDT", "DOTUSDT", "TRXUSDT"]
    
    trade_logs = []
    wallet = 10.0
    
    for sym in symbols:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=15m&limit=500"
        try:
            print(f"Fetching {sym}...", end=" ")
            res = requests.get(url, verify=False, timeout=10)
            if res.status_code != 200:
                print(f"Error {res.status_code}")
                continue
            
            data = res.json()
            df = pd.DataFrame(data, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
            df['c'] = df['c'].astype(float)
            df['v'] = df['v'].astype(float)
            df['h'] = df['h'].astype(float)
            df['l'] = df['l'].astype(float)
            
            df['rsi'] = get_rsi(df['c'])
            df['rvol'] = df['v'] / df['v'].rolling(20).mean()
            df['atr_pct'] = ((df['h'] - df['l']).rolling(14).mean() / df['c']) * 100
            
            df = df.dropna()
            print(f"OK ({len(df)} rows) | Max RSI: {df['rsi'].max():.1f} | Max RVOL: {df['rvol'].max():.1f}")
            
            # Simple Simulation for this coin
            for i, row in df.iterrows():
                if row['rsi'] > 65 and row['rvol'] > 2.0 and row['atr_pct'] > 0.5:
                    # Simulasi satu kali trade per koin saja untuk audit cepat
                    trade_logs.append({'date': pd.to_datetime(row['ts'], unit='ms').date(), 'sym': sym, 'res': 'SIGNAL'})
                    
        except Exception as e:
            print(f"Failed: {e}")

    if not trade_logs:
        print("\nKESIMPULAN: Tidak ada sinyal Holy Grail terdeteksi di 10 koin utama dalam 500 candle terakhir.")
    else:
        audit_df = pd.DataFrame(trade_logs)
        print("\n--- SEJARAH TEMBAKAN SINYAL ---")
        print(audit_df.groupby('date').count())

if __name__ == "__main__":
    run_audit()



