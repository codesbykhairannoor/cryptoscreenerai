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
    NOTE: Hanya 6 simbol hardcoded. Digantikan oleh BitgetMarketWS untuk coverage penuh.
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
                if not hasattr(self, '_finnhub_retry_count'):
                    self._finnhub_retry_count = 0
                self._finnhub_retry_count += 1

                # Cap di attempt 10 — setelah itu pause 30 menit, tidak spam log
                if self._finnhub_retry_count > 10:
                    wait = 1800  # 30 menit
                    print(f"[FINNHUB WS] Terlalu banyak retry ({self._finnhub_retry_count}x). "
                          f"Pause 30 menit, lanjut tanpa Finnhub.", flush=True)
                    await asyncio.sleep(wait)
                    self._finnhub_retry_count = 0  # Reset setelah pause panjang
                else:
                    # Exponential backoff: 30s, 60s, 120s, 240s, max 300s
                    wait = min(300, 30 * (2 ** min(self._finnhub_retry_count - 1, 3)))
                    print(f"[FINNHUB WS] Reconnect dalam {wait}s (attempt #{self._finnhub_retry_count}/10)...")
                    await asyncio.sleep(wait)
            else:
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


# ─────────────────────────────────────────────────────────────────────────────
#  BITGET MARKET WS — Full Real-Time Market Data Engine
#  Setara CoinAPI: ticker, order book L2, trade stream, OI, funding
#  Coverage: semua top coins dari fetch_all_tickers (dinamis, bukan hardcoded)
#  Data disimpan ke shared_state untuk dipakai data_fetcher tanpa REST call
# ─────────────────────────────────────────────────────────────────────────────

WHALE_THRESHOLD_USD   = 50_000   # Trade > $50k = whale
WHALE_WINDOW_SECONDS  = 300      # Rolling 5 menit untuk akumulasi whale volume
MAX_SYMBOLS_PER_CONN  = 30       # Bitget WS limit per connection
TICKER_CHANNELS       = ["ticker", "books5", "trade"]
FUNDING_REFRESH_SEC   = 60       # Refresh funding rate setiap 1 menit via REST


class BitgetMarketWS:
    """
    FULL MARKET DATA ENGINE — Setara CoinAPI Market Data API

    Channels yang di-subscribe per symbol:
    1. ticker   → lastPrice, 24h change%, volume, OI, funding rate, high/low
    2. books5   → L2 order book 5 level → OBI (bid/ask imbalance)
    3. trade    → individual trades → whale detection (>$50k)

    Data yang dihasilkan (semua masuk shared_state):
    - rt_price[sym]         : last traded price
    - rt_change[sym]        : 24h price change %
    - rt_volume[sym]        : 24h volume USD
    - rt_high[sym]          : 24h high
    - rt_low[sym]           : 24h low
    - rt_oi[sym]            : open interest
    - rt_funding[sym]       : funding rate
    - rt_bid[sym]           : best bid
    - rt_ask[sym]           : best ask
    - rt_spread[sym]        : spread % (ask-bid)/mid
    - rt_obi[sym]           : order book imbalance (-1 to +1)
    - rt_whale[sym]         : WHALE_BUY / WHALE_SELL / NORMAL
    - rt_whale_buy_vol[sym] : rolling 5min whale buy volume USD
    - rt_whale_sell_vol[sym]: rolling 5min whale sell volume USD
    - rt_whale_trades[sym]  : list of recent whale trades
    - rt_ticker_ts[sym]     : last ticker update timestamp
    - rt_depth_ts[sym]      : last depth update timestamp
    - market_ws_connected   : bool
    - market_ws_symbols     : list of tracked symbols
    """

    def __init__(self):
        self.url = "wss://ws.bitget.com/v2/ws/public"
        self.is_running = True
        self._symbols: list[str] = []
        self._connections: list = []   # list of asyncio tasks per connection
        self._last_funding_refresh = 0.0

    # ── Symbol Management ────────────────────────────────────────────────────

    def update_symbols(self, symbols: list[str]):
        """
        Update daftar simbol yang di-track.
        Dipanggil dari crypto_engine setelah fetch_all_tickers().
        Simbol baru akan di-subscribe di koneksi berikutnya (reconnect cycle).
        """
        clean = [s.upper().replace("_UMCBL", "").replace("USDT_UMCBL", "USDT") for s in symbols]
        # Selalu include BTC dan ETH sebagai anchor
        for anchor in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            if anchor not in clean:
                clean.insert(0, anchor)
        self._symbols = list(dict.fromkeys(clean))  # deduplicate, preserve order

        from shared_state import state
        state.market_ws_symbols = self._symbols
        print(f"[MARKET WS] Symbol list updated: {len(self._symbols)} symbols", flush=True)

    def _chunk_symbols(self) -> list[list[str]]:
        """Split symbols ke chunks sesuai MAX_SYMBOLS_PER_CONN."""
        syms = self._symbols or ["BTCUSDT", "ETHUSDT"]
        return [syms[i:i + MAX_SYMBOLS_PER_CONN] for i in range(0, len(syms), MAX_SYMBOLS_PER_CONN)]

    # ── Heartbeat ────────────────────────────────────────────────────────────

    async def _heartbeat(self, ws):
        while self.is_running:
            try:
                await ws.send("ping")
                await asyncio.sleep(20)
            except Exception:
                break

    # ── Subscribe ────────────────────────────────────────────────────────────

    async def _subscribe(self, ws, symbols: list[str]):
        args = []
        for sym in symbols:
            inst_id = sym.replace("USDT", "")  # Bitget instId format: BTC, ETH, etc.
            # Bitget v2 WS instId for futures = symbol without USDT suffix
            # e.g. BTCUSDT → instId = "BTCUSDT" for mix futures
            for ch in TICKER_CHANNELS:
                args.append({
                    "instType": "USDT-FUTURES",
                    "channel": ch,
                    "instId": sym  # BTCUSDT format
                })
        msg = {"op": "subscribe", "args": args}
        await ws.send(json.dumps(msg))
        print(f"[MARKET WS] Subscribed {len(symbols)} symbols × {len(TICKER_CHANNELS)} channels "
              f"= {len(args)} streams", flush=True)

    # ── Message Handlers ─────────────────────────────────────────────────────

    def _handle_ticker(self, symbol: str, data_list: list):
        from shared_state import state
        for t in data_list:
            try:
                price = float(t.get("lastPr", 0) or 0)
                if price <= 0:
                    continue

                state.rt_price[symbol]   = price
                state.rt_ticker_ts[symbol] = time.time()

                # 24h stats
                change_pct = float(t.get("change24h", 0) or 0) * 100
                state.rt_change[symbol]  = round(change_pct, 4)

                vol = float(t.get("baseVolume", 0) or 0)
                state.rt_volume[symbol]  = vol

                high = float(t.get("high24h", 0) or 0)
                low  = float(t.get("low24h", 0) or 0)
                if high > 0: state.rt_high[symbol] = high
                if low  > 0: state.rt_low[symbol]  = low

                # Open Interest
                oi = float(t.get("openInterest", 0) or 0)
                if oi > 0:
                    state.rt_oi[symbol] = oi

                # Funding Rate
                fr = t.get("fundingRate")
                if fr is not None:
                    state.rt_funding[symbol] = float(fr)

                # Best bid/ask dari ticker
                bid = float(t.get("bidPr", 0) or 0)
                ask = float(t.get("askPr", 0) or 0)
                if bid > 0 and ask > 0:
                    state.rt_bid[symbol]    = bid
                    state.rt_ask[symbol]    = ask
                    mid = (bid + ask) / 2
                    state.rt_spread[symbol] = round((ask - bid) / mid * 100, 4) if mid > 0 else 0

            except Exception as e:
                pass  # Jangan crash karena satu ticker error

    def _handle_books5(self, symbol: str, data_list: list):
        """L2 Order Book → OBI + best bid/ask."""
        from shared_state import state
        for d in data_list:
            try:
                bids_raw = d.get("bids", [])
                asks_raw = d.get("asks", [])

                # Bitget books5: [[price, size], ...]
                bid_vol = sum(float(b[1]) for b in bids_raw if len(b) >= 2)
                ask_vol = sum(float(a[1]) for a in asks_raw if len(a) >= 2)
                total   = bid_vol + ask_vol

                if total > 0:
                    obi = round((bid_vol - ask_vol) / total, 4)
                    state.rt_obi[symbol] = obi
                    state.rt_depth_ts[symbol] = time.time()

                # Best bid/ask dari order book (lebih akurat dari ticker)
                if bids_raw:
                    state.rt_bid[symbol] = float(bids_raw[0][0])
                if asks_raw:
                    state.rt_ask[symbol] = float(asks_raw[0][0])

                bid = state.rt_bid.get(symbol, 0)
                ask = state.rt_ask.get(symbol, 0)
                if bid > 0 and ask > 0:
                    mid = (bid + ask) / 2
                    state.rt_spread[symbol] = round((ask - bid) / mid * 100, 4)

            except Exception:
                pass

    def _handle_trade(self, symbol: str, data_list: list):
        """
        Trade stream → Whale detection.
        Akumulasi whale buy/sell volume dalam rolling 5 menit.
        Kalau whale buy > whale sell dan total > $100k → WHALE_BUY
        """
        from shared_state import state
        now = time.time()
        cutoff = now - WHALE_WINDOW_SECONDS

        # Init kalau belum ada
        if symbol not in state.rt_whale_trades:
            state.rt_whale_trades[symbol] = []

        for t in data_list:
            try:
                price    = float(t.get("px", 0) or 0)
                size     = float(t.get("sz", 0) or 0)
                side_raw = t.get("side", "")
                ts_ms    = int(t.get("ts", now * 1000))
                ts       = ts_ms / 1000

                size_usd = price * size
                if size_usd <= 0:
                    continue

                # Catat semua trade (untuk volume profile)
                trade_entry = {
                    "ts": ts,
                    "side": side_raw,
                    "size_usd": size_usd,
                    "price": price,
                    "is_whale": size_usd >= WHALE_THRESHOLD_USD
                }
                state.rt_whale_trades[symbol].append(trade_entry)

                if size_usd >= WHALE_THRESHOLD_USD:
                    side_label = "BUY" if side_raw == "buy" else "SELL"
                    print(f"  [WHALE ALERT] {symbol} | {side_label} | "
                          f"${round(size_usd/1000, 1)}K @ {price}", flush=True)

            except Exception:
                pass

        # Prune trades older than window
        state.rt_whale_trades[symbol] = [
            t for t in state.rt_whale_trades[symbol] if t["ts"] > cutoff
        ]

        # Recalculate rolling whale volumes
        recent = state.rt_whale_trades[symbol]
        buy_vol  = sum(t["size_usd"] for t in recent if t["side"] == "buy"  and t["is_whale"])
        sell_vol = sum(t["size_usd"] for t in recent if t["side"] == "sell" and t["is_whale"])

        state.rt_whale_buy_vol[symbol]  = round(buy_vol, 0)
        state.rt_whale_sell_vol[symbol] = round(sell_vol, 0)

        # Determine whale signal
        total_whale = buy_vol + sell_vol
        if total_whale >= 100_000:
            if buy_vol > sell_vol * 1.5:
                state.rt_whale[symbol] = "WHALE_BUY"
            elif sell_vol > buy_vol * 1.5:
                state.rt_whale[symbol] = "WHALE_SELL"
            else:
                state.rt_whale[symbol] = "NORMAL"
        elif total_whale < 10_000:
            # Tidak ada aktivitas whale → reset ke NORMAL setelah 5 menit
            state.rt_whale[symbol] = "NORMAL"

    # ── Funding Rate REST Refresh ─────────────────────────────────────────────

    async def _refresh_funding_rates(self):
        """
        Funding rate tidak selalu ada di ticker WS.
        Fetch via REST setiap 1 menit untuk semua tracked symbols.
        Ini jauh lebih efisien dari fetch per-symbol di data_fetcher.
        """
        from shared_state import state
        syms = self._symbols[:50]  # Batch max 50
        if not syms:
            return
        try:
            url = "https://api.bitget.com/api/v2/mix/market/current-fund-rate?productType=USDT-FUTURES"
            r = requests.get(url, timeout=8, verify=False)
            if r.status_code == 200:
                data = r.json().get("data", [])
                for item in data:
                    sym = item.get("symbol", "")
                    fr  = item.get("fundingRate")
                    if sym and fr is not None:
                        state.rt_funding[sym] = float(fr)
                print(f"[MARKET WS] Funding rates refreshed: {len(data)} symbols", flush=True)
        except Exception as e:
            print(f"[MARKET WS] Funding refresh error: {e}", flush=True)

    # ── Single Connection Loop ────────────────────────────────────────────────

    async def _run_connection(self, symbols: list[str], conn_id: int):
        """Run satu WebSocket connection untuk subset symbols."""
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        retry_count = 0
        while self.is_running:
            try:
                async with websockets.connect(
                    self.url,
                    ssl=ssl_ctx,
                    ping_interval=None,   # Kita handle sendiri
                    max_size=10 * 1024 * 1024  # 10MB max message
                ) as ws:
                    retry_count = 0
                    asyncio.create_task(self._heartbeat(ws))
                    await self._subscribe(ws, symbols)

                    from shared_state import state
                    state.market_ws_connected = True

                    print(f"[MARKET WS #{conn_id}] Connected & streaming "
                          f"{len(symbols)} symbols", flush=True)

                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=45)
                        except asyncio.TimeoutError:
                            await ws.send("ping")
                            continue

                        if raw == "pong":
                            continue

                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue

                        # Skip subscription confirmations
                        if msg.get("event") in ("subscribe", "error"):
                            if msg.get("event") == "error":
                                print(f"[MARKET WS #{conn_id}] Sub error: {msg}", flush=True)
                            continue

                        arg     = msg.get("arg", {})
                        channel = arg.get("channel", "")
                        symbol  = arg.get("instId", "")
                        payload = msg.get("data", [])

                        if not symbol or not payload:
                            continue

                        if channel == "ticker":
                            self._handle_ticker(symbol, payload)
                        elif channel == "books5":
                            self._handle_books5(symbol, payload)
                        elif channel == "trade":
                            self._handle_trade(symbol, payload)

            except Exception as e:
                from shared_state import state
                state.market_ws_connected = False
                retry_count += 1
                wait = min(60, 5 * retry_count)
                print(f"[MARKET WS #{conn_id}] Error: {e} | Reconnect in {wait}s", flush=True)
                await asyncio.sleep(wait)

    # ── Main Entry Point ──────────────────────────────────────────────────────

    async def listen(self):
        """
        Start semua connections + funding rate refresh loop.
        Dipanggil dari main() dengan asyncio.gather().
        """
        # Seed symbols dari Bitget REST sebelum WS start
        try:
            r = requests.get(
                "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES",
                timeout=10, verify=False
            )
            if r.status_code == 200:
                tickers = r.json().get("data", [])
                # Sort by 24h volume, ambil top 60
                tickers.sort(key=lambda x: float(x.get("baseVolume", 0) or 0), reverse=True)
                syms = [t["symbol"] for t in tickers if t.get("symbol")]  # Semua koin
                self.update_symbols(syms)
        except Exception as e:
            print(f"[MARKET WS] Seed symbols error: {e}", flush=True)
            self.update_symbols(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT"])

        chunks = self._chunk_symbols()
        print(f"[MARKET WS] Starting {len(chunks)} connections for "
              f"{len(self._symbols)} symbols", flush=True)

        # Jalankan semua connections + funding refresh loop secara parallel
        tasks = [self._run_connection(chunk, i) for i, chunk in enumerate(chunks)]
        tasks.append(self._funding_refresh_loop())
        await asyncio.gather(*tasks)

    async def _funding_refresh_loop(self):
        """Refresh funding rates via REST setiap FUNDING_REFRESH_SEC detik."""
        while self.is_running:
            await asyncio.sleep(FUNDING_REFRESH_SEC)
            await self._refresh_funding_rates()


# ── Market WS Singleton ───────────────────────────────────────────────────────
_market_ws_instance: BitgetMarketWS | None = None

def get_market_ws() -> BitgetMarketWS:
    global _market_ws_instance
    if _market_ws_instance is None:
        _market_ws_instance = BitgetMarketWS()
    return _market_ws_instance


async def main():
    private_ws  = BitgetPrivateWS()
    public_ws   = BitgetPublicWS()   # Legacy — masih jalan untuk backward compat
    finnhub_ws  = FinnhubWS()
    market_ws   = get_market_ws()    # NEW: Full market data engine

    await asyncio.gather(
        private_ws.listen(),
        finnhub_ws.listen(),
        market_ws.listen(),          # Gantikan public_ws untuk data coverage penuh
    )

if __name__ == "__main__":
    asyncio.run(main())
