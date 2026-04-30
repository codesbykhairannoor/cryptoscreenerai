import sys
import os
import time

# Add current directory to path
sys.path.append(os.getcwd())

try:
    from bitget_executor import BitgetExecutor
    print("[INFO] Import successful!")
    
    executor = BitgetExecutor()
    print("[INFO] Testing get_all_positions()...")
    positions = executor.get_all_positions()
    print(f"[INFO] Positions fetched: {len(positions)}")
    for p in positions:
        print(f"  - {p['symbol']} ({p['side']}): {p['size']} @ {p['entry']}")
        
    if positions:
        sym = positions[0]['symbol']
        print(f"[INFO] Testing get_pending_plan_orders for {sym}...")
        plans = executor.get_pending_plan_orders(sym)
        print(f"[INFO] Plans found: {len(plans)}")
        for pl in plans:
            print(f"  - Plan ID: {pl.get('orderId') or pl.get('id')} | Trigger: {pl.get('triggerPrice')}")
    else:
        print("[INFO] No active positions to test specific plan orders. Fetching all plans...")
        plans = executor.get_pending_plan_orders()
        print(f"[INFO] Total Plans found: {len(plans)}")

except Exception as e:
    print(f"[ERROR] TEST FAILED: {e}")
    import traceback
    traceback.print_exc()
