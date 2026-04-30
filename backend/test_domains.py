import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

domains = [
    "api.bitget.com",
    "api.bitgetapi.com",
    "api.bitget.site",
    "api.bitget.vip"
]

def test_domains():
    symbol_v3 = "BTCUSDT"
    symbol_v2 = "BTCUSDT_UMCBL"
    
    for domain in domains:
        print(f"\n--- Testing Domain: {domain} ---")
        
        # Test V3
        url_v3 = f"https://{domain}/api/v3/market/candles?symbol={symbol_v3}&granularity=15m&limit=2&category=USDT-FUTURES"
        try:
            r = requests.get(url_v3, timeout=5, verify=False)
            if r.status_code == 200:
                data = r.json()
                if 'data' in data and data['data']:
                    print("[OK] V3 SUCCESS!")
                else:
                    print("[FAIL] V3 Valid JSON, but empty or no 'data' key.")
            else:
                print(f"[FAIL] V3 Failed with Status {r.status_code}: {r.text[:50]}")
        except Exception as e:
            print(f"[FAIL] V3 Exception: {e}")
            
        # Test V2
        url_v2 = f"https://{domain}/api/v2/mix/market/candles?symbol={symbol_v2}&granularity=15m&limit=2&productType=usdt-futures"
        try:
            r = requests.get(url_v2, timeout=5, verify=False)
            if r.status_code == 200:
                data = r.json()
                if 'data' in data and data['data']:
                    print("[OK] V2 SUCCESS!")
                else:
                    print("[FAIL] V2 Valid JSON, but empty or no 'data' key.")
            else:
                print(f"[FAIL] V2 Failed with Status {r.status_code}: {r.text[:50]}")
        except Exception as e:
            print(f"[FAIL] V2 Exception: {e}")

if __name__ == "__main__":
    test_domains()
