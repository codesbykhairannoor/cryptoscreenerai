import asyncio
import time
import json
from shared_state import state
from websocket_sniper import BitgetPrivateWS, BitgetMarketWS, BinanceWS, FinnhubWS, get_market_ws

async def monitor_state():
    print("\n--- MONITORING DATA FLOW (20 SECONDS) ---")
    start_time = time.time()
    while time.time() - start_time < 20:
        await asyncio.sleep(5)
        print(f"\n[SNAPSHOT @ {int(time.time() - start_time)}s]")
        print(f"  RT Prices:  {len(state.rt_price)} symbols tracked")
        print(f"  RT OI:      {len(state.rt_oi)} symbols tracked")
        print(f"  RT OBI:     {len(state.rt_obi)} symbols tracked")
        print(f"  RT Funding: {len(state.rt_funding)} symbols tracked")
        
        if "BTCUSDT" in state.rt_price:
            print(f"  BTC Sample: Price={state.rt_price['BTCUSDT']} | OI={state.rt_oi.get('BTCUSDT')} | OBI={state.rt_obi.get('BTCUSDT')}")
        
        if state.rt_news:
            print(f"  Latest News: {state.rt_news[-1][:50]}...")

async def test_all():
    # Setup all WS
    private_ws = BitgetPrivateWS()
    market_ws  = get_market_ws()
    binance_ws = BinanceWS()
    finnhub_ws = FinnhubWS()

    # Run everything in gather
    # We use a wrapper to stop after 25s
    try:
        await asyncio.wait_for(
            asyncio.gather(
                private_ws.listen(),
                market_ws.listen(),
                binance_ws.listen(),
                finnhub_ws.listen(),
                monitor_state()
            ),
            timeout=25
        )
    except asyncio.TimeoutError:
        print("\n--- TEST COMPLETED SUCCESSFULLY ---")
        print("Final State Audit:")
        print(f"Total Symbols in State: {len(state.rt_price)}")
        if len(state.rt_price) > 0:
            print("VERIFIED: Data is flowing from WebSockets to SharedState.")
        else:
            print("FAILED: No data received.")

if __name__ == "__main__":
    asyncio.run(test_all())
