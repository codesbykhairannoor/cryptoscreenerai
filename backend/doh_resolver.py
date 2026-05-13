import requests
import json

def get_real_ip(domain):
    print(f"[DoH] Querying Cloudflare for real IP of {domain}...")
    url = f"https://cloudflare-dns.com/query?name={domain}&type=A"
    headers = {"accept": "application/dns-json"}
    try:
        r = requests.get(url, headers=headers, verify=False)
        data = r.json()
        ips = [ans['data'] for ans in data.get('Answer', []) if ans['type'] == 1]
        return ips
    except Exception as e:
        print(f"[ERROR] DoH Failed: {e}")
        return []

bitget_ips = get_real_ip("api.bitget.com")
binance_ips = get_real_ip("fapi.binance.com")

print(f"\nREAL BITGET IPS: {bitget_ips}")
print(f"REAL BINANCE IPS: {binance_ips}")
