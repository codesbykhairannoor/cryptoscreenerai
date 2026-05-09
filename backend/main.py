from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sentiment import get_crypto_news, get_global_market_data, get_fred_macro_context
from data_fetcher import (
    fetch_all_tickers, get_order_book_details, 
    get_technical_indicators, get_forex_data, 
    get_idx_data, get_idx_market_status,
    get_retail_sentiment, detect_institutional_flow,
    get_dune_macro_metrics
)
from ai_model import analyze_and_sort
from database import log_trade, get_performance_stats, init_db
from bitget_executor import BitgetExecutor
from crypto_engine import run_crypto_engine, detect_volatility_spike
from forex_executor import ForexExecutor
from news_sniper import get_sniper_instance, news_execution_handler
import requests
import random
import threading
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Singleton executor — dibuat sekali, dipakai ulang untuk semua request
# Mencegah pembuatan koneksi baru + API call balance/positions setiap request
_bitget_executor: BitgetExecutor = None
_forex_executor: ForexExecutor = None

def get_bitget_executor() -> BitgetExecutor:
    global _bitget_executor
    if _bitget_executor is None:
        _bitget_executor = BitgetExecutor()
    return _bitget_executor

def get_forex_executor() -> ForexExecutor:
    global _forex_executor
    if _forex_executor is None:
        _forex_executor = ForexExecutor()
    return _forex_executor

@app.on_event("startup")
def startup_event():
    # 0. Database migration
    try:
        init_db()
        print("[DB] Database migration selesai.")
    except Exception as e:
        print(f"[DB] Migration error: {e}")

    # 1. Sync State Memory (Anti-Amnesia Pillar)
    try:
        executor = get_bitget_executor()
        executor.sync_state_with_exchange()
    except Exception as e:
        print(f"[SYSTEM] Gagal sinkronisasi state: {e}", flush=True)

    # 2. Start Crypto Engine (Isolated)
    # VERSI: v5.1 Direct Execution Mode (bukan v9.0 Whale Observer)
    crypto_thread = threading.Thread(target=run_crypto_engine, daemon=True, name="CryptoEngine")
    crypto_thread.start()
    print("[SYSTEM] Crypto Engine AKTIF! (v5.1 Direct Mode)", flush=True)
    
    # 3. Start WebSocket Sniper (Isolated)
    try:
        from websocket_sniper import main as ws_main, get_market_ws
        import asyncio
        def run_ws():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(ws_main())
        ws_thread = threading.Thread(target=run_ws, daemon=True)
        ws_thread.start()
        print("[SYSTEM] WebSocket Sniper AKTIF! (Private + Finnhub + MarketWS)")
    except Exception as e:
        print(f"[SYSTEM] Gagal memulai WebSocket: {e}")

    # 4. Start Forex Engine (Isolated)
    try:
        fx = get_forex_executor()
        fx_thread = threading.Thread(target=fx.monitor_forex_market, daemon=True)
        fx_thread.start()
        print("[SYSTEM] Forex Engine AKTIF!")
    except Exception as e:
        print(f"[SYSTEM] Gagal memulai Forex Engine: {e}")

    # 4. Start News Sniper (Sub-millisecond Execution)
    # Pakai singleton   ForexExecutor sudah pre-initialized
    try:
        news_sniper = get_sniper_instance()
        news_sniper.start()
        print("[SYSTEM] News Sniper Engine AKTIF (Sub-millisecond Ready)!", flush=True)
    except Exception as e:
        print(f"[SYSTEM] Gagal memulai News Sniper: {e}", flush=True)

    # 5. Start Heartbeat Monitor (Visual Feedback)
    def system_heartbeat():
        while True:
            # Heartbeat silent - hanya untuk menjaga thread utama tetap hidup di log kalau perlu
            time.sleep(60)
    
    
    hb_thread = threading.Thread(target=system_heartbeat, daemon=True)
    hb_thread.start()
    print("[SYSTEM] Heartbeat Monitor AKTIF!", flush=True)

@app.get("/")
def read_root():
    return {"message": "CryptoScreener AI Multi-Market Backend is running"}

@app.get("/api/macro-context")
def get_macro_context():
    """
    Endpoint untuk FRED macro context.
    Data: Fed Rate, CPI, DXY, 10Y Treasury, Yield Curve, Macro Bias.
    Cache 1 jam — data FRED update harian.
    """
    try:
        fred = get_fred_macro_context()
        return {"status": "success", "data": fred}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/market-ws-status")
def get_market_ws_status():
    """
    Status real-time BitgetMarketWS — setara CoinAPI connection status.
    Menampilkan berapa symbol yang di-track, data freshness, dan sample data.
    """
    try:
        from shared_state import state
        from websocket_sniper import get_market_ws
        mws = get_market_ws()

        # Hitung berapa symbol yang punya data fresh (< 30 detik)
        now = time.time()
        fresh_count = sum(
            1 for sym, ts in state.rt_ticker_ts.items()
            if now - ts < 30
        )

        # Sample data dari BTC
        btc = "BTCUSDT"
        sample = {
            "price":      state.rt_price.get(btc, 0),
            "obi":        state.rt_obi.get(btc, 0),
            "whale":      state.rt_whale.get(btc, "N/A"),
            "funding":    state.rt_funding.get(btc, 0),
            "oi":         state.rt_oi.get(btc, 0),
            "spread_pct": state.rt_spread.get(btc, 0),
            "change_24h": state.rt_change.get(btc, 0),
            "whale_buy_vol_5m":  state.rt_whale_buy_vol.get(btc, 0),
            "whale_sell_vol_5m": state.rt_whale_sell_vol.get(btc, 0),
        }

        return {
            "status": "success",
            "data": {
                "connected":       state.market_ws_connected,
                "tracked_symbols": len(state.market_ws_symbols),
                "fresh_symbols":   fresh_count,
                "symbols":         state.market_ws_symbols[:20],
                "btc_sample":      sample,
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/onchain-context")
def get_onchain_context():
    """
    Dune Analytics on-chain macro context.
    Data: stablecoin supply, DEX volume, ETH gas, whale transfers.
    Cache 30 menit — tidak trigger fresh execution setiap request.
    """
    try:
        dune = get_dune_macro_metrics()
        return {"status": "success", "data": dune}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/bitget-status")
def get_bitget_status():
    try:
        executor = get_bitget_executor()
        success, message = executor.test_connection()
        return {"connected": success, "message": message}
    except Exception as e:
        return {"connected": False, "message": str(e)}

@app.get("/api/forex-status")
def get_forex_status():
    try:
        executor = get_forex_executor()
        success, message = executor.test_connection()
        return {"connected": success, "message": message}
    except Exception as e:
        return {"connected": False, "message": str(e)}

@app.get("/api/top-coins")
def get_top_coins(timeframe: str = "15m"):
    try:
        raw_data = fetch_all_tickers()
        top_coins = analyze_and_sort(raw_data)
        
        for coin in top_coins:
            ob = get_order_book_details(coin['symbol'])
            tech = get_technical_indicators(coin['symbol'], interval=timeframe) 
            
            if not tech:
                tech = {"rsi": 50, "atr": 0, "ema_200": 0, "ema_200_htf": 0, "candle_pattern": "NONE", "order_block": "NONE", "fvg": "NONE", "htf": "1h"}

            coin['whale_ratio'] = ob['ratio']
            coin['rsi_15m'] = tech.get('rsi', 50)
            coin['atr'] = tech.get('atr', 0)
            coin['candle_pattern'] = tech.get('candle_pattern', "NONE")
            coin['order_block'] = tech.get('order_block', "NONE")
            coin['fvg'] = tech.get('fvg', "NONE")
            coin['inst_flow'] = tech.get('inst_flow', "NORMAL")
            coin['retail_sentiment'] = get_retail_sentiment(coin['symbol']).get('sentiment', 'Neutral')
            coin['news_insight'] = get_crypto_news(coin['symbol'])
            coin['htf'] = tech.get('htf', "1h")
            
            # Trend calculation
            lp = float(coin['lastPrice'])
            ema = tech.get('ema_200', 0)
            coin['trend'] = "Bullish" if lp > ema else "Bearish"
            
            # SMARTER ENTRY LOGIC
            atr = coin['atr']
            entry_price = lp - (0.1 * atr) if atr else lp
            coin['entry_price'] = round(entry_price, 4)
            coin['sl_price'] = round(entry_price - (2.0 * atr), 4) if atr else round(entry_price * 0.97, 4)
            coin['tp_price'] = round(entry_price + (4.0 * atr), 4) if atr else round(entry_price * 1.08, 4)
            
            if lp <= entry_price * 1.001:
                coin['trade_signal'] = f"ENTRY NOW"
            else:
                coin['trade_signal'] = f"LIMIT ORDER"

        return {"status": "success", "data": top_coins}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/forex")
def get_forex(timeframe: str = "15m"):
    try:
        asset_data = get_forex_data("XAUUSD", interval=timeframe)
        if not asset_data: return {"status": "error", "message": "Failed to fetch data."}
        
        lp = float(asset_data.get('lastPrice', 0))
        ema = float(asset_data.get('ema_200', 0))
        atr = float(asset_data.get('atr', 0))
        asset_data['trend'] = "Bullish" if lp > ema else "Bearish"
        
        entry_price = lp - (0.1 * atr) if atr else lp
        asset_data['entry_price'] = round(entry_price, 2)
        asset_data['sl_price'] = round(entry_price - (1.5 * atr), 2) if atr else round(entry_price - 2, 2)
        asset_data['tp_price'] = round(entry_price + (3.0 * atr), 2) if atr else round(entry_price + 5, 2)
        
        if lp <= entry_price * 1.001: asset_data['trade_signal'] = "ENTRY NOW"
        else: asset_data['trade_signal'] = "LIMIT ORDER"
        
        return {"status": "success", "data": [asset_data]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/idx-stocks")
def get_idx(timeframe: str = "15m"):
    try:
        stocks = get_idx_data(interval=timeframe)
        status = get_idx_market_status()
        
        for s in stocks:
            lp = float(s.get('lastPrice', 0))
            ema = float(s.get('ema_200', 0))
            atr = float(s.get('atr', 0))
            s['trend'] = "Bullish" if lp > ema else "Bearish"
            
            entry_price = lp - (0.1 * atr) if atr else lp
            s['entry_price'] = round(entry_price, 0)
            s['sl_price'] = round(entry_price - (2.0 * atr), 0) if atr else round(entry_price * 0.96, 0)
            s['tp_price'] = round(entry_price + (4.0 * atr), 0) if atr else round(entry_price * 1.08, 0)
            
            if lp <= entry_price * 1.001: s['trade_signal'] = "ENTRY NOW"
            else: s['trade_signal'] = "LIMIT ORDER"
            
        return {"status": "success", "market_status": status, "data": stocks}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/performance")
def get_performance(market: str = None):
    try:
        return {"status": "success", "data": get_performance_stats(market)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/execute-now")
def execute_now(trade: dict):
    """
    MANUAL SNIPER: Instantly executes a market order.
    Use this to test connectivity or manual entry.
    """
    try:
        symbol = trade.get('symbol')
        market = trade.get('market', 'crypto')
        side = trade.get('side', 'buy')
        
        if market == 'crypto':
            executor = get_bitget_executor()
            # Small randomized TP/SL for manual stealth test
            tp = float(trade.get('tp', 0))
            sl = float(trade.get('sl', 0))
            success, res = executor.place_futures_order(symbol, side, tp_price=tp, sl_price=sl)
        else:
            executor = get_forex_executor()
            # Manual batch for Forex (3 trades for 'pinter' scaling test)
            tp = float(trade.get('tp', 0))
            sl = float(trade.get('sl', 0))
            success = executor.place_xauusd_scalp_batch(side, trades_count=1, volume=0.01, tp=tp, sl=sl)
            res = "Forex Order Sent to MT5 with SL/TP"
            
        if success:
            return {"status": "success", "message": f"Manual {side.upper()} executed for {symbol}!"}
        return {"status": "error", "message": f"Failed: {res}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/select-trade")
def select_trade(trade: dict):
    try:
        # Robust property extraction with fallbacks
        symbol = trade.get('symbol')
        entry = trade.get('entry_price') or trade.get('entry') or 0
        tp = trade.get('tp_price') or trade.get('tp') or 0
        sl = trade.get('sl_price') or trade.get('sl') or 0
        market = trade.get('market', 'crypto')

        # Convert to float safely
        entry_f = float(entry) if entry is not None else 0.0
        tp_f = float(tp) if tp is not None else 0.0
        sl_f = float(sl) if sl is not None else 0.0

        success = log_trade(symbol, entry_f, tp_f, sl_f, market=market)
        return {"status": "success" if success else "error"}
    except Exception as e:
        print(f"Select trade error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/trade-history")
def get_history():
    try:
        from database import get_connection
        from psycopg2.extras import RealDictCursor
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT 30")
        history = cursor.fetchall()
        cursor.close()
        conn.close()
        return {"status": "success", "data": history}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)