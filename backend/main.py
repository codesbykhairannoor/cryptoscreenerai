from contextlib import asynccontextmanager
from fastapi import FastAPI
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
import threading
import time
import subprocess
import os as _os
import sys
import traceback
import io

# Force UTF-8 for Windows console to prevent 'charmap' crash
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ============================================================================-
#  GLOBAL EXCEPTION HANDLER - catch semua unhandled exception di semua thread
#  Ini yang bikin exit code 4294967295 terdeteksi dan di-log
# ============================================================================-
def _global_thread_exception_handler(args):
    """Dipanggil saat ada unhandled exception di thread manapun."""
    print(f"\n[THREAD CRASH] Thread '{args.thread.name}' crashed!", flush=True)
    print(f"  Exception: {args.exc_type.__name__}: {args.exc_value}", flush=True)
    traceback.print_tb(args.exc_traceback)
    print(flush=True)

threading.excepthook = _global_thread_exception_handler

# ============================================================================-
#  PORT CLEANUP - dipanggil saat lifespan startup
#  Membunuh proses lama yang masih pakai port 8000 sebelum bind
# ============================================================================-
def _kill_stale_port(port: int = 8000):
    """Kill proses lain yang masih pakai port ini. Windows-safe."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5
        )
        my_pid = str(_os.getpid())
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1]
                if pid.isdigit() and pid != "0" and pid != my_pid:
                    subprocess.run(
                        ["taskkill", "/PID", pid, "/F"],
                        capture_output=True, timeout=5
                    )
                    print(f"[STARTUP] Killed stale PID {pid} on port {port}", flush=True)
                    time.sleep(1)
    except Exception as e:
        print(f"[STARTUP] Port cleanup: {e}", flush=True)

# ============================================================================-
#  SINGLETON EXECUTORS
# ============================================================================-
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

# ============================================================================-
#  LIFESPAN - menggantikan @app.on_event("startup") yang deprecated
#  Keuntungan: tidak ada DeprecationWarning, graceful shutdown lebih bersih
# ============================================================================-
@asynccontextmanager
async def lifespan(app: FastAPI):
    # == STARTUP ==============================================================
    # Kill proses lama yang masih pakai port 8000 SEBELUM engines start
    # Ini fix untuk [Errno 10048] saat PM2 restart
    _kill_stale_port(8000)

    print("[SYSTEM] Starting CryptoScreener AI...", flush=True)

    # 0. Database migration
    try:
        init_db()
        print("[DB] Database migration selesai.", flush=True)
    except Exception as e:
        print(f"[DB] Migration error: {e}", flush=True)

    # 1. Sync State Memory
    try:
        executor = get_bitget_executor()
        executor.sync_state_with_exchange()
    except Exception as e:
        print(f"[SYSTEM] Gagal sinkronisasi state: {e}", flush=True)

    # 2. Crypto Engine (v5.1 Direct Mode)
    def _run_crypto_engine_safe():
        """Wrapper dengan full traceback logging supaya crash terdeteksi."""
        import traceback
        try:
            run_crypto_engine()
        except Exception as e:
            print(f"[CRYPTO ENGINE FATAL CRASH] {e}", flush=True)
            traceback.print_exc()

    crypto_thread = threading.Thread(
        target=_run_crypto_engine_safe, daemon=True, name="CryptoEngine"
    )
    crypto_thread.start()
    print("[SYSTEM] Crypto Engine AKTIF! (v5.1 Direct Mode)", flush=True)

    # 3. WebSocket Sniper (Private + Finnhub + MarketWS)
    try:
        from websocket_sniper import main as ws_main
        import asyncio

        def run_ws():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(ws_main())

        ws_thread = threading.Thread(target=run_ws, daemon=True, name="WSSniper")
        ws_thread.start()
        print("[SYSTEM] WebSocket Sniper AKTIF! (Private + Finnhub + MarketWS)", flush=True)
    except Exception as e:
        print(f"[SYSTEM] Gagal memulai WebSocket: {e}", flush=True)

    # 4. Forex Engine
    try:
        fx = get_forex_executor()
        fx_thread = threading.Thread(
            target=fx.monitor_forex_market, daemon=True, name="ForexEngine"
        )
        fx_thread.start()
        print("[SYSTEM] Forex Engine AKTIF!", flush=True)
    except Exception as e:
        print(f"[SYSTEM] Gagal memulai Forex Engine: {e}", flush=True)

    # 5. News Sniper
    try:
        news_sniper = get_sniper_instance()
        news_sniper.start()
        print("[SYSTEM] News Sniper Engine AKTIF (Sub-millisecond Ready)!", flush=True)
    except Exception as e:
        print(f"[SYSTEM] Gagal memulai News Sniper: {e}", flush=True)

    print("[SYSTEM] All engines started. Bot is LIVE.", flush=True)

    # 6. Early Signal Engine (OI Tracker + DexScreener)
    try:
        from early_signal import start_early_signal_engine
        start_early_signal_engine()
        print("[SYSTEM] Early Signal Engine AKTIF! (OI Tracker + DexScreener)", flush=True)
    except Exception as e:
        print(f"[SYSTEM] Gagal memulai Early Signal Engine: {e}", flush=True)

    yield  # <- aplikasi berjalan di sini

    # == SHUTDOWN ============================================================-
    print("[SYSTEM] Shutting down gracefully...", flush=True)


# ============================================================================-
#  APP
# ============================================================================-
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================-
#  ENDPOINTS
# ============================================================================-

@app.get("/")
def read_root():
    return {"message": "CryptoScreener AI Multi-Market Backend is running", "version": "5.1"}

@app.get("/api/macro-context")
def get_macro_context():
    """FRED macro context: Fed Rate, CPI, DXY, 10Y Treasury, Yield Curve."""
    try:
        return {"status": "success", "data": get_fred_macro_context()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/onchain-context")
def get_onchain_context():
    """Dune Analytics: stablecoin supply, DEX volume, ETH gas, whale transfers."""
    try:
        return {"status": "success", "data": get_dune_macro_metrics()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/early-signals")
def get_early_signals_endpoint():
    """
    Early momentum signals:
    - OI surge coins (OI naik >30% dalam 1 jam)
    - DexScreener early-stage pairs (volume spike di DEX sebelum listing futures)
    - Top RVOL coins (volume spike vs rata-rata)
    """
    try:
        from early_signal import get_early_signals
        return {"status": "success", "data": get_early_signals()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/market-ws-status")
def get_market_ws_status():
    """Status BitgetMarketWS: berapa symbol di-track, data freshness, BTC sample."""
    try:
        from shared_state import state
        now = time.time()
        fresh_count = sum(1 for ts in state.rt_ticker_ts.values() if now - ts < 30)
        btc = "BTCUSDT"
        return {
            "status": "success",
            "data": {
                "connected":       state.market_ws_connected,
                "tracked_symbols": len(state.market_ws_symbols),
                "fresh_symbols":   fresh_count,
                "symbols":         state.market_ws_symbols[:20],
                "btc_sample": {
                    "price":             state.rt_price.get(btc, 0),
                    "obi":               state.rt_obi.get(btc, 0),
                    "whale":             state.rt_whale.get(btc, "N/A"),
                    "funding":           state.rt_funding.get(btc, 0),
                    "oi":                state.rt_oi.get(btc, 0),
                    "spread_pct":        state.rt_spread.get(btc, 0),
                    "change_24h":        state.rt_change.get(btc, 0),
                    "whale_buy_vol_5m":  state.rt_whale_buy_vol.get(btc, 0),
                    "whale_sell_vol_5m": state.rt_whale_sell_vol.get(btc, 0),
                },
            }
        }
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
        raw_data  = fetch_all_tickers()
        top_coins = analyze_and_sort(raw_data)

        for coin in top_coins:
            ob   = get_order_book_details(coin['symbol'])
            tech = get_technical_indicators(coin['symbol'], interval=timeframe)

            if not tech:
                tech = {
                    "rsi": 50, "atr": 0, "ema_200": 0, "ema_200_htf": 0,
                    "candle_pattern": "NONE", "order_block": "NONE",
                    "fvg": "NONE", "htf": "1h"
                }

            coin['whale_ratio']      = ob['ratio']
            coin['rsi_15m']          = tech.get('rsi', 50)
            coin['atr']              = tech.get('atr', 0)
            coin['candle_pattern']   = tech.get('candle_pattern', "NONE")
            coin['order_block']      = tech.get('order_block', "NONE")
            coin['fvg']              = tech.get('fvg', "NONE")
            coin['inst_flow']        = tech.get('inst_flow', "NORMAL")
            coin['retail_sentiment'] = get_retail_sentiment(coin['symbol']).get('sentiment', 'Neutral')
            coin['news_insight']     = get_crypto_news(coin['symbol'])
            coin['htf']              = tech.get('htf', "1h")
            # 5m precision entry fields
            coin['entry_signal_5m']  = tech.get('entry_signal_5m', 'NEUTRAL')
            coin['entry_quality_5m'] = tech.get('entry_quality_5m', 0)
            coin['zone_freshness_5m']= tech.get('zone_freshness_5m', 'UNKNOWN')
            coin['in_5m_demand']     = tech.get('in_5m_demand', False)
            coin['in_5m_supply']     = tech.get('in_5m_supply', False)

            lp  = float(coin['lastPrice'])
            ema = tech.get('ema_200', 0)
            coin['trend'] = "Bullish" if lp > ema else "Bearish"

            atr = coin['atr']
            entry_price = lp - (0.1 * atr) if atr else lp
            coin['entry_price'] = round(entry_price, 4)
            coin['sl_price']    = round(entry_price - (2.0 * atr), 4) if atr else round(entry_price * 0.97, 4)
            coin['tp_price']    = round(entry_price + (4.0 * atr), 4) if atr else round(entry_price * 1.08, 4)
            coin['trade_signal'] = "ENTRY NOW" if lp <= entry_price * 1.001 else "LIMIT ORDER"

        return {"status": "success", "data": top_coins}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/forex")
def get_forex(timeframe: str = "15m"):
    try:
        asset_data = get_forex_data("XAUUSD", interval=timeframe)
        if not asset_data:
            return {"status": "error", "message": "Failed to fetch data."}

        lp  = float(asset_data.get('lastPrice', 0))
        ema = float(asset_data.get('ema_200', 0))
        atr = float(asset_data.get('atr', 0))
        asset_data['trend'] = "Bullish" if lp > ema else "Bearish"

        entry_price = lp - (0.1 * atr) if atr else lp
        asset_data['entry_price'] = round(entry_price, 2)
        asset_data['sl_price']    = round(entry_price - (1.5 * atr), 2) if atr else round(entry_price - 2, 2)
        asset_data['tp_price']    = round(entry_price + (3.0 * atr), 2) if atr else round(entry_price + 5, 2)
        asset_data['trade_signal'] = "ENTRY NOW" if lp <= entry_price * 1.001 else "LIMIT ORDER"

        return {"status": "success", "data": [asset_data]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/idx-stocks")
def get_idx(timeframe: str = "15m"):
    try:
        stocks = get_idx_data(interval=timeframe)
        status = get_idx_market_status()

        for s in stocks:
            lp  = float(s.get('lastPrice', 0))
            ema = float(s.get('ema_200', 0))
            atr = float(s.get('atr', 0))
            s['trend'] = "Bullish" if lp > ema else "Bearish"

            entry_price = lp - (0.1 * atr) if atr else lp
            s['entry_price'] = round(entry_price, 0)
            s['sl_price']    = round(entry_price - (2.0 * atr), 0) if atr else round(entry_price * 0.96, 0)
            s['tp_price']    = round(entry_price + (4.0 * atr), 0) if atr else round(entry_price * 1.08, 0)
            s['trade_signal'] = "ENTRY NOW" if lp <= entry_price * 1.001 else "LIMIT ORDER"

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
    """Manual market order execution."""
    try:
        symbol = trade.get('symbol')
        market = trade.get('market', 'crypto')
        side   = trade.get('side', 'buy')
        tp     = float(trade.get('tp', 0))
        sl     = float(trade.get('sl', 0))

        if market == 'crypto':
            executor = get_bitget_executor()
            success, res = executor.place_futures_order(symbol, side, tp_price=tp, sl_price=sl)
        else:
            executor = get_forex_executor()
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
        symbol  = trade.get('symbol')
        entry   = trade.get('entry_price') or trade.get('entry') or 0
        tp      = trade.get('tp_price') or trade.get('tp') or 0
        sl      = trade.get('sl_price') or trade.get('sl') or 0
        market  = trade.get('market', 'crypto')
        entry_f = float(entry) if entry is not None else 0.0
        tp_f    = float(tp)    if tp    is not None else 0.0
        sl_f    = float(sl)    if sl    is not None else 0.0
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
        conn   = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT 30")
        history = cursor.fetchall()
        cursor.close()
        conn.close()
        return {"status": "success", "data": history}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================================-
#  ENTRY POINT - dipakai saat run via: python main.py
#  Saat run via PM2 dengan uvicorn langsung, bagian ini tidak dieksekusi
#  tapi _kill_stale_port sudah dipanggil di lifespan startup
# ============================================================================-
if __name__ == "__main__":
    import uvicorn
    _kill_stale_port(8000)
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        timeout_graceful_shutdown=5,
    )



