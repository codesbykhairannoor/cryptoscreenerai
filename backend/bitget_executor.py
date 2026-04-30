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
                    return {
                        'total': balance['USDT'].get('total', 0),
                        'free': balance['USDT'].get('free', 0)
                    }
            except Exception as e:
                if i == retries - 1: print(f"Balance fetch error after {retries} attempts: {e}")
                time.sleep(1) # Wait before retry
        return {'total': 0, 'free': 0}

    def get_all_positions(self):
        """
        [STATE MEMORY] - Fetches all currently active positions on Bitget using V3 API directly.
        """
        import requests, time, hmac, hashlib, base64
        try:
            ts = str(int(time.time() * 1000))
            path = "/api/v2/mix/position/all-position"
            query = "productType=USDT-FUTURES&marginCoin=USDT"
            
            message = ts + "GET" + path + "?" + query
            mac = hmac.new(bytes(self.secret_key, encoding='utf8'), bytes(message, encoding='utf8'), digestmod=hashlib.sha256)
            sign = base64.b64encode(mac.digest()).decode('utf8')
            
            headers = {
                "ACCESS-KEY": self.api_key,
                "ACCESS-SIGN": sign,
                "ACCESS-TIMESTAMP": ts,
                "ACCESS-PASSPHRASE": self.passphrase,
                "Content-Type": "application/json"
            }
            
            url = f"https://api.bitget.com{path}?{query}"
            res = requests.get(url, headers=headers, timeout=5)
            data = res.json()
            
            if data.get('code') == '00000' and 'data' in data:
                positions = []
                for p in data['data']:
                    size = float(p.get('size', 0) or p.get('total', 0))
                    if size > 0:
                        instId = p.get('instId', '') or p.get('symbol', '')
                        # Convert Bitget V2 instId/symbol to CCXT format
                        symbol = f"{instId.replace('USDT', '')}/USDT:USDT" if "USDT" in instId and ":" not in instId else instId
                        
                        raw_entry = p.get('openPriceAvg') or p.get('averageOpenPrice') or p.get('entryPrice') or 0
                        
                        positions.append({
                            'symbol': symbol, 
                            'instId': instId,
                            'size': size, 
                            'entryPrice': float(raw_entry),
                            'markPrice': float(p.get('markPrice', 0)),
                            'side': p.get('holdSide', 'long')
                        })
                return positions
            else:
                print(f"⚠️ [STATE ERROR] V2 API Response: {res.text}")
                return []
        except Exception as e:
            print(f"⚠️ [STATE ERROR] Gagal fetch posisi V2: {e}")
            return []

    def get_pending_plan_orders(self):
        """Fetches all pending trigger/plan orders (SL/TP) via Bitget V2"""
        import requests, time, hmac, hashlib, base64
        try:
            ts = str(int(time.time() * 1000))
            path = "/api/v2/mix/order/orders-plan-pending"
            query = "productType=USDT-FUTURES"
            
            message = ts + "GET" + path + "?" + query
            mac = hmac.new(bytes(self.secret_key, encoding='utf8'), bytes(message, encoding='utf8'), digestmod=hashlib.sha256)
            sign = base64.b64encode(mac.digest()).decode('utf8')
            
            headers = {
                "ACCESS-KEY": self.api_key,
                "ACCESS-SIGN": sign,
                "ACCESS-TIMESTAMP": ts,
                "ACCESS-PASSPHRASE": self.passphrase,
                "Content-Type": "application/json"
            }
            
            url = f"https://api.bitget.com{path}?{query}"
            res = requests.get(url, headers=headers, timeout=5)
            data = res.json()
            
            if data.get('code') == '00000':
                return data.get('data', {}).get('entrustList', []) if isinstance(data.get('data'), dict) else data.get('data', [])
            return []
        except Exception as e:
            print(f"⚠️ [PLAN ERROR] Gagal fetch plan orders: {e}")
            return []

    def get_max_available(self, symbol, leverage):
        """
        [DYNAMIC SIZING] - Asks Bitget: "What's the max I can open for this koin?"
        Prevents 'Insufficient Margin' errors.
        """
        try:
            if not ":" in symbol:
                symbol = f"{symbol}/USDT:USDT" if "USDT" not in symbol else f"{symbol.replace('USDT','')}/USDT:USDT"
            
            # Fetch max available from exchange
            params = {
                'symbol': symbol.replace("/","").replace(":USDT",""),
                'leverage': leverage
            }
            # Bitget V3 specific endpoint via CCXT
            res = self.exchange.private_get_mix_v1_account_account(params)
            if res.get('code') == '00000':
                return float(res['data'].get('available', 0))
        except:
            pass
        
        # Fallback to manual calc if API fails
        bal = self.get_balance_robust()
        return bal['free'] * 0.95 # Safe buffer

    def test_connection(self):
        try:
            if not self.api_key:
                return False, "API Key Bitget tidak ditemukan di .env"
            
            print(f"Testing connection with Key: {self.api_key[:10]}...")
            
            bal = self.get_balance_robust()
            if bal['total'] > 0:
                return True, f"Bitget Futures OK (Saldo: ${round(bal['total'], 2)})"
            
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
            
            # 1. DYNAMIC SIZING (The "Anti-Margin Error" Pillar)
            # Ask bursa: "Berapa max gue bisa open buat koin ini?"
            max_available = self.get_max_available(symbol, leverage)
            
            # Use 95% of MAX available as a safety buffer
            actual_spend = max_available * 0.95
            
            if actual_spend < 5:
                return False, f"Saldo tersedia tidak cukup (Min $5). Max Available: ${round(max_available, 2)}."

            ticker = self.exchange.fetch_ticker(symbol)
            last_price = ticker['last']
            
            # SLIPPAGE PROTECTION: Calculate Limit Price (0.5% offset)
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
                                'triggerType': 'mark_price',
                                'reduceOnly': True 
                            })
                            print(f"🛡️ [BITGET] Stop Loss set at {formatted_sl} (Trigger: Mark Price)")
                            
                    except Exception as e_safety:
                        print(f"⚠️ [BITGET SAFETY] Entry Success, but SL/TP failed: {e_safety}")

                    return True, f"Trade {side.upper()} BERHASIL! Entry: {last_price} | Margin: {round(actual_spend, 2)}"
                except Exception as e:
                    if i == retries - 1: return False, f"Gagal Order Sniper: {str(e)}"
                    time.sleep(1)
        except Exception as e:
            return False, f"Error Executor: {str(e)}"

    def sync_state_with_exchange(self):
        """
        [STATE RECOVERY ENGINE] - Cross-references DB with actual exchange positions.
        Call this on startup to prevent 'Amnesia' after Railway restart.
        """
        print("🔄 [SYNC] Synchronizing bot memory with Bitget...")
        try:
            active_positions = self.get_all_positions()
            active_symbols = [p['symbol'] for p in active_positions]
            
            from database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            
            # Find all trades that WE think are running
            cursor.execute("SELECT id, symbol FROM trades WHERE status IN ('PENDING', 'RUNNING') AND market = 'crypto'")
            db_trades = cursor.fetchall()
            
            for trade_id, db_symbol in db_trades:
                # Map DB symbol to Bitget symbol format
                clean_sym = f"{db_symbol.replace('USDT','')}/USDT:USDT" if not ":" in db_symbol else db_symbol
                
                if clean_sym not in active_symbols:
                    print(f"⚠️ [RECOVERY] {db_symbol} not found on exchange. Marking as CLOSED.")
                    cursor.execute("UPDATE trades SET status = 'CLOSED' WHERE id = %s", (trade_id,))
                    # Also cancel any orphaned SL/TP orders
                    try:
                        self.exchange.cancel_all_orders(clean_sym)
                    except:
                        pass
                else:
                    print(f"✅ [RECOVERY] {db_symbol} is active and verified.")
            
            conn.commit()
            conn.close()
            print("✨ [SYNC] Memory synchronization complete.")
        except Exception as e:
            print(f"❌ [SYNC ERROR] {e}")

    def manage_open_positions(self):
        """
        [AUTO-CLEANUP ENGINE] - BEP, Trailing, and Orphaned Order Purge.
        Ensures margin is released immediately after a trade ends.
        """
        try:
            # 1. Fetch current active positions from Native Bitget V2 API instead of CCXT
            positions = self.get_all_positions()
            active_symbols = []
            
            # Fetch pending plan orders to check actual SL/TP
            plan_orders = self.get_pending_plan_orders()
            
            for pos in positions:
                size = pos['size']
                if size > 0:
                    active_symbols.append(pos['symbol'])
                    
                    symbol = pos['symbol']
                    entry_price = pos['entryPrice']
                    mark_price = pos['markPrice']
                    side = pos['side']
                    
                    pnl_pct = 0
                    if entry_price > 0:
                        if side == 'long':
                            pnl_pct = (mark_price - entry_price) / entry_price * 100
                        else:
                            pnl_pct = (entry_price - mark_price) / entry_price * 100
                    print(f"📊 [MONITOR] {symbol} | PNL: {round(pnl_pct, 2)}% | Price: {mark_price}")
                    
                    # [VERIFICATION LOG] Determine SL/TP Status from pending plan orders
                    sl_price = 0
                    tp_price = 0
                    for plan in plan_orders:
                        if plan.get('instId') == pos.get('instId') or plan.get('symbol') == pos.get('instId'):
                            trigger = float(plan.get('triggerPrice', 0))
                            if trigger > 0:
                                if side == 'long':
                                    if trigger > entry_price: tp_price = trigger
                                    else: sl_price = trigger
                                else:
                                    if trigger < entry_price: tp_price = trigger
                                    else: sl_price = trigger
                                    
                    # Auto-inject Default SL if missing to protect user capital
                    if sl_price == 0:
                        default_sl = entry_price * 0.95 if side == 'long' else entry_price * 1.05
                        print(f"⚠️ [RISK] {symbol} tidak memiliki Stop Loss! Memasang default SL di {round(default_sl, 4)}")
                        self.update_sl_price(symbol, side, size, default_sl)
                        sl_price = default_sl
                        
                    sl_text = f"${round(sl_price, 4)} (ACTIVE)" if sl_price > 0 else "PENDING"
                    tp_text = f"${round(tp_price, 4)} (ACTIVE)" if tp_price > 0 else "PENDING"
                    print(f"🛡️ [VERIFIED] Risk Guards for {symbol}: SL: {sl_text} | TP: {tp_text}")
                    
                    # [INSTITUTIONAL UPGRADE] Partial Take Profit & Safety Guard
                    if pnl_pct >= 2.0 and pnl_pct < 5.0:
                        # Check if we already did partial by checking if SL is at Break-Even or better
                        already_secured = False
                        if side == 'long' and sl_price >= entry_price: already_secured = True
                        if side == 'short' and sl_price <= entry_price and sl_price > 0: already_secured = True
                        
                        if not already_secured:
                            new_sl_price = entry_price * 1.002 if side == 'long' else entry_price * 0.998
                            print(f"💰 [PARTIAL TP] Profit 2% tercapai di {symbol}! Menutup 50% posisi untuk amankan modal.")
                            
                            try:
                                # Close 50% of the position
                                close_side = 'sell' if side == 'long' else 'buy'
                                partial_size = size * 0.5
                                self.exchange.create_order(symbol, 'market', close_side, partial_size, params={'reduceOnly': True})
                                
                                print(f"🛡️ [SECURE] Memindahkan sisa posisi ke Break-Even (${round(new_sl_price, 4)}).")
                                self.update_sl_price(symbol, side, partial_size, new_sl_price)
                            except Exception as e_ptp:
                                print(f"⚠️ [PTP ERROR] Gagal eksekusi partial: {e_ptp}")
                                
                    elif pnl_pct >= 5.0:
                        trail_sl = mark_price * 0.985 if side == 'long' else mark_price * 1.015
                        
                        update_trail = False
                        if side == 'long' and trail_sl > sl_price: update_trail = True
                        if side == 'short' and (sl_price == 0 or trail_sl < sl_price): update_trail = True
                        
                        if update_trail:
                            print(f"🏃 [TRAIL] Menggeser Trailing Stop {symbol} ke ${round(trail_sl, 4)}.")
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
                    is_active = any(db_symbol.replace("USDT","") in s for s in active_symbols)
                    
                    if not is_active:
                        print(f"🧹 [CLEANUP] {db_symbol} sudah tertutup di bursa. Membersihkan orphaned orders...")
                        try:
                            clean_sym = f"{db_symbol.replace('USDT','')}/USDT:USDT" if not ":" in db_symbol else db_symbol
                            self.exchange.cancel_all_orders(clean_sym)
                            cursor.execute("UPDATE trades SET status = 'CLOSED' WHERE symbol = %s AND market = 'crypto'", (db_symbol,))
                            conn.commit()
                        except Exception as e_clean:
                            pass
            except Exception as e_db:
                print(f"❌ [DB MONITOR ERROR] {e_db}")
            finally:
                if conn:
                    conn.close()
                    
        except Exception as e:
            print(f"⚠️ [MONITOR ERROR] {e}")

    def update_sl_price(self, symbol, side, amount, new_sl):
        """Helper to cancel old SL and place a new one"""
        try:
            # Bitget V2 Trigger Order
            tp_side = 'sell' if side == 'long' or side == 'buy' else 'buy'
            # Cancel all previous plan orders to avoid overlap
            try:
                self.exchange.cancel_all_orders(symbol, params={'planType': 'normal_plan'})
            except:
                pass
                
            # Format price precision
            formatted_sl = self.exchange.price_to_precision(symbol, new_sl)
            
            self.exchange.create_order(symbol, 'market', tp_side, amount, params={
                'triggerPrice': formatted_sl,
                'triggerType': 'mark_price',
                'reduceOnly': True
            })
        except Exception as e:
            print(f"❌ [SL UPDATE FAILED] {symbol}: {e}")


if __name__ == "__main__":
    executor = BitgetExecutor()
    success, msg = executor.test_connection()
    print(msg)
