import ccxt
import os
from dotenv import load_dotenv

load_dotenv('backend/.env')

def check():
    print("Checking Bitget...")
    exchange = ccxt.bitget({
        'apiKey': os.getenv('BITGET_API_KEY'),
        'secret': os.getenv('BITGET_SECRET_KEY'),
        'password': os.getenv('BITGET_PASSPHRASE'),
        'options': {'defaultType': 'swap'}
    })
    
    try:
        balance = exchange.fetch_balance()
        print(f"Total USDT: {balance['total']['USDT']}")
        
        positions = exchange.fetch_positions(params={'productType': 'usdt-futures'})
        active = [p for p in positions if float(p.get('contracts', 0) or 0) > 0]
        
        if not active:
            print("No active positions.")
        else:
            for p in active:
                print(f"{p['symbol']}: {p['side']} | Size: {p['contracts']} | PnL: {p.get('percentage', 0)}%")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check()
