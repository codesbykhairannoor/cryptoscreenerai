from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from data_fetcher import fetch_all_tickers, get_order_book_details, get_technical_indicators, get_forex_data
from ai_model import analyze_and_sort
from database import init_db, log_trade, check_pending_trades, get_performance_stats
import threading
import time

app = FastAPI(title="Crypto AI Screener API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def trade_checker_loop():
    while True:
        try:
            check_pending_trades()
        except Exception as e:
            print(f"Trade checker error: {e}")
        time.sleep(60) # Check every minute

@app.on_event("startup")
def startup_event():
    init_db()
    # Start the background thread for checking TP/SL
    thread = threading.Thread(target=trade_checker_loop, daemon=True)
    thread.start()

@app.get("/")
def read_root():
    return {"message": "Mesin AI Crypto Aktif! Siap mendeteksi cuan."}

@app.get("/api/top-coins")
def get_top_coins():
    try:
        raw_data = fetch_all_tickers()
        top_coins = analyze_and_sort(raw_data)

        for coin in top_coins:
            ob = get_order_book_details(coin['symbol'])
            tech = get_technical_indicators(coin['symbol']) 
            
            coin['whale_ratio'] = ob['ratio']
            coin['bid_wall_price'] = ob['bid_wall_price']
            coin['bid_wall_usdt'] = ob['bid_wall_usdt']
            coin['ask_wall_price'] = ob['ask_wall_price']
            coin['ask_wall_usdt'] = ob['ask_wall_usdt']
            
            rsi = tech['rsi']
            atr = tech['atr']
            ema_50 = tech['ema_50']
            ema_200 = tech['ema_200']
            
            coin['rsi_15m'] = rsi
            coin['atr'] = atr
            coin['ema_50'] = round(ema_50, 4)
            coin['ema_200'] = round(ema_200, 4)
            
            last_price = float(coin['lastPrice'])
            
            is_uptrend = last_price > ema_200
            coin['trend'] = "Bullish (Uptrend)" if is_uptrend else "Bearish (Downtrend)"
            
            # LOGIKA DAY TRADING (WR OPTIMIZED)
            if ob['ratio'] > 1.5 and rsi < 45 and is_uptrend:
                coin['trade_signal'] = "🔥 STRONG BUY (Uptrend Dip)"
                coin['entry_price'] = round(last_price, 4)
                coin['sl_price'] = round(last_price - (1.5 * atr), 4) if atr else round(last_price * 0.98, 4)
                coin['tp_price'] = round(last_price + (3.0 * atr), 4) if atr else round(last_price * 1.04, 4)
                # Log to DB
                log_trade(coin['symbol'], coin['entry_price'], coin['tp_price'], coin['sl_price'])
                
            elif ob['ratio'] > 2.0 and rsi < 30 and not is_uptrend:
                coin['trade_signal'] = "⚠️ HIGH RISK SCALP (Downtrend)"
                coin['entry_price'] = round(last_price, 4)
                coin['sl_price'] = round(last_price - (1.0 * atr), 4) if atr else round(last_price * 0.99, 4)
                coin['tp_price'] = round(last_price + (2.0 * atr), 4) if atr else round(last_price * 1.02, 4)
                
            elif ob['ratio'] < 0.8 and rsi > 70 and not is_uptrend:
                coin['trade_signal'] = "🩸 DANGER DUMP (Bearish Continuation)"
                coin['entry_price'] = round(last_price, 4)
                coin['sl_price'] = round(last_price + (1.5 * atr), 4) if atr else round(last_price * 1.02, 4)
                coin['tp_price'] = round(last_price - (3.0 * atr), 4) if atr else round(last_price * 0.96, 4)
                
            else:
                if is_uptrend:
                    coin['trade_signal'] = "🐳 Whale Accumulating (Wait for Dip)" if ob['ratio'] > 1.2 else "⚖️ Neutral Uptrend (Limit Buy)"
                    coin['entry_price'] = round(last_price - (1.0 * atr), 4) if atr else round(last_price * 0.99, 4)
                    coin['sl_price'] = round(coin['entry_price'] - (1.5 * atr), 4) if atr else round(last_price * 0.98, 4)
                    coin['tp_price'] = round(coin['entry_price'] + (3.0 * atr), 4) if atr else round(last_price * 1.04, 4)
                else:
                    coin['trade_signal'] = "📉 Bearish (Limit Short)"
                    coin['entry_price'] = round(last_price + (1.0 * atr), 4) if atr else round(last_price * 1.01, 4)
                    coin['sl_price'] = round(coin['entry_price'] + (1.5 * atr), 4) if atr else round(last_price * 1.02, 4)
                    coin['tp_price'] = round(coin['entry_price'] - (3.0 * atr), 4) if atr else round(last_price * 0.96, 4)

        return {
            "status": "success",
            "total_analyzed": len(raw_data),
            "data": top_coins
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/forex")
def get_forex():
    try:
        # Fetch XAUUSD (Gold proxy)
        gold_data = get_forex_data("XAUUSD")
        if not gold_data:
            return {"status": "error", "message": "Failed to fetch XAUUSD data."}
            
        rsi = gold_data['rsi_15m']
        atr = gold_data['atr']
        ema_200 = gold_data.get('ema_200', 0)
        last_price = float(gold_data['lastPrice'])
        is_uptrend = last_price > ema_200
        
        gold_data['trend'] = "Bullish (Uptrend)" if is_uptrend else "Bearish (Downtrend)"
        
        if rsi < 35 and is_uptrend:
            signal = "🔥 OVERSOLD (Buy Opportunity)"
            entry_price = round(last_price, 2)
            sl_price = round(last_price - (1.5 * atr), 2) if atr else round(last_price * 0.99, 2)
            tp_price = round(last_price + (3.0 * atr), 2) if atr else round(last_price * 1.02, 2)
            log_trade("XAUUSD", entry_price, tp_price, sl_price)
            
        elif rsi > 70 and not is_uptrend:
            signal = "⚠️ OVERBOUGHT (Sell/Short Opportunity)"
            entry_price = round(last_price, 2)
            sl_price = round(last_price + (1.5 * atr), 2) if atr else round(last_price * 1.01, 2)
            tp_price = round(last_price - (3.0 * atr), 2) if atr else round(last_price * 0.98, 2)
            log_trade("XAUUSD", entry_price, tp_price, sl_price)
            
        else:
            signal = "⚖️ Neutral (Limit Setup)"
            if is_uptrend:
                entry_price = round(last_price - (1.0 * atr), 2) if atr else round(last_price * 0.99, 2)
                sl_price = round(entry_price - (1.5 * atr), 2) if atr else round(last_price * 0.98, 2)
                tp_price = round(entry_price + (3.0 * atr), 2) if atr else round(last_price * 1.02, 2)
            else:
                entry_price = round(last_price + (1.0 * atr), 2) if atr else round(last_price * 1.01, 2)
                sl_price = round(entry_price + (1.5 * atr), 2) if atr else round(last_price * 1.02, 2)
                tp_price = round(entry_price - (3.0 * atr), 2) if atr else round(last_price * 0.98, 2)
        
        gold_data['trade_signal'] = signal
        gold_data['entry_price'] = entry_price
        gold_data['sl_price'] = sl_price
        gold_data['tp_price'] = tp_price
        
        return {
            "status": "success",
            "data": [gold_data]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/performance")
def get_performance():
    try:
        stats = get_performance_stats()
        return {
            "status": "success",
            "data": stats
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/select-trade")
def select_trade(trade: dict):
    # trade expect: {symbol, entry, tp, sl}
    try:
        log_trade(
            trade.get('symbol'), 
            float(trade.get('entry')), 
            float(trade.get('tp')), 
            float(trade.get('sl'))
        )
        return {"status": "success", "message": "Trade picked and saved!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/trade-history")
def get_history():
    try:
        from database import DB_PATH
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT 20")
        rows = cursor.fetchall()
        history = [dict(row) for row in rows]
        conn.close()
        return {"status": "success", "data": history}
    except Exception as e:
        return {"status": "error", "message": str(e)}