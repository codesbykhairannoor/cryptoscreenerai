
import os
import requests
import time
import pandas as pd
from dotenv import load_dotenv

load_dotenv('backend/.env')

def test_metaapi_candles():
    token = os.getenv("FOREX_META_API_TOKEN")
    account_id = os.getenv("FOREX_ACCOUNT_ID")
    base_url = "https://mt-client-api-v1.london.agiliumtrade.ai"
    headers = {"auth-token": token}
    
    symbol = "XAUUSDc"
    period = "15m"
    # Endpoints vary, trying common ones
    url = f"{base_url}/users/current/accounts/{account_id}/symbols/{symbol}/historical-data/candles?period={period}&limit=50"
    
    print(f"Testing MetaAPI Candles for {symbol}...")
    try:
        res = requests.get(url, headers=headers, timeout=10)
        print(f"Status: {res.status_code}")
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                print(f"SUCCESS: Received {len(data)} candles.")
                print(f"Sample: {data[0]}")
            else:
                print(f"EMPTY: {data}")
        else:
            print(f"ERROR: {res.text}")
    except Exception as e:
        print(f"CRASH: {e}")

if __name__ == "__main__":
    test_metaapi_candles()
