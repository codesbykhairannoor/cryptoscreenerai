import ccxt
import os
import traceback
from dotenv import load_dotenv

load_dotenv()

class BitgetExecutor:
    def __init__(self):
        self.api_key = os.getenv("BITGET_API_KEY")
        self.secret_key = os.getenv("BITGET_SECRET_KEY")
        self.passphrase = os.getenv("BITGET_PASSPHRASE", "")
        
        self.exchange = ccxt.bitget({
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'password': self.passphrase,
            'enableRateLimit': True,
            'timeout': 30000,
            'options': {
                'defaultType': 'swap',
            }
        })

    def get_balance_robust(self):
        """Helper to fetch balance using multiple methods"""
        try:
            # Method 1: Swap Type
            balance = self.exchange.fetch_balance(params={'type': 'swap'})
            if balance and 'USDT' in balance:
                return balance['USDT'].get('total', 0)
        except:
            pass
        
        try:
            # Method 2: Generic
            balance = self.exchange.fetch_balance()
            if balance and 'USDT' in balance:
                return balance['USDT'].get('total', 0)
        except:
            pass
            
        return 0

    def test_connection(self):
        try:
            if not self.api_key:
                return False, "API Key Bitget tidak ditemukan di .env"
            
            print(f"Testing connection with Key: {self.api_key[:10]}...")
            
            usdt = self.get_balance_robust()
            if usdt > 0:
                return True, f"Bitget Futures OK (Saldo: ${round(usdt, 2)})"
            
            # Fallback to ticker proof
            try:
                ticker = self.exchange.fetch_ticker('BTC/USDT:USDT')
                if ticker and 'last' in ticker:
                    return True, f"Bitget OK (Izin Futures Terbatas - BTC: ${ticker['last']})"
            except:
                pass
                
            return False, "Koneksi gagal. Cek API Key & Izin Futures di Bitget."
        except Exception as e:
            return False, f"Error: {str(e)}"

    def place_futures_order(self, symbol, side, leverage=5, amount_usdt=10):
        try:
            if not ":" in symbol:
                if symbol.endswith("USDT"):
                    symbol = f"{symbol.replace('USDT', '')}/USDT:USDT"
                else:
                    symbol = f"{symbol}/USDT:USDT"

            try: self.exchange.set_leverage(leverage, symbol)
            except: pass
            
            total_usdt = self.get_balance_robust()
            
            max_safe = total_usdt * 0.2
            actual_spend = min(amount_usdt, max_safe)
            
            if actual_spend < 5:
                return False, f"Saldo tidak cukup (Min $5). Saldo terdeteksi: ${total_usdt}"

            ticker = self.exchange.fetch_ticker(symbol)
            price = ticker['last']
            quantity = (actual_spend * leverage) / price
            
            order = self.exchange.create_market_order(symbol, side, quantity)
            return True, f"Trade {side.upper()} {symbol} BERHASIL! Margin: {actual_spend} USDT"
        except Exception as e:
            return False, f"Gagal Order: {str(e)}"


if __name__ == "__main__":
    executor = BitgetExecutor()
    success, msg = executor.test_connection()
    print(msg)
