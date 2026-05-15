import sys
import os
import time

sys.path.append(os.getcwd())

from bitget_executor import BitgetExecutor

def test_live_execution():
    print("=== STARTING LIVE TRADE EXECUTION TEST ===")
    executor = BitgetExecutor()
    
    symbol = "XRPUSDT"
    side = "buy"
    leverage = 10
    
    print(f"[TEST] Target Symbol: {symbol}")
    
    # 1. Get Live Price
    try:
        from data_fetcher import get_technical_indicators
        tech = get_technical_indicators(symbol)
        mark_price = tech.get('mark_price', 0)
        print(f"[TEST] Current Mark Price: {mark_price}")
        
        if mark_price == 0:
            print("FAILED: Could not get live price.")
            return
            
        # 2. Place Market Order
        # Smallest possible size for test
        amount = 5.0 # 5 USDT
        
        print(f"[TEST] Firing Market {side.upper()} {symbol} amount=${amount}...")
        
        # Calculate SL/TP
        tp_price = round(mark_price * 1.05, 4) # +5%
        sl_price = round(mark_price * 0.95, 4) # -5%
        
        success, res = executor.place_order(
            symbol=symbol,
            side=side,
            amount=amount,
            take_profit_val=tp_price,
            stop_loss_val=sl_price,
            leverage=leverage
        )
        
        if success:
            print(f"SUCCESS! Order placed: {res}")
            print("\nCheck your Bitget app now! You should see an XRP position with SL/TP.")
        else:
            print(f"FAILED: {res}")
            
    except Exception as e:
        print(f"CRITICAL ERROR during test: {e}")

if __name__ == "__main__":
    test_live_execution()
