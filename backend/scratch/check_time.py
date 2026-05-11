import requests
import time
import json

def check_time_sync():
    local_ts = int(time.time() * 1000)
    res = requests.get("https://api.bitget.com/api/v2/public/time")
    if res.status_code == 200:
        server_ts = int(res.json()['data']['serverTime'])
        diff = server_ts - local_ts
        print(f"Local Time : {local_ts}")
        print(f"Server Time: {server_ts}")
        print(f"Difference : {diff} ms ({diff/1000} seconds)")
        return diff
    else:
        print(f"Failed to fetch server time: {res.text}")
        return 0

if __name__ == "__main__":
    check_time_sync()
