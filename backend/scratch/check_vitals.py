import sys
import os
import time

sys.path.append(os.getcwd())

from database import get_connection, init_db
from bitget_executor import BitgetExecutor

def test_vitals():
    print("=== STARTING VITAL SIGNS CHECK ===")
    
    # 1. Database Check
    try:
        print("[DB] Connecting...", end=" ", flush=True)
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        print("OK")
        conn.close()
    except Exception as e:
        print(f"FAILED: {e}")

    # 2. Bitget Check
    try:
        print("[BITGET] Initializing Executor...", end=" ", flush=True)
        executor = BitgetExecutor()
        bal = executor.get_balance()
        if bal:
            print(f"OK (Balance: {bal.get('total')} USDT)")
        else:
            print("FAILED (No data)")
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    test_vitals()
