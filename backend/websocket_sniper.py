import hmac
import hashlib
import base64
import asyncio
import json
import websockets
import os
import time
import requests
from dotenv import load_dotenv
from bitget_executor import BitgetExecutor
from database import log_trade

load_dotenv()

class BitgetPrivateWS:
    """
    [THE SAFETY KING] - Private WebSocket for Instant SL/TP
    Listens to 'order' and 'account' updates directly from Bitget.
    """
    def __init__(self):
        self.url = "wss://ws.bitget.com/v2/ws/private"
        self.api_key = os.getenv("BITGET_API_KEY")
        self.secret_key = os.getenv("BITGET_SECRET_KEY")
        self.passphrase = os.getenv("BITGET_PASSPHRASE")
        self.executor = BitgetExecutor()
        self.is_running = True

    def get_signature(self, timestamp):
        message = str(timestamp) + 'GET' + '/user/verify'
        mac = hmac.new(bytes(self.secret_key, encoding='utf8'), bytes(message, encoding='utf8'), digestmod=hashlib.sha256)
        return base64.b64encode(mac.digest()).decode('utf8')

    async def heartbeat(self, ws):
        """Send 'ping' every 20s to keep private connection alive"""
        while self.is_running:
            try:
                await ws.send("ping")
                await asyncio.sleep(20)
            except:
                break

    async def login(self, ws):
        ts = int(time.time() * 1000)
        login_msg = {
            "op": "login",
            "args": [{
                "apiKey": self.api_key,
                "passphrase": self.passphrase,
                "timestamp": str(ts),
                "sign": self.get_signature(ts)
            }]
        }
        await ws.send(json.dumps(login_msg))
        print("🔐 [PRIVATE WS] Login request sent...")

    async def subscribe(self, ws):
        # Subscribe to Order & Account updates (USDT-FUTURES mode)
        subs = {
            "op": "subscribe",
            "args": [
                {"instType": "USDT-FUTURES", "channel": "order", "instId": "default"},
                {"instType": "USDT-FUTURES", "channel": "orders-algo", "instId": "default"},
                {"instType": "USDT-FUTURES", "channel": "account", "instId": "default"}
            ]
        }
        await ws.send(json.dumps(subs))
        print("🛰️ [PRIVATE WS] Subscribed to Order, Algo (SL/TP), and Account Updates!")

    async def listen(self):
        while self.is_running:
            try:
                async with websockets.connect(self.url) as ws:
                    # 1. Start heartbeat
                    asyncio.create_task(self.heartbeat(ws))
                    
                    # 2. Login
                    await self.login(ws)
                    
                    # 3. Wait for login success
                    resp = await ws.recv()
                    print(f"🔓 [PRIVATE WS] Login Response: {resp}")
                    
                    # 3. Subscribe
                    await self.subscribe(ws)
                    
                    # 4. Listen Loop
                    while True:
                        msg = await ws.recv()
                        if msg == "pong": continue
                        
                        data = json.loads(msg)
                        action = data.get("action")
                        arg = data.get("arg", {})
                        channel = arg.get("channel")
                        from shared_state import state
                        
                        if channel == "order" and "data" in data:
                            state.last_order_update = time.time()
                            for order in data["data"]:
                                status = order.get("orderStatus")
                                symbol = order.get("symbol")
                                current_orders = state.orders
                                current_orders = [o for o in current_orders if o.get('orderId') != order.get('orderId')]
                                if status not in ['filled', 'canceled']:
                                    current_orders.append(order)
                                state.update_orders(current_orders)
                                if status == "filled":
                                    print(f"✅ [PRIVATE WS] EKSEKUSI: {symbol} filled!")
                                    self.executor.sync_state_with_exchange()
                                    
                        elif channel == "orders-algo" and "data" in data:
                            state.last_algo_update = time.time()
                            for plan in data["data"]:
                                status = plan.get("state") or plan.get("status")
                                sym = plan.get("symbol") or plan.get("instId")
                                # RAW ALGO LOG: Now includes instId for identification
                                print(f"📡 [ALGO STREAM] {sym} | State: {status} | Type: {plan.get('planType')} | ID: {plan.get('orderId')}")
                                
                                current_orders = state.orders
                                current_orders = [o for o in current_orders if o.get('orderId') != plan.get('orderId')]
                                if status in ['live', 'not_trigger', 'executed', 'partially_executed']: 
                                    current_orders.append(plan)
                                state.update_orders(current_orders)
                                
                        elif channel == "account":
                            state.last_acc_update = time.time()
                            for acc in data.get("data", []):
                                state.update_balance(acc.get('marginCoin'), acc)

            except Exception as e:
                print(f"🔄 [PRIVATE WS RECONNECT] Error: {e}")
                await asyncio.sleep(5)

class BitgetWebSocketSniper:
    def __init__(self):
        # Upgrade to V2 for better stability
        self.url = "wss://ws.bitget.com/v2/ws/public"
        self.executor = BitgetExecutor()
        self.is_running = True
        self.last_trade_time = {}

    async def heartbeat(self, ws):
        """Send 'ping' every 20s to keep connection alive (V2 Requirement)"""
        while True:
            try:
                await ws.send("ping")
                await asyncio.sleep(20)
            except:
                break

    async def subscribe(self, ws):
        # Bitget V2 USDT-FUTURES Subscription
        subs = {
            "op": "subscribe",
            "args": [
                {"instType": "USDT-FUTURES", "channel": "ticker", "instId": "BTCUSDT"},
                {"instType": "USDT-FUTURES", "channel": "ticker", "instId": "ETHUSDT"},
                {"instType": "USDT-FUTURES", "channel": "ticker", "instId": "SOLUSDT"},
                {"instType": "USDT-FUTURES", "channel": "ticker", "instId": "XRPUSDT"},
                {"instType": "USDT-FUTURES", "channel": "ticker", "instId": "BCHUSDT"},
                {"instType": "USDT-FUTURES", "channel": "ticker", "instId": "LTCUSDT"},
                {"instType": "USDT-FUTURES", "channel": "ticker", "instId": "DOGEUSDT"},
                {"instType": "USDT-FUTURES", "channel": "ticker", "instId": "PEPEUSDT"}
            ]
        }
        await ws.send(json.dumps(subs))
        print("🛰️ [WS V2] Subscribed to Public Stream (BTC, ETH, SOL, XRP, BCH, LTC, DOGE, PEPE)!")

    async def listen(self):
        while self.is_running:
            try:
                print(f"📡 [WS] Connecting to {self.url}...")
                async with websockets.connect(self.url) as ws:
                    asyncio.create_task(self.heartbeat(ws))
                    await self.subscribe(ws)
                    
                    while True:
                        message = await ws.recv()
                        if message == "pong": continue
                        
                        data = json.loads(message)
                        if "data" in data:
                            # Volatility spike detection logic remains here
                            pass
            except Exception as e:
                print(f"🔄 [WS RECONNECT] Error: {e}. Retrying in 5s...")
                await asyncio.sleep(5)

async def main():
    # Run Public and Private WS in parallel
    public_ws = BitgetWebSocketSniper()
    private_ws = BitgetPrivateWS()
    
    await asyncio.gather(
        public_ws.listen(),
        private_ws.listen()
    )

if __name__ == "__main__":
    asyncio.run(main())
