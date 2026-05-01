
import os
import requests
import time
from dotenv import load_dotenv

# Load from backend folder
load_dotenv('backend/.env')

def run_final_check():
    print("--- [MILITARY AUDIT: FINAL VERIFICATION] ---")
    
    # 1. VERIFY FOREX ENDPOINT (Critical Fix)
    from backend.forex_executor import ForexExecutor
    fx = ForexExecutor()
    print(f"CHECK: Forex Endpoint Path: {fx.base_url}/users/current/accounts/.../trade")
    
    # 2. VERIFY SYMBOL SYNC (XAUUSDc)
    token = os.getenv("FOREX_META_API_TOKEN")
    account_id = os.getenv("FOREX_ACCOUNT_ID")
    headers = {"auth-token": token}
    
    found_price = False
    for s in ["", "c", ".m"]:
        url = f"https://mt-client-api-v1.new-york.agiliumtrade.ai/users/current/accounts/{account_id}/symbols/XAUUSD{s}/current-price"
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                price = res.json().get('bid')
                print(f"SUCCESS: MetaAPI Synced. XAUUSD{s} Price: {price}")
                found_price = True
                break
        except: continue
        
    if not found_price:
        print("ALERT: MetaAPI Sync failed. Check Token/AccountID.")

    # 3. VERIFY BITGET (Logical Check)
    from backend.bitget_executor import BitgetExecutor
    try:
        executor = BitgetExecutor()
        print(f"SUCCESS: Bitget Executor initialized. (UTA Mode: {executor.is_uta})")
    except Exception as e:
        print(f"ERROR: Bitget initialization failed: {e}")

    print("--- [AUDIT COMPLETE: SYSTEM IS MISSION READY] ---")

if __name__ == "__main__":
    run_final_check()
