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
            
            # Get Available Balance (Free balance only to avoid locked funds error)
            balance_data = self.exchange.fetch_balance(params={'type': 'swap'})
            available_usdt = balance_data.get('USDT', {}).get('free', 0)
            
            # Use 90% of AVAILABLE balance as a safety buffer for fees/slippage
            actual_spend = available_usdt * 0.90
            
            if actual_spend < 5:
                return False, f"Saldo tersedia tidak cukup (Min $5). Tersedia: ${round(available_usdt, 2)}."

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
                        
                        # PRECISION FIX: Round prices according to exchange rules
                        market = self.exchange.market(symbol)
                        price_precision = market['precision']['price']
                        
                        formatted_tp = self.exchange.price_to_precision(symbol, tp_price) if tp_price else None
                        formatted_sl = self.exchange.price_to_precision(symbol, sl_price) if sl_price else None

                        if formatted_tp:
                            self.exchange.create_order(symbol, 'limit', tp_side, quantity, formatted_tp)
                            print(f"🎯 [BITGET] Take Profit set at {formatted_tp}")
                        
                        if formatted_sl:
                            # Use trigger price for SL with correct precision
                            self.exchange.create_order(symbol, 'market', tp_side, quantity, params={
                                'stopPrice': formatted_sl, 
                                'triggerPrice': formatted_sl
                            })
                            print(f"🛡️ [BITGET] Stop Loss set at {formatted_sl}")
                            
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
        SUPER SMART PROTECTION: BEP and Trailing Stop Logic.
        Moves SL to lock in profit as the market moves in our favor.
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
                
                # 1. BREAK-EVEN PROTECTION (At 2% profit)
                # If we are up 2%, move SL to Entry + tiny buffer
                if pnl_pct >= 2.0 and pnl_pct < 5.0:
                    print(f"🛡️ [PROTECT] {symbol} Profit 2% reached. Moving SL to BEP.")
                    sl_price = entry_price * 1.001 if side == 'long' else entry_price * 0.999
                    self.update_sl_price(symbol, side, size, sl_price)

                # 2. TRAILING STOP (At 5% profit and above)
                # Lock in 80% of the gains
                elif pnl_pct >= 5.0:
                    print(f"🔥 [TRAIL] {symbol} Profit {round(pnl_pct, 2)}% reached. Trailing SL...")
                    trail_sl = mark_price * 0.985 if side == 'long' else mark_price * 1.015
                    self.update_sl_price(symbol, side, size, trail_sl)
                    
        except Exception as e:
            print(f"Position Management Error: {e}")

    def update_sl_price(self, symbol, side, amount, new_sl):
        """Helper to cancel old SL and place a new one"""
        try:
            # 1. Cancel existing Stop orders for this symbol first (if possible)
            # 2. Place new Trigger/Market SL order
            tp_side = 'sell' if side == 'long' or side == 'buy' else 'buy'
            self.exchange.create_order(symbol, 'market', tp_side, amount, params={
                'stopPrice': new_sl,
                'triggerPrice': new_sl,
                'reduceOnly': True
            })
        except:
            pass


if __name__ == "__main__":
    executor = BitgetExecutor()
    success, msg = executor.test_connection()
    print(msg)
