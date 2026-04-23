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
            ema_200_15m = tech['ema_200']
            ema_200_1h = tech['ema_200_1h']
            
            coin['rsi_15m'] = rsi
            coin['atr'] = atr
            coin['ema_200'] = round(ema_200_15m, 4)
            coin['ema_200_1h'] = round(ema_200_1h, 4)
            
            last_price = float(coin['lastPrice'])
            
            # Trend Detection (MTF)
            is_uptrend_15m = last_price > ema_200_15m
            is_uptrend_1h = last_price > ema_200_1h
            
            coin['trend'] = "Bullish (MTF Confirmed)" if (is_uptrend_15m and is_uptrend_1h) else \
                           "Bullish (Pullback)" if (is_uptrend_1h and not is_uptrend_15m) else \
                           "Bearish (MTF Confirmed)" if (not is_uptrend_15m and not is_uptrend_1h) else \
                           "Neutral/Transition"

            # Volatility Check
            volatility_ratio = (atr / last_price) * 100 if last_price > 0 else 0
            is_volatile = volatility_ratio > 0.3 # Minimum 0.3% movement per candle

            # LOGIKA DAY TRADING (SUPER SMART & AGGRESSIVE TP)
            if not is_volatile:
                coin['trade_signal'] = "⚖️ Low Volatility (Sideways)"
                coin['entry_price'] = 0
                coin['sl_price'] = 0
                coin['tp_price'] = 0
            elif ob['ratio'] > 1.5 and rsi < 40 and is_uptrend_1h:
                # STRONG BUY with MTF Confirmation
                coin['trade_signal'] = "🔥 STRONG BUY (MTF Trend)"
                coin['entry_price'] = round(last_price, 4)
                # SL: 2.0x ATR, TP: 5.0x ATR (High Risk/Reward)
                coin['sl_price'] = round(last_price - (2.0 * atr), 4) if atr else round(last_price * 0.97, 4)
                coin['tp_price'] = round(last_price + (5.0 * atr), 4) if atr else round(last_price * 1.08, 4)
                pass
                
            elif ob['ratio'] > 2.0 and rsi < 30:
                # OVERSOLD SCALP
                coin['trade_signal'] = "⚡ FAST SCALP (Oversold)"
                coin['entry_price'] = round(last_price, 4)
                coin['sl_price'] = round(last_price - (1.5 * atr), 4) if atr else round(last_price * 0.98, 4)
                coin['tp_price'] = round(last_price + (3.5 * atr), 4) if atr else round(last_price * 1.05, 4)
                
            elif rsi > 75 and not is_uptrend_1h:
                # SHORT OPPORTUNITY
                coin['trade_signal'] = "🩸 DANGER DUMP (Overbought)"
                coin['entry_price'] = round(last_price, 4)
                coin['sl_price'] = round(last_price + (2.0 * atr), 4) if atr else round(last_price * 1.03, 4)
                coin['tp_price'] = round(last_price - (5.0 * atr), 4) if atr else round(last_price * 0.92, 4)
                
            else:
                coin['trade_signal'] = "👀 Waiting for Better Setup"
                coin['entry_price'] = 0
                coin['sl_price'] = 0
                coin['tp_price'] = 0

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
            # Sinyal terdeteksi, tapi jangan auto-log ke DB.
            pass
            
        elif rsi > 70 and not is_uptrend:
            signal = "⚠️ OVERBOUGHT (Sell/Short Opportunity)"
            entry_price = round(last_price, 2)
            sl_price = round(last_price + (1.5 * atr), 2) if atr else round(last_price * 1.01, 2)
            tp_price = round(last_price - (3.0 * atr), 2) if atr else round(last_price * 0.98, 2)
            # Sinyal terdeteksi, tapi jangan auto-log ke DB.
            pass
            
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
        success = log_trade(
            trade.get('symbol'), 
            float(trade.get('entry')), 
            float(trade.get('tp')), 
            float(trade.get('sl'))
        )
        if success:
            return {"status": "success", "message": f"Trade {trade.get('symbol')} berhasil disimpan ke journal!"}
        else:
            return {"status": "warning", "message": f"Trade {trade.get('symbol')} sudah ada di journal (Pending)."}
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