import ccxt
import os
import json
from dotenv import load_dotenv

load_dotenv('backend/.env')

def test_bitget_positions():
    exchange = ccxt.bitget({
        'apiKey': os.getenv('BITGET_API_KEY'),
        'secret': os.getenv('BITGET_SECRET_KEY'),
        'password': os.getenv('BITGET_PASSPHRASE'),
        'options': {'defaultType': 'swap'} # Use swap for futures
    })
    
    print("Checking USDT-FUTURES positions...")
    try:
        # 1. Standard fetch_positions
        pos = exchange.fetch_positions(params={'productType': 'usdt-futures'})
        print(f"Found {len(pos)} raw position entries.")
        
        active = []
        for p in pos:
            sz = float(p.get('contracts', 0) or 0)
            if sz > 0:
                active.append({
                    'symbol': p['symbol'],
                    'side': p['side'],
                    'size': sz,
                    'entry': p.get('entryPrice')
                })
        
        print(f"Active Positions: {json.dumps(active, indent=2)}")
        
        # 2. Check balance
        bal = exchange.fetch_balance(params={'productType': 'usdt-futures'})
        print(f"Free USDT: {bal['free'].get('USDT', 0)}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_bitget_positions()
