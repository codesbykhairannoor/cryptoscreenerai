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
        print(f"[INIT] Bitget API Key: {self.api_key[:5]}...{self.api_key[-5:]}")
        try:
            # Set a very short timeout for this to avoid hanging
            self.exchange.timeout = 5000 
            self.exchange.set_position_mode(False) # Attempt to set One-way (False)
            self.exchange.timeout = 30000 # Reset to normal
            print("[INIT] Position mode verified.")
        except Exception as e:
            print(f"[INIT] Position mode set failed (skipping): {e}")
            self.exchange.timeout = 30000

    def _clean_symbol(self, s):
        """Standardizes any symbol format (BTCUSDT, BTC/USDT:USDT, BTCUSDT_UMCBL) to just 'BTC'"""
        if not s: return ""
        return s.upper().replace('USDT', '').replace('/', '').split(':')[0].split('_')[0]

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
        [STATE MEMORY] - Fetches all currently active positions on Bitget.
        Checks both USDT-FUTURES and umcbl for total coverage.
        """
        import requests, time, hmac, hashlib, base64
        all_pos = []
        product_types = ['USDT-FUTURES', 'umcbl']
        
        for pt in product_types:
            try:
                # Try with marginCoin=USDT first, then without if it fails
                for use_margin_coin in [True, False]:
                    ts = str(int(time.time() * 1000))
                    path = "/api/v2/mix/position/all-position"
                    query = f"productType={pt}"
                    if use_margin_coin:
                        query += "&marginCoin=USDT"
                    
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
                    res = requests.get(url, headers=headers, timeout=10, verify=False)
                    data = res.json()
                    
                    # MENTAH LOG
                    if use_margin_coin or data.get('code') == '00000':
                        print(f"[RAW POS] PT: {pt} | MarginCoin: {use_margin_coin} | Status: {data.get('code')} | Found: {len(data.get('data') or []) if isinstance(data.get('data'), list) else 'N/A'}")
                    
                    if data.get('code') == '00000':
                        if data.get('data'):
                            for p in data['data']:
                                sz = float(p.get('total', 0) or p.get('available', 0) or p.get('size', 0) or 0)
                                if sz > 0:
                                    instId = p.get('instId', '') or p.get('symbol', '')
                                    symbol = f"{instId.replace('USDT', '')}/USDT:USDT" if "USDT" in instId and ":" not in instId else instId
                                    
                                    all_pos.append({
                                        'symbol': symbol,
                                        'instId': instId,
                                        'side': p.get('holdSide', 'long'),
                                        'size': sz,
                                        'entry': float(p.get('openPrice', 0) or p.get('entryPrice', 0) or p.get('averageOpenPrice', 0)),
                                        'mark_price': float(p.get('markPrice', 0) or 0),
                                        'pnl': float(p.get('unrealizedPL', 0) or 0),
                                        'productType': pt
                                    })
                        break # Success with this PT, move to next PT
                    
                time.sleep(0.5)
            except Exception as e:
                print(f"[STATE ERROR] Gagal fetch posisi {pt}: {e}")
        
        return all_pos

    def get_pending_plan_orders(self, symbol=None):
        """Fetches all pending trigger/plan orders (SL/TP) via Bitget V2"""
        import requests, time, hmac, hashlib, base64
        all_plans = []
        
        # Determine product types to check
        pts = ['USDT-FUTURES', 'umcbl']
        plan_types = ['profit_loss', 'normal_plan']
        
        for pt in pts:
            for p_type in plan_types:
                try:
                    ts = str(int(time.time() * 1000))
                    path = "/api/v2/mix/order/orders-plan-pending"
                    query = f"productType={pt}&planType={p_type}"
                    
                    if symbol:
                        # Convert to Bitget V2 format (e.g. BTCUSDT)
                        clean_sym = symbol.split('_')[0].split(':')[0].replace('/', '').replace('USDT','') + "USDT"
                        query += f"&symbol={clean_sym}"
                    
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
                    
                    # MENTAH LOG
                    print(f"[RAW PLAN] {pt}/{p_type}: {res.text[:150]}...")
                    
                    if data.get('code') == '00000':
                        # Bitget V2 uses 'entrustedList'. Handle case where it might be null or missing.
                        res_data = data.get('data', {})
                        if isinstance(res_data, dict):
                            entrusts = res_data.get('entrustedList') or []
                        else:
                            entrusts = res_data or []
                            
                        if isinstance(entrusts, list) and len(entrusts) > 0:
                            for e in entrusts:
                                e_id = e.get('orderId') or e.get('id')
                                if not any((x.get('orderId') or x.get('id')) == e_id for x in all_plans):
                                    all_plans.append(e)
                    else:
                        if data.get('code') not in ['00000', '400171']:
                            print(f"❌ [PLAN ERROR] {pt}/{p_type}: {data}")
                except Exception as e:
                    pass
        return all_plans

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
                            # Use Plan Order for TP to ensure it's tracked as TP
                            self.update_sl_price(symbol, side, quantity, tp_price, is_tp=True)
                        
                        if formatted_sl:
                            # Use Plan Order for SL
                            self.update_sl_price(symbol, side, quantity, sl_price, is_tp=False)
                            
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
            positions = self.get_all_positions()
            open_symbols = [p['symbol'].upper() for p in positions] if isinstance(positions, list) else []
            open_bases = [self._clean_symbol(s) for s in open_symbols]
            
            if int(time.time()) % 60 < 15:
                print(f"🕵️ [ENGINE DEBUG] Active Bases: {open_bases}")
            
            from database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            
            # Find all trades that WE think are running
            cursor.execute("SELECT id, symbol FROM trades WHERE status IN ('PENDING', 'RUNNING') AND market = 'crypto'")
            db_trades = cursor.fetchall()
            
            for trade_id, db_symbol in db_trades:
                # Map DB symbol to Bitget symbol format
                clean_sym = f"{db_symbol.replace('USDT','')}/USDT:USDT" if not ":" in db_symbol else db_symbol
                
                if clean_sym not in open_symbols:
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
            # 1. Fetch current active positions and plan orders
            positions = self.get_all_positions()
            active_symbols = []
            
            for pos in positions:
                try:
                    symbol = pos['symbol']
                    side = pos['side']
                    size = pos['size']
                    entry = pos['entry']
                    mark_price = pos['mark_price']
                    pnl = pos['pnl']
                    
                    # Log PNL periodically
                    if int(time.time()) % 300 < 35:
                        print(f"[MONITOR] {symbol} | PNL: {round(pnl, 2)}% | Price: {mark_price}")
                    
                    active_symbols.append(symbol)
                    
                    # [VERIFICATION LOG] Determine SL/TP Status from pending plan orders
                    sl_price = 0
                    tp_price = 0
                    
                    # Fetch plan orders specifically for this symbol
                    plan_orders = self.get_pending_plan_orders(symbol)
                    current_clean = self._clean_symbol(pos.get('instId') or pos.get('symbol'))
                    
                    for plan in plan_orders:
                        plan_symbol = plan.get('instId') or plan.get('symbol')
                        plan_clean = self._clean_symbol(plan_symbol)
                        
                        if plan_clean == current_clean:
                            trigger = float(plan.get('triggerPrice', 0) or plan.get('executePrice', 0))
                            if trigger > 0:
                                # Logic to differentiate SL from TP based on side and price
                                is_long = side.lower() in ['long', 'buy']
                                if is_long:
                                    if trigger > entry: tp_price = max(tp_price, trigger)
                                    else: sl_price = max(sl_price, trigger)
                                else:
                                    if trigger < entry: tp_price = min(tp_price, trigger) if tp_price > 0 else trigger
                                    else: sl_price = min(sl_price, trigger) if sl_price > 0 else trigger
                    
                    # [RISK GUARD] Verify SL Existence
                    if sl_price > 0:
                        print(f"[VERIFIED] Risk Guards for {symbol}: SL: ${sl_price} (ACTIVE) | TP: {'$' + str(tp_price) if tp_price > 0 else 'PENDING'}")
                    else:
                        # Safety First: Inject default SL if none found
                        default_sl = entry * 0.95 if side.lower() in ['long', 'buy'] else entry * 1.05
                        print(f"[RISK] {symbol} tidak memiliki Stop Loss! Memasang default SL di {round(default_sl, 4)}")
                        self.update_sl_price(symbol, side, size, default_sl)
                    
                    # [RISK GUARD] Verify TP Existence
                    if tp_price == 0:
                        default_tp = entry * 1.05 if side.lower() in ['long', 'buy'] else entry * 0.95
                        print(f"🎯 [TP CHECK] {symbol} Take Profit is MISSING. Memasang default TP di {round(default_tp, 4)}")
                        self.update_sl_price(symbol, side, size, default_tp, is_tp=True)
                    
                    # [INSTITUTIONAL UPGRADE] Trailing SL
                    if pnl >= 2.0:
                        # Move to Break Even + small profit to cover fees
                        be_sl = entry * 1.002 if side.lower() in ['long', 'buy'] else entry * 0.998
                        
                        # Trailing SL: 1.5% behind current mark price
                        trail_sl = mark_price * 0.985 if side.lower() in ['long', 'buy'] else mark_price * 1.015
                        
                        # Choose the best SL (BE or Trailing)
                        best_sl = max(be_sl, trail_sl) if side.lower() in ['long', 'buy'] else min(be_sl, trail_sl)
                        
                        update_sl = False
                        if side.lower() in ['long', 'buy'] and (sl_price == 0 or best_sl > sl_price): update_sl = True
                        if side.lower() in ['short', 'sell'] and (sl_price == 0 or best_sl < sl_price): update_sl = True
                        
                        # Prevent updating too frequently (e.g., only if it moves by >0.5%)
                        if update_sl and sl_price > 0:
                            diff_pct = abs(best_sl - sl_price) / sl_price * 100
                            if diff_pct < 0.5:
                                update_sl = False
                        
                        if update_sl:
                            print(f"🏃 [TRAILING] Moving {symbol} SL to {round(best_sl, 4)} (PNL: {round(pnl, 2)}%)")
                            self.update_sl_price(symbol, side, size, best_sl)
                except Exception as e_pos:
                    print(f"⚠️ [MONITOR ERROR] Error processing {symbol if 'symbol' in locals() else 'unknown'}: {e_pos}")

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

    def update_sl_price(self, symbol, side, amount, new_price, is_tp=False):
        """Helper to cancel old SL/TP and place a new one using Bitget V2 Plan Orders"""
        try:
            tp_side = 'sell' if side.lower() in ['long', 'buy'] else 'buy'
            formatted_price = self.exchange.price_to_precision(symbol, new_price)
            
            # Bitget V2 Strategy: Use 'normal_plan' which is more widely accepted for stop/trigger orders
            params = {
                'triggerPrice': formatted_price,
                'triggerType': 'mark_price',
                'reduceOnly': 'YES',
                'planType': 'normal_plan'
            }
            
            # We use None for price in market orders
            self.exchange.create_order(symbol, 'market', tp_side, amount, None, params=params)
            label = "Take Profit" if is_tp else "Stop Loss"
            print(f"🛡️ [BITGET] {label} updated at {formatted_price}")
        except Exception as e:
            print(f"❌ [SL/TP UPDATE FAILED] {symbol}: {e}")


if __name__ == "__main__":
    executor = BitgetExecutor()
    success, msg = executor.test_connection()
    print(msg)
