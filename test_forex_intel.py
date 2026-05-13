import os
import sys
import time
import json
from dotenv import load_dotenv

# Tambahkan path backend agar bisa import ForexExecutor
sys.path.append(os.path.join(os.getcwd(), "backend"))

from forex_executor import ForexExecutor

def test_forex_intelligence():
    print("="*60)
    print("FOREX INTELLIGENCE AUDIT & DIAGNOSTIC")
    print("="*60)
    
    executor = ForexExecutor()
    
    # 1. Test Connection
    print("\n[1] Testing MT5 Connection...")
    success, msg = executor.test_connection()
    print(f"Status: {'SUCCESS' if success else 'FAILED'}")
    print(f"Message: {msg}")
    
    if not success:
        print("Aborting diagnostic due to connection failure.")
        return

    # 2. Test Live Price
    print("\n[2] Fetching Live Price...")
    price = executor.get_live_price()
    print(f"Symbol: {executor._working_symbol}")
    print(f"Price: {json.dumps(price, indent=2)}")

    # 3. Test Multi-Timeframe Indicators
    print("\n[3] Calculating Indicators (30m)...")
    indicators = executor._calc_indicators(timeframe="30m")
    print(f"30m Indicators: RSI={indicators.get('rsi')} Trend={indicators.get('trend')}")

    # 3b. Test 1m Indicators (New Hyper-Scalp Mode)
    print("\n[3b] Calculating Indicators (1m Hyper-Scalp)...")
    ind_1m = executor._calc_indicators(timeframe="1m")
    print(f"1m Indicators: RSI={ind_1m.get('rsi')} Trend={ind_1m.get('trend')} Vel={ind_1m.get('velocity')}")

    # 4. Test 5m Precision (MTF Confluence)
    print("\n[4] Testing MTF Confluence (including 5m)...")
    side_to_test = "buy" if indicators.get('trend') == "BULLISH" else "sell"
    confluence = executor._get_mtf_confluence(side_to_test)
    print(f"Side Tested: {side_to_test}")
    print(f"Confluence: {json.dumps(confluence, indent=2)}")

    # 5. Test 1m Micro-Momentum
    print("\n[5] Testing Micro-Momentum (1m precision)...")
    momentum = executor._get_micro_momentum()
    print(f"Momentum: {json.dumps(momentum, indent=2)}")

    # 5b. Test 5m Entry Precision (SMC)
    print("\n[5b] Testing 5m Entry Precision (SMC FVG/OB/Liq)...")
    e5m = executor._get_5m_entry_quality()
    print(f"5m Precision: {json.dumps(e5m, indent=2)}")

    # 6. Test DXY Context
    print("\n[6] Fetching DXY Macro Context...")
    dxy = executor._get_dxy_context()
    print(f"DXY: {json.dumps(dxy, indent=2)}")

    # 7. Test Orderbook / Whale Analysis
    print("\n[7] Analyzing Gold Orderbook/Whale...")
    ob = executor._get_gold_orderbook()
    whale = executor._get_gold_whale_trades()
    print(f"Orderbook: {json.dumps(ob, indent=2)}")
    print(f"Whale Trade: {whale}")

    print("\n" + "="*60)
    print("DIAGNOSTIC COMPLETE")
    print("="*60)

if __name__ == "__main__":
    test_forex_intelligence()
