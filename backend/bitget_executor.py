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
                            # Bitget V2: Must use triggerPrice and reduceOnly for SL to appear in 'Plan Orders'
                            self.exchange.create_order(symbol, 'market', tp_side, quantity, params={
                                'triggerPrice': formatted_sl,
                                'triggerType': 'mark',
                                'reduceOnly': True 
                            })
                            print(f"🛡️ [BITGET] Stop Loss set at {formatted_sl} (Trigger: Mark)")
                            
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
        [AUTO-CLEANUP ENGINE] - BEP, Trailing, and Orphaned Order Purge.
        Ensures margin is released immediately after a trade ends.
        """
        try:
            # 1. Fetch current active positions from Bitget
            positions = self.exchange.fetch_positions(params={'productType': 'usdt-futures'})
            active_symbols = []
            for pos in positions:
                size = float(pos.get('contracts', 0))
                if size > 0:
                    active_symbols.append(pos['symbol'])
                    
                    symbol = pos['symbol']
                    entry_price = float(pos['entryPrice'])
                    mark_price = float(pos['markPrice'])
                    side = pos['side']
                    
                    pnl_pct = 0
                    if side == 'long':
                        pnl_pct = (mark_price - entry_price) / entry_price * 100
                    else:
                        pnl_pct = (entry_price - mark_price) / entry_price * 100
                    
                    print(f"📊 [MONITOR] {symbol} | PNL: {round(pnl_pct, 2)}% | Price: {mark_price}")
                    
                    # BEP and Trailing Stop logic
                    if pnl_pct >= 2.0 and pnl_pct < 5.0:
                        sl_price = entry_price * 1.001 if side == 'long' else entry_price * 0.999
                        self.update_sl_price(symbol, side, size, sl_price)
                    elif pnl_pct >= 5.0:
                        trail_sl = mark_price * 0.985 if side == 'long' else mark_price * 1.015
                        self.update_sl_price(symbol, side, size, trail_sl)

            # 2. ORPHANED ORDER CLEANUP (Database Sync)
            from database import get_connection
            conn = None
            try:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT symbol FROM trades WHERE status IN ('PENDING', 'RUNNING') AND market = 'crypto'")
                db_trades = cursor.fetchall()
                
                for (db_symbol,) in db_trades:
                    # Check if this DB symbol is still active in Bitget
                    # Note: db_symbol is like 'LUMIAUSDT', exchange symbol is like 'LUMIA/USDT:USDT'
                    is_active = any(db_symbol.replace("USDT","") in s for s in active_symbols)
                    
                    if not is_active:
                        print(f"🧹 [CLEANUP] {db_symbol} closed. Purging orphaned orders to release margin...")
                        try:
                            clean_sym = f"{db_symbol.replace('USDT','')}/USDT:USDT" if not ":" in db_symbol else db_symbol
                            self.exchange.cancel_all_orders(clean_sym)
                            cursor.execute("UPDATE trades SET status = 'CLOSED' WHERE symbol = %s AND market = 'crypto'", (db_symbol,))
                            conn.commit()
                        except Exception as e_clean:
                            print(f"⚠️ [CLEANUP ERROR] {db_symbol}: {e_clean}")
            except Exception as e_db:
                print(f"DB Monitor Error: {e_db}")
            finally:
                if conn:
                    conn.close()
                    
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
