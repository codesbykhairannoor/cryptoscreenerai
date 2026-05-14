
import requests
import time
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

apis = {
    "Bitget Public": "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES",
    "MetaAPI London": "https://mt-client-api-v1.london.agiliumtrade.ai/health"
}

print(f"--- PENGETESAN LATENCY API (VPS -> SERVER) ---")
for name, url in apis.items():
    print(f"\nTesting {name}...")
    latencies = []
    for i in range(5):
        try:
            start = time.time()
            r = requests.get(url, timeout=20, verify=False)
            end = time.time()
            latency = (end - start) * 1000
            print(f"  Attempt {i+1}: {latency:.0f}ms (HTTP {r.status_code})")
            latencies.append(latency)
        except Exception as e:
            print(f"  Attempt {i+1}: FAILED ({e})")
        time.sleep(1)
    
    if latencies:
        avg = sum(latencies) / len(latencies)
        max_l = max(latencies)
        print(f"  RESULT: Avg {avg:.0f}ms | Max {max_l:.0f}ms")
        print(f"  SUGGESTED TIMEOUT: {max_l/1000 + 5:.1f}s (Buffer +5s)")
    else:
        print(f"  RESULT: TOTAL FAILURE")
