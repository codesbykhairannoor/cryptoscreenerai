import os
import sys
import pandas as pd
import time
from forex_executor import ForexExecutor

def fetch_massive_data(timeframe="30m", limit=2000):
    fx = ForexExecutor()
    print(f"Fetching {limit} candles for {timeframe}...")
    
    all_candles = []
    # MetaAPI might limit per call, let's try in chunks if it fails, 
    # but usually 1000-2000 is okay for historical requests.
    data = fx.get_candles(timeframe=timeframe, limit=limit)
    if data:
        print(f"Successfully fetched {len(data)} candles.")
        return pd.DataFrame(data)
    else:
        print("Failed to fetch data.")
        return None

if __name__ == "__main__":
    df = fetch_massive_data("30m", 1500)
    if df is not None:
        df.to_csv("xauusd_30m_massive.csv", index=False)
        print("Data saved to xauusd_30m_massive.csv")
