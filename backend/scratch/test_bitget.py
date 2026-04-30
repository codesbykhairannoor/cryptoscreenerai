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

def test_v3_uta():
    executor = BitgetExecutor()
    
    print("\n" + "="*50)
    print("BITGET V3 (UTA) DIAGNOSTIC TEST")
    print("="*50)
    
    # 1. Test Balance
    print("\n[1] Testing Balance...")
    bal = executor.get_balance()
    print(f"[RESULT] Total: {bal['total']} USDT | Free: {bal['free']} USDT")
    
    # 2. Test Positions
    print("\n[2] Testing Get Positions (V3)...")
    positions = executor.get_all_positions()
    print(f"[RESULT] Found {len(positions)} positions.")
    for p in positions:
        print(f" - {p['symbol']} | Side: {p['side']} | Entry: {p['entry']} | PNL: {p['pnl']}")
    
    # 3. Test Open Orders
    print("\n[3] Testing Get Open Orders (V3)...")
    orders = executor.get_pending_plan_orders()
    print(f"[RESULT] Found {len(orders)} open/plan orders.")
    for o in orders:
        dtype = o.get('delegateType', 'normal')
        price = o.get('triggerPrice') or o.get('price')
        print(f" - ID: {o.get('orderId')} | Symbol: {o.get('symbol')} | Side: {o.get('side')} | Type: {dtype} | Price: {price}")

    print("\n" + "="*50)
    print("TEST COMPLETE")
    print("="*50)

if __name__ == "__main__":
    test_v3_uta()
