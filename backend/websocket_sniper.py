import asyncio
import json
import websockets
import os
import time
import requests
from dotenv import load_dotenv
from bitget_executor import BitgetExecutor
from main import detect_volatility_spike
from database import log_trade

load_dotenv()

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
                {"instType": "USDT-FUTURES", "channel": "candle1m", "instId": "BTCUSDT"},
                {"instType": "USDT-FUTURES", "channel": "ticker", "instId": "ETHUSDT"},
                {"instType": "USDT-FUTURES", "channel": "ticker", "instId": "SOLUSDT"}
            ]
        }
        await ws.send(json.dumps(subs))
        print("🛰️ [WS V2] Subscribed to USDT-FUTURES Stream (BTC, ETH, SOL)!")

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
                            arg = data.get("arg", {})
                            channel = arg.get("channel")
                            symbol = arg.get("instId")
                            
                            if channel == "candle1m":
                                now = time.time()
                                if symbol in self.last_trade_time:
                                    if now - self.last_trade_time[symbol] < 30:
                                        continue

                                is_spike, vol_pct = self.detect_vol_with_details(symbol)
                                
                                if is_spike:
                                    print(f"⚡ [ALERT] Volatility Spike Detected! Volume: {vol_pct}%")
                                    print(f"🚀 [WS SNIPER] TRIGGERED ON {symbol}!")
                                    self.last_trade_time[symbol] = now
                                # Muted: else: print(f"📊 [WS V2] New Candle Data: {symbol}! (Normal)")
            except Exception as e:
                print(f"🔄 [WS RECONNECT] Error: {e}. Retrying in 5s...")
                await asyncio.sleep(5)

    def detect_vol_with_details(self, symbol):
        """Helper to get exact volume percentage for the log"""
        try:
            # Simple volume check
            url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=1m&limit=5"
            res = requests.get(url, timeout=2)
            data = res.json()
            if not data or len(data) < 5: return False, 0
            
            last_vol = float(data[-1][5])
            avg_vol = sum(float(d[5]) for d in data[:-1]) / 4
            pct = round((last_vol / avg_vol) * 100, 0)
            return last_vol > avg_vol * 3.0, int(pct)
        except:
            return False, 0

async def main():
    sniper = BitgetWebSocketSniper()
    await sniper.listen()

if __name__ == "__main__":
    asyncio.run(main())
