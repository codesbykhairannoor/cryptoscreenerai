import sys
import os
import time
import json

sys.path.append(os.getcwd())

from data_fetcher import get_technical_indicators

def debug_rvol():
    symbol = "XRPUSDT"
    print(f"--- DEBUGGING TECH FOR {symbol} ---")
    tech = get_technical_indicators(symbol)
    print(json.dumps(tech, indent=2))

if __name__ == "__main__":
    debug_rvol()
