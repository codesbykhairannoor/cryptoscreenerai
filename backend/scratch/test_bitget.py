import os
import sys
from dotenv import load_dotenv

# Add parent directory to path to import backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from bitget_executor import BitgetExecutor
    print("[INFO] Import successful!")
except ImportError as e:
    print(f"[ERROR] Import failed: {e}")
    sys.exit(1)

def test_mode_detection():
    executor = BitgetExecutor()
    
    print("\n" + "="*50)
    print("BITGET HYBRID DIAGNOSTIC TEST")
    print("="*50)
    
    # 1. Test Connection & Mode
    success, msg = executor.test_connection()
    print(f"[1] Connection Test: {msg}")
    print(f"    Detected Mode: {'UTA' if executor.is_uta else 'Classic'}")
    
    # 2. Test Balance
    print("\n[2] Testing Balance...")
    bal = executor.get_balance()
    print(f"[RESULT] Total: {bal['total']} USDT | Free: {bal['free']} USDT")
    
    # 3. Test Positions
    print("\n[3] Testing Get Positions...")
    positions = executor.get_all_positions()
    print(f"[RESULT] Found {len(positions)} positions.")
    for p in positions:
        print(f" - {p['symbol']} | Side: {p['side']} | Entry: {p['entry']} | PNL: {p.get('pnl', 0)}")
    
    # 4. Test Max Available
    print("\n[4] Testing Max Available...")
    try:
        max_q = executor.get_max_available("BTC/USDT:USDT")
        print(f"[RESULT] Max BTC for 10x: {max_q}")
    except Exception as e:
        print(f"[ERROR] Max Available failed: {e}")

    print("\n" + "="*50)
    print("TEST COMPLETE")
    print("="*50)

if __name__ == "__main__":
    test_mode_detection()
