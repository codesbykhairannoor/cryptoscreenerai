import sys
import os
import json
from dotenv import load_dotenv

load_dotenv()

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from data_fetcher import get_dune_macro_metrics, get_defillama_metrics
    from early_signal import _fetch_dex_trending
    print("[INFO] Imports successful!")
except ImportError as e:
    print(f"[ERROR] Import failed: {e}")
    sys.exit(1)

def test_dune():
    print("\n--- TESTING DUNE ANALYTICS MACRO ---")
    data = get_dune_macro_metrics()
    print(json.dumps(data, indent=2))
    if data.get("status") == "success":
        print("PASS: Dune Analytics is working.")
    else:
        print(f"FAIL/WARN: Dune Analytics status: {data.get('status')}")

def test_defillama():
    print("\n--- TESTING DEFILLAMA (AAVE) ---")
    data = get_defillama_metrics("aave")
    print(json.dumps(data, indent=2))
    if data.get("tvl", 0) > 0:
        print("PASS: DefiLlama is working.")
    else:
        print("FAIL: DefiLlama returned zero/no TVL.")

def test_dexscreener():
    print("\n--- TESTING DEXSCREENER ---")
    alerts = _fetch_dex_trending()
    print(f"Found {len(alerts)} alerts.")
    if alerts:
        for a in alerts[:3]:
            print(f" - [{a['chain'].upper()}] {a.get('symbol', 'N/A')} | Vol5m: {a.get('vol_5m', 0)}")
        print("PASS: DexScreener is working.")
    else:
        print("FAIL: DexScreener returned no alerts.")

if __name__ == "__main__":
    test_dune()
    test_defillama()
    test_dexscreener()
