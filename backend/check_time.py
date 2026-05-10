import requests
import time

def check_offset():
    try:
        url = "https://api.bitget.com/api/v2/public/time"
        start = time.time() * 1000
        res = requests.get(url, timeout=5)
        end = time.time() * 1000
        server_ms = int(res.json()['data'])
        local_ms = int((start + end) / 2)
        offset = server_ms - local_ms
        print(f"Server Time: {server_ms}")
        print(f"Local Time:  {local_ms}")
        print(f"Offset:      {offset} ms")
        return offset
    except Exception as e:
        print(f"Error: {e}")
        return 0

if __name__ == "__main__":
    check_offset()
