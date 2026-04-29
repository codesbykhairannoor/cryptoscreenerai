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
        self.url = "wss://ws.bitget.com/mix/v1/stream"
        self.executor = BitgetExecutor()
        self.is_running = True
        self.last_trade_time = {} # For Debouncing

    async def subscribe(self, ws):
        subs = {
            "op": "subscribe",
            "args": [
                {"instType": "mc", "channel": "ticker", "instId": "BTCUSDT"},
                {"instType": "mc", "channel": "candle1m", "instId": "BTCUSDT"},
                {"instType": "mc", "channel": "ticker", "instId": "ETHUSDT"}
            ]
        }
        await ws.send(json.dumps(subs))
        print("🛰️ [WS] Subscribed with Heartbeat & Auto-Reconnect!")

    async def listen(self):
        while self.is_running:
            try:
                # Use ping_interval to prevent Zombie Connections
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=10) as ws:
                    await self.subscribe(ws)
                    
                    while True:
                        message = await ws.recv()
                        data = json.loads(message)
                        
                        if "data" in data:
                            arg = data.get("arg", {})
                            channel = arg.get("channel")
                            symbol = arg.get("instId")

                            # DEBOUNCING: Prevent multiple trades in same 30s window
                            now = time.time()
                            if symbol in self.last_trade_time:
                                if now - self.last_trade_time[symbol] < 30:
                                    continue

                            if channel == "candle1m":
                                print(f"📊 [WS] Candle Update: {symbol}")
                                is_spike = detect_volatility_spike(symbol)
                                
                                if is_spike:
                                    print(f"🚀 [WS SNIPER] VOLATILITY TRIGGERED ON {symbol}!")
                                    self.last_trade_time[symbol] = now
                                    # Trade logic here (already handled in main.py loop but WS can trigger it faster)

            except Exception as e:
                print(f"🔄 [WS RECONNECT] Connection lost, retrying in 5s... Error: {e}")
                await asyncio.sleep(5)

async def main():
    sniper = BitgetWebSocketSniper()
    await sniper.listen()

if __name__ == "__main__":
    asyncio.run(main())
