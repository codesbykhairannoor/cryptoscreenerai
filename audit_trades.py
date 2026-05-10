import sys
import os
from dotenv import load_dotenv

# Ensure we can import from backend
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from bitget_executor import BitgetExecutor

def check_trades():
    print("Initializing Bitget Executor...")
    try:
        executor = BitgetExecutor()
        positions = executor.get_all_positions()
        
        print("\n" + "="*40)
        print("      LIVE BITGET POSITIONS AUDIT")
        print("="*40)
        
        if not positions:
            print("No active trades found at the moment.")
        else:
            for p in positions:
                status = "🟢 PROFIT" if p['pnl'] > 0 else "🔴 LOSS"
                print(f"Symbol:   {p['symbol']}")
                print(f"Side:     {p['side'].upper()}")
                print(f"Size:     {p['size']} contracts")
                print(f"Entry:    {p['entry']}")
                print(f"PnL:      {p['pnl']}% ({status})")
                print("-" * 20)
        
        balance = executor.get_balance()
        print(f"\nWallet Balance: ${balance['total']:.2f} USDT")
        print(f"Available:      ${balance['free']:.2f} USDT")
        print("="*40)
        
    except Exception as e:
        print(f"Error checking trades: {e}")

if __name__ == "__main__":
    check_trades()
