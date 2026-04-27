import ccxt
import os
from dotenv import load_dotenv

load_dotenv()

def test_bitget():
    api_key = os.getenv("BITGET_API_KEY")
    secret_key = os.getenv("BITGET_SECRET_KEY")
    passphrase = os.getenv("BITGET_PASSPHRASE")

    hostnames = [None, 'bitget.cc', 'bitgetapi.com']
    
    print(f"--- BITGET DIAGNOSTIC START ---")
    print(f"Key: {api_key[:10]}...")
    
    for host in hostnames:
        print(f"\n>> Testing Hostname: {host or 'DEFAULT'}")
        params = {
            'apiKey': api_key,
            'secret': secret_key,
            'password': passphrase,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        }
        if host:
            params['hostname'] = host
            
        exchange = ccxt.bitget(params)
        
        try:
            # Test 1: Fetch Time (Public)
            time = exchange.fetch_time()
            print(f"  [OK] Public API (fetch_time): {time}")
            
            # Test 2: Fetch Ticker (Public)
            ticker = exchange.fetch_ticker('BTC/USDT:USDT')
            print(f"  [OK] Futures Ticker: {ticker['last']}")
            
            # Test 3: Fetch Balance (Private)
            balance = exchange.fetch_balance(params={'type': 'swap'})
            usdt = balance.get('USDT', {}).get('total', 'N/A')
            print(f"  [OK] Private API (Balance): {usdt} USDT")
            
            print(f"  !!! SUCCESS WITH {host or 'DEFAULT'} !!!")
            return host
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {str(e)}")
            
    print("\n--- DIAGNOSTIC FINISHED: ALL HOSTS FAILED ---")
    return None

if __name__ == "__main__":
    test_bitget()
