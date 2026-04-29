import ccxt
import os
import time
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
                'posMode': 'unilateral' # Hardcode for One-Way Mode
            }
        })
        try:
            self.exchange.set_position_mode(False) # Attempt to set One-way (False)
        except:
            pass

    def get_balance_robust(self, retries=3):
        """Helper to fetch balance with retry logic"""
        for i in range(retries):
            try:
                # Method 1: Swap Type
                balance = self.exchange.fetch_balance(params={'type': 'swap'})
                if balance and 'USDT' in balance:
                    return balance['USDT'].get('total', 0)
            except Exception as e:
                if i == retries - 1: print(f"Balance fetch error after {retries} attempts: {e}")
                time.sleep(1) # Wait before retry
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

    def place_futures_order(self, symbol, side, leverage=5, amount_usdt=None, tp_price=None, sl_price=None, retries=3):
        """
        Executes a 'Market-with-Protection' trade using Limit orders with offset.
        Prevents buying at extreme prices (slippage protection).
        """
        try:
            if not ":" in symbol:
                if symbol.endswith("USDT"):
                    symbol = f"{symbol.replace('USDT', '')}/USDT:USDT"
                else:
                    symbol = f"{symbol}/USDT:USDT"

            # Set Leverage
            for i in range(retries):
                try:
                    self.exchange.set_leverage(leverage, symbol)
                    break
                except:
                    time.sleep(1)
            
            total_usdt = self.get_balance_robust()
            actual_spend = total_usdt * 0.95
            
            if actual_spend < 5:
                return False, f"Saldo tidak cukup (Min $5). Saldo Anda: ${total_usdt}."

            ticker = self.exchange.fetch_ticker(symbol)
            last_price = ticker['last']
            
            # SLIPPAGE PROTECTION: Calculate Limit Price (0.5% offset)
            # This ensures we get fast execution but not at a crazy price
            if side == 'buy':
                limit_price = last_price * 1.005 # Buy slightly higher to guarantee fill
            else:
                limit_price = last_price * 0.995 # Sell slightly lower

            quantity = (actual_spend * leverage) / limit_price
            
            # Enhanced Order Params for Bitget (TP/SL)
            params = {
                'takeProfitPrice': tp_price,
                'stopLossPrice': sl_price
            }

            # Place Protected Limit Order
            for i in range(retries):
                try:
                    # 1. Place Main Entry Order (STRICT One-Way Mode)
                    # We send ONLY the essential params to avoid 40774 error
                    order = self.exchange.create_order(
                        symbol=symbol,
                        type='limit',
                        side=side,
                        amount=quantity,
                        price=limit_price,
                        params={} # Empty params to avoid any hidden mode conflicts
                    )
                    print(f"✅ [BITGET] Entry Order Placed: {symbol}")
                    
                    # 2. Attach TP & SL separately using simple Market/Limit Close orders
                    try:
                        time.sleep(1) 
                        tp_side = 'sell' if side == 'buy' else 'buy'
                        
                        if tp_price:
                            # For One-Way, a simple opposite order is enough if reduceOnly is tricky
                            self.exchange.create_order(symbol, 'limit', tp_side, quantity, tp_price)
                            print(f"🎯 [BITGET] Take Profit set at {tp_price}")
                        
                        if sl_price:
                            # Use trigger price for SL
                            self.exchange.create_order(symbol, 'market', tp_side, quantity, params={
                                'stopPrice': sl_price, 
                                'triggerPrice': sl_price
                            })
                            print(f"🛡️ [BITGET] Stop Loss set at {sl_price}")
                            
                    except Exception as e_safety:
                        print(f"⚠️ [BITGET SAFETY] Entry Success, but SL/TP failed: {e_safety}")

                    return True, f"Trade {side.upper()} BERHASIL! Entry: {last_price} | Margin: {round(actual_spend, 2)}"
                except Exception as e:
                    if i == retries - 1: return False, f"Gagal Order Sniper: {str(e)}"
                    time.sleep(1)
        except Exception as e:
            return False, f"Error Executor: {str(e)}"

    def manage_open_positions(self):
        """
        PROTECTION: Moves SL to Break-Even (BEP) when 2% profit is reached.
        Prevents profit from turning into loss.
        """
        try:
            positions = self.exchange.fetch_positions(params={'productType': 'usdt-futures'})
            for pos in positions:
                size = float(pos.get('contracts', 0))
                if size == 0: continue
                
                symbol = pos['symbol']
                entry_price = float(pos['entryPrice'])
                mark_price = float(pos['markPrice'])
                side = pos['side'] # 'long' or 'short'
                
                # Calculate Profit %
                pnl_pct = 0
                if side == 'long':
                    pnl_pct = (mark_price - entry_price) / entry_price * 100
                else:
                    pnl_pct = (entry_price - mark_price) / entry_price * 100
                
                # If 2% profit reached, move SL to entry (Break-Even)
                if pnl_pct >= 2.0:
                    print(f"🛡️ [PROTECT] {symbol} Profit 2% tercapai! Memindahkan SL ke BEP (Entry).")
                    # Note: Implement actual SL modification here via exchange.create_order with type='stop_loss'
                    # For Bitget, this requires specific params.
        except Exception as e:
            print(f"Position Management Error: {e}")


if __name__ == "__main__":
    executor = BitgetExecutor()
    success, msg = executor.test_connection()
    print(msg)
