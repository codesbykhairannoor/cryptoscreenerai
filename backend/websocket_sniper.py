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
                            
                            # Real-time Price Log (Optional)
                            if channel == "ticker":
                                # print(f"⚡ Tick: {symbol} @ {data['data'][0]['last']}")
                                pass

                            if channel == "candle1m":
                                print(f"📊 [WS V2] New Candle Data: {symbol}!")
                                now = time.time()
                                if symbol in self.last_trade_time:
                                    if now - self.last_trade_time[symbol] < 30:
                                        continue

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
