import asyncio
import json
import websockets
import os
import time
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
        # Bitget V2 Subscription Format
        subs = {
            "op": "subscribe",
            "args": [
                {"instType": "unify", "channel": "ticker", "instId": "BTCUSDT"},
                {"instType": "unify", "channel": "candle1m", "instId": "BTCUSDT"},
                {"instType": "unify", "channel": "ticker", "instId": "ETHUSDT"}
            ]
        }
        await ws.send(json.dumps(subs))
        print("🛰️ [WS V2] Subscribed to Public Stream!")

    async def listen(self):
        while self.is_running:
            try:
                print(f"📡 [WS] Connecting to {self.url}...")
                async with websockets.connect(self.url) as ws:
                    # Start Heartbeat in background
                    asyncio.create_task(self.heartbeat(ws))
                    
                    await self.subscribe(ws)
                    
                    while True:
                        message = await ws.recv()
                        if message == "pong": continue # Ignore heartbeat response
                        
                        data = json.loads(message)
                        if "data" in data:
                            arg = data.get("arg", {})
                            channel = arg.get("channel")
                            symbol = arg.get("instId")

                            now = time.time()
                            if symbol in self.last_trade_time:
                                if now - self.last_trade_time[symbol] < 30:
                                    continue

                            if channel == "candle1m":
                                print(f"📊 [WS V2] Candle Data Received: {symbol}")
                                is_spike = detect_volatility_spike(symbol)
                                
                                if is_spike:
                                    print(f"🚀 [WS SNIPER] TRIGGERED ON {symbol}!")
                                    self.last_trade_time[symbol] = now
            except Exception as e:
                print(f"🔄 [WS RECONNECT] Error: {e}. Retrying in 5s...")
                await asyncio.sleep(5)

async def main():
    sniper = BitgetWebSocketSniper()
    await sniper.listen()

if __name__ == "__main__":
    asyncio.run(main())
