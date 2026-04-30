import requests
import json
import pandas as pd

def test_bitget_v3():
    symbol = "BTCUSDT"
    granularity = "15m"
    url = f"https://api.bitget.com/api/v3/market/candles?symbol={symbol}&granularity={granularity}&limit=5&category=USDT-FUTURES"
    
    print(f"Testing URL: {url}")
    try:
        res = requests.get(url, timeout=10, verify=False)
        print(f"Status Code: {res.status_code}")
        data = res.json()
        print("Raw Response Keys:", data.keys())
        if 'data' in data:
            print("Data Length:", len(data['data']))
            if data['data']:
                print("First Candle Sample:", data['data'][0])
        else:
            print("Response:", data)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_bitget_v3()
