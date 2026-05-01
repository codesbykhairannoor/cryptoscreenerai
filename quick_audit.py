
import os
import requests
import time
from dotenv import load_dotenv

# Load from backend folder
load_dotenv('backend/.env')

def quick_test():
    print("--- QUICK INFRASTRUCTURE AUDIT ---")
    
    # 1. BITGET V3 API TEST (Raw)
    try:
        url = "https://api.bitget.com/api/v3/market/tickers?category=USDT-FUTURES"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            print("PASS: Bitget API is reachable.")
        else:
            print(f"FAIL: Bitget API returned {res.status_code}")
    except Exception as e:
        print(f"FAIL: Bitget API unreachable: {e}")

    # 2. METAAPI (FOREX) TEST (Raw)
    token = os.getenv("FOREX_META_API_TOKEN")
    account_id = os.getenv("FOREX_ACCOUNT_ID")
    
    if token and account_id:
        try:
            url = f"https://mt-client-api-v1.new-york.agiliumtrade.ai/users/current/accounts/{account_id}"
            headers = {"auth-token": token}
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                bal = res.json().get('balance', 0)
                print(f"PASS: MetaAPI connected. Balance: ${bal}")
            else:
                print(f"FAIL: MetaAPI returned {res.status_code} - {res.text}")
        except Exception as e:
            print(f"FAIL: MetaAPI unreachable: {e}")
    else:
        print("FAIL: MetaAPI credentials missing in .env")

    # 3. FOREX PRICE SYNC TEST (Raw)
    if token and account_id:
        # Try a few suffixes
        for s in ["", "c", ".m"]:
            try:
                symbol = f"XAUUSD{s}"
                url = f"https://mt-client-api-v1.new-york.agiliumtrade.ai/users/current/accounts/{account_id}/symbols/{symbol}/current-price"
                headers = {"auth-token": token}
                res = requests.get(url, headers=headers, timeout=5)
                if res.status_code == 200:
                    price = res.json().get('bid')
                    print(f"PASS: Found {symbol} at price: {price}")
                    break
            except: continue

    print("--- AUDIT COMPLETE ---")

if __name__ == "__main__":
    quick_test()
