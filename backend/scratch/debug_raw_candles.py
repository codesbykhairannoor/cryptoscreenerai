import requests
import pandas as pd
import json

def debug_raw_candles():
    symbol = "XRPUSDT"
    url = f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&granularity=15m&limit=20&productType=USDT-FUTURES"
    r = requests.get(url, verify=False)
    data = r.json().get('data', [])
    
    print(f"--- RAW CANDLES FOR {symbol} ---")
    for i, c in enumerate(data[-5:]):
        print(f"Candle {i}: Time={c[0]} Vol={c[5]}")
        
    df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'vol_usd'])
    df['vol'] = df['vol'].astype(float)
    avg_vol = df['vol'].mean()
    last_vol = df['vol'].iloc[-1]
    rvol = last_vol / avg_vol if avg_vol > 0 else 1.0
    
    print(f"\nLast Vol: {last_vol}")
    print(f"Avg Vol (20): {avg_vol}")
    print(f"Calculated RVOL: {rvol}")

if __name__ == "__main__":
    debug_raw_candles()
