import hmac
import hashlib
import base64
import asyncio
import json
import websockets
import os
import time
import requests
import ssl
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
        # executor dihapus — tidak pernah dipakai (sync sudah di-comment out)
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
        print("[PRIVATE WS] Login request sent...")

    async def subscribe(self, ws):
        subs = {
            "op": "subscribe",
            "args": [
                {"instType": "USDT-FUTURES", "channel": "order", "instId": "default"},
                {"instType": "USDT-FUTURES", "channel": "orders-algo", "instId": "default"},
                {"instType": "USDT-FUTURES", "channel": "account", "instId": "default"},
                {"instType": "USDT-FUTURES", "channel": "positions", "instId": "default"}
            ]
        }
        await ws.send(json.dumps(subs))
        print("[PRIVATE WS] Subscribed to Order, Algo (SL/TP), Account, and Positions!")

    async def listen(self):
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        while self.is_running:
            try:
                async with websockets.connect(self.url, ssl=ssl_context) as ws:
                    asyncio.create_task(self.heartbeat(ws))
                    await self.login(ws)
                    resp = await ws.recv()
                    print(f"[PRIVATE WS] Login Response: {resp}")
                    await self.subscribe(ws)
                    
                    while True:
                        msg = await ws.recv()
                        if msg == "pong": continue
                        data = json.loads(msg)
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
                                    print(f"[PRIVATE WS] EXECUTION: {symbol} filled!")
                                    # self.executor.sync_state_with_exchange() # Removed REST sync
                                    
                        elif channel == "orders-algo" and "data" in data:
                            state.last_algo_update = time.time()
                            current_orders = state.orders
                            for plan in data["data"]:
                                plan_id = plan.get('orderId') or plan.get('planId')
                                status = plan.get("state") or plan.get("status")
                                sym = plan.get("symbol") or plan.get("instId")
                                
                                # Incremental Update: Remove old version of this plan, then add new if active
                                current_orders = [o for o in current_orders if (o.get('orderId') or o.get('planId')) != plan_id]
                                if status in ['live', 'not_trigger', 'active']:
                                    current_orders.append(plan)
                                    
                                print(f"[ALGO STREAM] {sym} | State: {status} | Type: {plan.get('planType')} | ID: {plan_id}")
                            
                            state.update_orders(current_orders)

                        elif channel == "positions" and "data" in data:
                            # Direct Real-time Position Tracking
                            formatted_pos = []
                            for p in data["data"]:
                                sz = float(p.get("total", p.get("holdQty", 0)))
                                if sz > 0:
                                    formatted_pos.append({
                                        'symbol': p.get('symbol', p.get('instId')),
                                        'side': p.get('holdSide', 'long').lower(),
                                        'size': sz,
                                        'entry': float(p.get('openPrice', p.get('average', 0))),
                                        'mark_price': float(p.get('markPrice', 0)),
                                        'pnl': float(p.get('unrealizedPL', 0))
                                    })
                            state.update_positions(formatted_pos)
                            if formatted_pos:
                                print(f"[POSITION STREAM] {len(formatted_pos)} active trades updated via WS.")

                        elif channel == "account":
                            state.last_acc_update = time.time()
                            for acc in data.get("data", []):
                                state.update_balance(acc.get('marginCoin'), acc)

            except Exception as e:
                print(f"[PRIVATE WS RECONNECT] Error: {e}")
                await asyncio.sleep(5)

class BitgetPublicWS:
    """
    [THE HUNTER] - Public WebSocket for Real-time Intelligence
    Tracks Whales, OBI, and Open Interest.
    """
    def __init__(self):
        self.url = "wss://ws.bitget.com/v2/ws/public"
        self.is_running = True
        self.symbols = ["BTCUSDT", "ETHUSDT", "PAXGUSDT", "SOLUSDT", "XRPUSDT", "AAVEUSDT"]

    async def heartbeat(self, ws):
        while self.is_running:
            try:
                await ws.send("ping")
                await asyncio.sleep(20)
            except: break

    async def subscribe(self, ws):
        args = []
        for sym in self.symbols:
            args.append({"instType": "USDT-FUTURES", "channel": "ticker", "instId": sym})
            args.append({"instType": "USDT-FUTURES", "channel": "trade", "instId": sym})
            args.append({"instType": "USDT-FUTURES", "channel": "books5", "instId": sym})
        
        subs = {"op": "subscribe", "args": args}
        await ws.send(json.dumps(subs))
        print(f"[PUBLIC WS] Subscribed to {len(self.symbols)} symbols (Ticker, Trade, L2 Depth)!")

    async def listen(self):
        from shared_state import state
        
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        while self.is_running:
            try:
                async with websockets.connect(self.url, ssl=ssl_context) as ws:
                    asyncio.create_task(self.heartbeat(ws))
                    await self.subscribe(ws)
                    
                    while True:
                        msg = await ws.recv()
                        if msg == "pong": continue
                        data = json.loads(msg)
                        arg = data.get("arg", {})
                        channel = arg.get("channel")
                        symbol = arg.get("instId")
                        
                        if not symbol: continue
                        
                        if channel == "trade" and "data" in data:
                            for t in data["data"]:
                                size_usd = float(t.get("sz", 0)) * float(t.get("px", 0))
                                if size_usd > 50000:
                                    side = "BUY" if t.get("side") == "buy" else "SELL"
                                    state.rt_whale[symbol] = f"WHALE_{side}"
                                    print(f"  [WHALE ALERT] {symbol} | {side} | ${round(size_usd/1000, 1)}K")
                        
                        elif channel == "books5" and "data" in data:
                            for d in data["data"]:
                                bids = sum(float(b[1]) for b in d.get("bids", []))
                                asks = sum(float(a[1]) for a in d.get("asks", []))
                                if (bids + asks) > 0:
                                    state.rt_obi[symbol] = round((bids - asks) / (bids + asks), 4)

                        elif channel == "ticker" and "data" in data:
                            for t in data["data"]:
                                state.rt_price[symbol] = float(t.get("lastPr", 0))
                                if t.get("openInterest"):
                                    state.rt_oi[symbol] = float(t.get("openInterest"))
            except Exception as e:
                print(f"[PUBLIC WS ERROR] {e}")
                await asyncio.sleep(5)

class FinnhubWS:
    """
    [THE ORACLE] - Finnhub WebSocket for Global News & Prices
    Tracks real-time news sentiment and high-fidelity global prices.
    """
    def __init__(self):
        self.api_key = os.getenv("FINNHUB_API_KEY")
        self.url = f"wss://ws.finnhub.io?token={self.api_key}"
        self.is_running = True

    async def heartbeat(self, ws):
        """Kirim ping manual untuk memastikan Finnhub tidak timeout."""
        while self.is_running:
            try:
                await ws.ping()
                await asyncio.sleep(25)
            except:
                break

    async def subscribe(self, ws):
        # Subscribe to News and Major Asset prices
        targets = ["BINANCE:BTCUSDT", "BINANCE:ETHUSDT", "IC MARKETS:1"] # 1 is Gold on some feeds
        for t in targets:
            await ws.send(json.dumps({"type": "subscribe", "symbol": t}))
        
        # Subscribe to real-time news
        await ws.send(json.dumps({"type": "subscribe-news", "symbol": "AAPL"})) # Broad market news
        print("[FINNHUB WS] Subscribed to Premium News and Global Assets!")

    def analyze_sentiment(self, text):
        # Simple high-speed institutional sentiment logic
        positive = ["surge", "bullish", "growth", "win", "buy", "jump", "success", "approved", "inflow"]
        negative = ["crash", "bearish", "dump", "fall", "sell", "drop", "failure", "rejected", "outflow", "warn"]
        
        score = 0
        text = text.lower()
        for p in positive: 
            if p in text: score += 0.2
        for n in negative: 
            if n in text: score -= 0.2
        return max(-1, min(1, score))

    async def listen(self):
        from shared_state import state
        
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        while self.is_running:
            try:
                # Tambahkan ping_interval & ping_timeout untuk stabilitas lebih tinggi
                async with websockets.connect(
                    self.url, 
                    ssl=ssl_context,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10
                ) as ws:
                    asyncio.create_task(self.heartbeat(ws))
                    await self.subscribe(ws)
                    while True:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=60)
                        except asyncio.TimeoutError:
                            # Jika 60 detik tidak ada data, kirim ping manual
                            await ws.ping()
                            continue
                            
                        data = json.loads(msg)
                        m_type = data.get("type")
                        
                        if m_type == "news" and "data" in data:
                            for n in data["data"]:
                                headline = n.get("headline", "")
                                score = self.analyze_sentiment(headline)
                                state.rt_news.append({"headline": headline, "score": score, "time": time.time()})
                                if len(state.rt_news) > 50: state.rt_news.pop(0)
                                print(f"[NEWS] {headline[:60]}... | Sentiment: {score}")

                                # TRIGGER NEWS SNIPER kalau sentiment kuat
                                if abs(score) >= 0.2:
                                    try:
                                        from news_sniper import get_sniper_instance
                                        sniper = get_sniper_instance()
                                        sniper.process_finnhub_news(headline, score)
                                    except Exception as e:
                                        print(f"[FINNHUB SNIPER ERROR] {e}")
                                
                        elif m_type == "trade" and "data" in data:
                            for t in data["data"]:
                                sym = t.get("s")
                                price = float(t.get("p", 0))
                                state.rt_price[f"FINNHUB:{sym}"] = price
            except Exception as e:
                # Finnhub sangat ketat dengan Rate Limit (429), kita tunggu lebih lama
                print(f"[FINNHUB WS ERROR] {e}")
                # Exponential backoff: mulai 30 detik, max 5 menit
                if not hasattr(self, '_finnhub_retry_count'):
                    self._finnhub_retry_count = 0
                self._finnhub_retry_count += 1
                wait = min(300, 30 * (2 ** min(self._finnhub_retry_count - 1, 3)))
                print(f"[FINNHUB WS] Reconnect dalam {wait}s (attempt #{self._finnhub_retry_count})...")
                await asyncio.sleep(wait)
            else:
                # Koneksi sukses, reset retry counter
                self._finnhub_retry_count = 0

async def main():
    private_ws = BitgetPrivateWS()
    public_ws = BitgetPublicWS()
    finnhub_ws = FinnhubWS()
    
    await asyncio.gather(
        private_ws.listen(),
        public_ws.listen(),
        finnhub_ws.listen()
    )

if __name__ == "__main__":
    asyncio.run(main())
