import requests
import json

queries = [
    "freqtrade strategy win rate",
    "crypto spot bot high win rate",
    "nostalgiaforinfinity",
    "crypto statistical arbitrage spot"
]

print("=" * 80)
print("PENCARIAN REPOSITORI GITHUB TERBAIK UNTUK SPOT CRYPTO STRATEGY")
print("=" * 80)

for q in queries:
    url = f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc"
    try:
        r = requests.get(url, headers={"User-Agent": "ResearchBot/1.0"}, timeout=10)
        if r.status_code == 200:
            items = r.json().get('items', [])[:4]
            print(f"\n[QUERY: '{q}'] - Top Results:")
            for item in items:
                name = item.get('full_name')
                stars = item.get('stargazers_count')
                desc = item.get('description')
                print(f"  * {name} ({stars} stars)")
                print(f"    Desc: {desc}")
    except Exception as e:
        print(f"Error querying {q}: {e}")
