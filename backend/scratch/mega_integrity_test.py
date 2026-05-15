import sys
import os
import time
import json
from unittest.mock import MagicMock, patch

# Ensure backend path is accessible
sys.path.append(os.getcwd())

# Import REAL components
from crypto_engine import _determine_trade_side, _calc_tp_sl, LEVERAGE, FIXED_MARGIN_USDT
from bitget_executor import BitgetExecutor
from data_fetcher import get_technical_indicators

def run_mega_test():
    print("\n" + "="*80)
    print("=" + " "*25 + "MEGA INTEGRITY TEST v1.1" + " "*25 + "=")
    print("=" + " "*20 + "AUDITING REAL EXECUTION & INDICATORS" + " "*18 + "=")
    print("="*80 + "\n")

    # 1. INITIALIZE REAL EXECUTOR
    print("[STEP 1] Initializing Bitget Executor...")
    executor = BitgetExecutor()
    print(f"  > Status: Connected to Bitget API V2")
    
    # 2. FETCH REAL DATA
    symbol = "XRPUSDT"
    print(f"\n[STEP 2] Fetching Real Data for {symbol}...")
    tech = get_technical_indicators(symbol)
    if not tech:
        print("  [!] Error: Could not fetch real data.")
        return
    
    # 3. FORCE A TRIGGER
    print(f"\n[STEP 3] Forcing a Technical Signal (MSS^ + FVG+)...")
    tech_forced = tech.copy()
    tech_forced['mss_bullish'] = True
    tech_forced['fvg'] = 'BULLISH'
    tech_forced['rvol'] = 1.5
    
    side, reason, tech_score = _determine_trade_side(
        tech_forced, 55.0, 1.0, "NEUTRAL", tech['mark_price'], 70, 0
    )
    
    if side == "buy":
        print(f"  [OK] TRIGGER ARMED: Logic says EXECUTE.")
        
        # 4. CALCULATE TP/SL
        tp, sl = _calc_tp_sl(tech['mark_price'], side, tech_forced)
        
        # 5. CALCULATE SIZE
        amount = executor.get_max_available(symbol, leverage=LEVERAGE, risk_usdt=FIXED_MARGIN_USDT)
        if amount <= 0:
            print(f"  [!] Insufficient balance for testing. (Required: ~${FIXED_MARGIN_USDT})")
            return

        # 6. EXECUTE ORDER
        print(f"\n[STEP 4] Executing Real Order to Bitget...")
        try:
            res = executor.place_order(
                symbol=symbol,
                side=side,
                amount=amount,
                take_profit_val=tp,
                stop_loss_val=sl,
                leverage=LEVERAGE
            )
            
            if res and 'orderId' in str(res):
                print(f"  [SUCCESS] ORDER EXECUTED!")
                print(f"  > Order ID: {res.get('orderId')}")
            else:
                print(f"  [X] API REJECTION: {res}")
        except Exception as e:
            print(f"  [ERROR] Execution failed: {e}")
            
    else:
        print(f"  [FAIL] TRIGGER BLOCKED.")

    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    run_mega_test()
