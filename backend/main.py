from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sentiment import get_crypto_news, get_global_market_data
from data_fetcher import (
    fetch_all_tickers, get_order_book_details, 
    get_technical_indicators, get_forex_data, 
    get_idx_data, get_idx_market_status,
    get_retail_sentiment, detect_institutional_flow
)
from ai_model import analyze_and_sort
from database import log_trade, get_performance_stats
from bitget_executor import BitgetExecutor
import requests
import threading
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def detect_volatility_spike(symbol, timeframe="1m"):
    """
    Sniper Tool: Detects if institutional bots are pumping/dumping during news.
    Look for 300% volume surge in the last minute.
    """
    try:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={timeframe}&limit=5"
        res = requests.get(url, timeout=2)
        data = res.json()
        if not data or len(data) < 5: return False
        
        # Last minute volume vs Average of previous 4 minutes
        last_vol = float(data[-1][5])
        avg_vol = sum(float(d[5]) for d in data[:-1]) / 4
        
        if last_vol > avg_vol * 3.0: # 300% Spike
            return True
        return False
    except:
        return False

def auto_trade_engine():
    """
    The 'GG' Engine: Advanced Autonomous Execution.
    Supports 'News Sniper' mode for high-volatility events (FOMC, etc.)
    """
    executor = BitgetExecutor()
    from database import check_pending_trades
    print("🚀 [SYSTEM] Auto-Trading Engine AKTIF!")
    
    while True:
        try:
            executor.manage_open_positions()
            check_pending_trades()
            
            # 1. Global Context & News Check
            global_context = get_global_market_data()
            print(f"🌍 [GLOBAL] {global_context}")
            
            # 2. Scanning for Normal & Sniper Opportunities
            raw_data = fetch_all_tickers()
            candidates = analyze_and_sort(raw_data)
            
            for coin in candidates[:5]:
                symbol = coin['symbol']
                
                # SNIPER MODE: Rapid Volatility Check
                is_news_spike = detect_volatility_spike(symbol)
                
                tech = get_technical_indicators(symbol)
                ob = tech.get('order_block', "NONE")
                inst_flow = tech.get('inst_flow', "NORMAL")
                retail = get_retail_sentiment(symbol)
                
                should_trade = False
                reason = ""
                
                # Strategy A: News Sniper (Momentum)
                if is_news_spike and inst_flow != "NORMAL":
                    should_trade = True
                    reason = "NEWS SNIPER: Volatility Spike + Inst Flow"
                
                # Strategy B: Smart Money (Swing)
                elif (ob != "NONE") and inst_flow != "NORMAL" and retail['ratio'] < 1.5:
                    should_trade = True
                    reason = "SWING: OB + Institutional Confluence"
                
                if should_trade:
                    entry = coin['lastPrice']
                    tp = coin['tp_price']
                    sl = coin['sl_price'] * 0.985 # Tighter SL for Sniper
                    
                    print(f"🎯 [EXECUTE] {reason} ditemukan di {symbol}!")
                    success, res = executor.place_futures_order(
                        symbol, 'buy', leverage=5, 
                        tp_price=tp, sl_price=sl
                    )
                    if success:
                        log_trade(symbol, entry, tp, sl, market='crypto')
                        print(f"💰 [SUCCESS] {symbol} Order Placed! Flow: {inst_flow}")
                    else:
                        print(f"⚠️ [FAILED] {symbol}: {res}")
                
        except Exception as e:
            print(f"❌ [CRITICAL] Engine Error: {e}")
        
        # News/Fast Mode Logic: If market is volatile, poll faster (30s), else 5m
        time.sleep(30) # Default faster polling for testing

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
                coin['trade_signal'] = f"🚀 ENTRY NOW"
            else:
                coin['trade_signal'] = f"⏳ LIMIT ORDER"

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
        
        if lp <= entry_price * 1.001: asset_data['trade_signal'] = "🚀 ENTRY NOW"
        else: asset_data['trade_signal'] = "⏳ LIMIT ORDER"
        
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
            
            if lp <= entry_price * 1.001: s['trade_signal'] = "🚀 ENTRY NOW"
            else: s['trade_signal'] = "⏳ LIMIT ORDER"
            
        return {"status": "success", "market_status": status, "data": stocks}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/performance")
def get_performance(market: str = None):
    try:
        return {"status": "success", "data": get_performance_stats(market)}
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