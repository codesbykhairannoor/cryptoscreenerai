import requests

domains = ["api.bitget.com", "api.bitget.com.cn", "api.bitget.site", "api.bitget.cc", "fapi.binance.me", "fapi.binance.info"]
endpoints = [
    "/api/v2/mix/market/history-candles?symbol=BTCUSDT&granularity=1m&limit=1&productType=USDT-FUTURES",
    "/api/v2/spot/market/candles?symbol=BTCUSDT&granularity=1m&limit=1",
    "/fapi/v1/klines?symbol=BTCUSDT&interval=1m&limit=1"
]

print("[DETECTOR] Scanning for working API tunnels...")

for d in domains:
    for e in endpoints:
        url = f"https://{d}{e}"
        try:
            r = requests.get(url, timeout=5, verify=False)
            if r.status_code == 200:
                print(f"[SUCCESS] FOUND WORKING TUNNEL: {url}")
                # Print a bit of data to verify
                print(f"          Data: {r.text[:50]}...")
            else:
                print(f"[FAILED] {d} -> {r.status_code}")
        except Exception as err:
            print(f"[ERROR] {d} -> Connection Failed")

print("[DETECTOR] Scan completed.")
