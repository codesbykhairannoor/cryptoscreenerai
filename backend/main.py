from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from data_fetcher import (
    fetch_all_tickers, get_order_book_details, 
    get_technical_indicators, get_forex_data, 
    get_idx_data, get_idx_market_status
)
from ai_model import analyze_and_sort
from database import log_trade, get_performance_stats
from bitget_executor import BitgetExecutor
import threading
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def auto_trade_engine():
    """
    The 'GG' Engine: Direct Execution based on Technical Signals.
    """
    executor = BitgetExecutor()
    print("🚀 Auto-Trading Engine AKTIF! Eksekusi Langsung Berdasarkan Sinyal Teknis...")
    
    while True:
        try:
            raw_data = fetch_all_tickers()
            candidates = analyze_and_sort(raw_data)
            
            for coin in candidates[:5]:
                tech = get_technical_indicators(coin['symbol'])
                signal = tech.get('candle_pattern', "NONE")
                ob = tech.get('order_block', "NONE")
                
                if ob != "NONE" or "ENGULFING" in signal:
                    print(f"🎯 Sinyal Valid di {coin['symbol']} ({ob}/{signal}). Menyiapkan eksekusi...")
                    success, res = executor.place_futures_order(coin['symbol'], 'buy', leverage=5, amount_usdt=10)
                    if success:
                        log_trade(coin['symbol'], "BUY", coin['lastPrice'], 0, 0, "AUTO_TECH")
                        print(f"💰 PROFIT MISSION STARTED: {res}")
        except Exception as e:
            print(f"Auto-trade engine error: {e}")
        time.sleep(300)

@app.on_event("startup")
def startup_event():
    thread = threading.Thread(target=auto_trade_engine, daemon=True)
    thread.start()

@app.get("/")
def read_root():
    return {"message": "CryptoScreener AI Backend is running"}

@app.get("/api/bitget-status")
def get_bitget_status():
    try:
        executor = BitgetExecutor()
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
            coin['bid_wall_price'] = ob['bid_wall_price']
            coin['bid_wall_usdt'] = ob['bid_wall_usdt']
            coin['ask_wall_price'] = ob['ask_wall_price']
            coin['ask_wall_usdt'] = ob['ask_wall_usdt']
            
            rsi = tech.get('rsi', 50)
            atr = tech.get('atr', 0)
            ema_200_cur = tech.get('ema_200', 0)
            ema_200_htf = tech.get('ema_200_htf', 0)
            
            coin['rsi_15m'] = rsi
            coin['atr'] = atr
            coin['ema_200'] = round(ema_200_cur, 4) if isinstance(ema_200_cur, (int, float)) else 0
            coin['ema_200_htf'] = round(ema_200_htf, 4) if isinstance(ema_200_htf, (int, float)) else 0
            coin['candle_pattern'] = tech.get('candle_pattern', "NONE")
            coin['order_block'] = tech.get('order_block', "NONE")
            coin['fvg'] = tech.get('fvg', "NONE")
            coin['htf'] = tech.get('htf', "1h")
            
            last_price = float(coin['lastPrice'])
            is_uptrend_cur = last_price > ema_200_cur if ema_200_cur > 0 else True
            is_uptrend_htf = last_price > ema_200_htf if ema_200_htf > 0 else True
            
            coin['trend'] = f"Bullish ({coin['htf']} Confirmed)" if (is_uptrend_cur and is_uptrend_htf) else \
                           f"Bearish ({coin['htf']} Confirmed)" if (not is_uptrend_cur and not is_uptrend_htf) else \
                           "Neutral/Transition"

            confidence = 35 
            if is_uptrend_cur and is_uptrend_htf: confidence += 20
            if coin['whale_ratio'] > 1.5: confidence += 15
            if rsi < 45: confidence += 15
            confidence = min(confidence, 92)

            coin['entry_price'] = round(last_price, 4)
            coin['sl_price'] = round(last_price - (2.0 * atr), 4) if atr else round(last_price * 0.97, 4)
            coin['tp_price'] = round(last_price + (5.0 * atr), 4) if atr else round(last_price * 1.08, 4)
            coin['trade_signal'] = f"⚖️ Signal ({confidence}%)"

        return {"status": "success", "data": top_coins}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/forex")
def get_forex(timeframe: str = "15m"):
    try:
        asset_data = get_forex_data("XAUUSD", interval=timeframe)
        if not asset_data: return {"status": "error", "message": "Failed to fetch data."}
        
        # Add Trend and Signal
        last_price = float(asset_data.get('lastPrice', 0))
        ema_200 = float(asset_data.get('ema_200', 0))
        asset_data['trend'] = "Bullish" if last_price > ema_200 else "Bearish"
        asset_data['trade_signal'] = "Neutral"
        if asset_data.get('rsi', 50) < 30: asset_data['trade_signal'] = "🔥 BUY"
        elif asset_data.get('rsi', 50) > 70: asset_data['trade_signal'] = "🩸 SELL"
        
        return {"status": "success", "data": [asset_data]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/idx-stocks")
def get_idx(timeframe: str = "15m"):
    try:
        stocks = get_idx_data(interval=timeframe)
        status = get_idx_market_status()
        
        # Add Trend and Signal for frontend compatibility
        for s in stocks:
            lp = float(s.get('lastPrice', 0))
            ema = float(s.get('ema_200', 0))
            s['trend'] = "Bullish" if lp > ema else "Bearish"
            s['trade_signal'] = "Neutral"
            if s.get('demand_score', 0) > 70: s['trade_signal'] = "🔥 WHALE"
            
        return {"status": "success", "market_status": status, "data": stocks}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/performance")
def get_performance():
    try:
        return {"status": "success", "data": get_performance_stats()}
    except Exception as e:
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