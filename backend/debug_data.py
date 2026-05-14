import requests
import pandas as pd
import numpy as np

def fetch_debug(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=100"
    r = requests.get(url).json()
    df = pd.DataFrame(r, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    
    # RSI Rumus Baru (Lebih Aman)
    delta = df['c'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=13, adjust=False).mean()
    ema_down = down.ewm(com=13, adjust=False).mean()
    rs = ema_up / ema_down
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # RVOL
    df['rvol'] = df['v'] / df['v'].rolling(20).mean()
    
    print(f"\n--- DEBUG DATA {symbol} ---")
    print(df[['ts', 'c', 'rsi', 'rvol']].tail(5).to_string())
    print(f"Max RSI: {df['rsi'].max()}")
    print(f"Max RVOL: {df['rvol'].max()}")

if __name__ == "__main__":
    fetch_debug("BTCUSDT")
    fetch_debug("ETHUSDT")



