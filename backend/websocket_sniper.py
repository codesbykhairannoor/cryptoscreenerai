import asyncio
import json
import websockets
import os
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

    async def subscribe(self, ws):
        # Subscribe to Tickers and 1m Candles for Top Coins
        # For simplicity, we monitor BTC and ETH as market leaders
        subs = {
            "op": "subscribe",
            "args": [
                {"instType": "mc", "channel": "ticker", "instId": "BTCUSDT"},
                {"instType": "mc", "channel": "candle1m", "instId": "BTCUSDT"}
            ]
        }
        await ws.send(json.dumps(subs))
        print("🛰️ [WS] Subscribed to Real-time Stream!")

    async def listen(self):
        async with websockets.connect(self.url) as ws:
            await self.subscribe(ws)
            
            while self.is_running:
                try:
                    message = await ws.recv()
                    data = json.loads(message)
                    
                    if "data" in data:
                        # Process Real-time Data
                        channel = data["action"] if "action" in data else data.get("arg", {}).get("channel")
                        
                        if channel == "ticker":
                            # Ultra-fast logic here
                            # print(f"⚡ Price Update: {data['data'][0]['last']}")
                            pass
                            
                        if channel == "candle1m":
                            symbol = data["arg"]["instId"]
                            print(f"📊 [WS] Candle Close on {symbol} - Checking for Spikes...")
                            
                            # Immediate Trigger!
                            is_spike = detect_volatility_spike(symbol)
                            if is_spike:
                                print(f"🚀 [WS SNIPER] VOLATILITY DETECTED ON {symbol}!")
                                # Execute immediate trade
                                # success, res = self.executor.place_futures_order(...)
                                
                except Exception as e:
                    print(f"❌ [WS ERROR] {e}")
                    await asyncio.sleep(5)
                    break

async def main():
    sniper = BitgetWebSocketSniper()
    await sniper.listen()

if __name__ == "__main__":
    asyncio.run(main())
