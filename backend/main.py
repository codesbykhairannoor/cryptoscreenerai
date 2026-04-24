from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from data_fetcher import (
    fetch_all_tickers, get_order_book_details, get_technical_indicators, 
    get_forex_data, get_idx_data, get_idx_market_status
)
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
def get_top_coins(timeframe: str = "15m"):
    try:
        raw_data = fetch_all_tickers()
        top_coins = analyze_and_sort(raw_data)
        
        # ENSURE BTC IS ALWAYS INCLUDED
        btc_exists = any(c['symbol'] == 'BTCUSDT' for c in top_coins)
        if not btc_exists:
            btc_row = raw_data[raw_data['symbol'] == 'BTCUSDT'].to_dict('records')
            if btc_row:
                top_coins.insert(0, btc_row[0])
        else:
            # Move BTC to top
            btc_idx = next(i for i, c in enumerate(top_coins) if c['symbol'] == 'BTCUSDT')
            btc_coin = top_coins.pop(btc_idx)
            top_coins.insert(0, btc_coin)

        for coin in top_coins:
            ob = get_order_book_details(coin['symbol'])
            tech = get_technical_indicators(coin['symbol'], interval=timeframe) 
            
            coin['whale_ratio'] = ob['ratio']
            coin['bid_wall_price'] = ob['bid_wall_price']
            coin['bid_wall_usdt'] = ob['bid_wall_usdt']
            coin['ask_wall_price'] = ob['ask_wall_price']
            coin['ask_wall_usdt'] = ob['ask_wall_usdt']
            
            rsi = tech['rsi']
            atr = tech['atr']
            ema_200_cur = tech['ema_200']
            ema_200_htf = tech['ema_200_htf']
            
            coin['rsi_15m'] = rsi
            coin['atr'] = atr
            coin['ema_200'] = round(ema_200_cur, 4)
            coin['ema_200_htf'] = round(ema_200_htf, 4)
            coin['htf'] = tech['htf']
            
            last_price = float(coin['lastPrice'])
            
            # Trend Detection (MTF)
            is_uptrend_cur = last_price > ema_200_cur
            is_uptrend_htf = last_price > ema_200_htf
            
            coin['trend'] = f"Bullish ({coin['htf']} Confirmed)" if (is_uptrend_cur and is_uptrend_htf) else \
                           f"Bullish ({coin['htf']} Pullback)" if (is_uptrend_htf and not is_uptrend_cur) else \
                           f"Bearish ({coin['htf']} Confirmed)" if (not is_uptrend_cur and not is_uptrend_htf) else \
                           "Neutral/Transition"

            # Confidence Calculation
            confidence = 35 
            if is_uptrend_cur and is_uptrend_htf: confidence += 20
            if ob['ratio'] > 1.5: confidence += 15
            if rsi < 45: confidence += 15
            if (atr / last_price) * 100 > 0.4: confidence += 10
            confidence = min(confidence, 88) if rsi > 30 else 92

            # ALWAYS CALCULATE TARGETS
            coin['entry_price'] = round(last_price, 4)
            coin['sl_price'] = round(last_price - (2.0 * atr), 4) if atr else round(last_price * 0.97, 4)
            coin['tp_price'] = round(last_price + (5.0 * atr), 4) if atr else round(last_price * 1.08, 4)

            if ob['ratio'] > 1.5 and rsi < 40 and is_uptrend_htf:
                coin['trade_signal'] = f"🔥 STRONG BUY ({timeframe} Prob: {confidence}%)"
            elif ob['ratio'] > 2.0 and rsi < 30:
                coin['trade_signal'] = f"⚡ FAST SCALP ({timeframe} Prob: {confidence}%)"
            elif rsi > 75 and not is_uptrend_htf:
                coin['trade_signal'] = f"🩸 DANGER DUMP ({timeframe} Prob: {confidence-10}%)"
                coin['sl_price'] = round(last_price + (2.0 * atr), 4) if atr else round(last_price * 1.03, 4)
                coin['tp_price'] = round(last_price - (5.0 * atr), 4) if atr else round(last_price * 0.92, 4)
            else:
                coin['trade_signal'] = f"⚖️ Neutral ({timeframe} Prob: {confidence}%)"

        return {
            "status": "success",
            "total_analyzed": len(raw_data),
            "data": top_coins
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/forex")
def get_forex(timeframe: str = "15m"):
    try:
        asset_data = get_forex_data("XAUUSD", interval=timeframe)
        if not asset_data:
            return {"status": "error", "message": "Failed to fetch XAUUSD data."}
            
        rsi = asset_data['rsi']
        atr = asset_data['atr']
        ema_200_cur = asset_data['ema_200']
        ema_200_htf = asset_data['ema_200_htf']
        last_price = float(asset_data['lastPrice'])
        
        is_uptrend_cur = last_price > ema_200_cur
        is_uptrend_htf = last_price > ema_200_htf
        
        asset_data['trend'] = f"Bullish ({asset_data['htf']} Confirmed)" if (is_uptrend_cur and is_uptrend_htf) else \
                             f"Bearish ({asset_data['htf']} Confirmed)" if (not is_uptrend_cur and not is_uptrend_htf) else \
                             "Neutral/Transition"
        
        # Confidence logic for Gold
        confidence = 40
        if is_uptrend_cur and is_uptrend_htf: confidence += 25
        if rsi < 35: confidence += 20
        
        # Tighten TP/SL for Gold (Tighter for Scalping)
        # 15m: Tighter SL (~10-20 pips)
        # 1h: Medium SL
        # 1d: Standard Swing SL
        sl_mult = 0.8 if timeframe == "15m" else 1.5 if timeframe == "1h" else 2.5
        tp_mult = 2.0 if timeframe == "15m" else 4.0 if timeframe == "1h" else 6.0
        
        asset_data['entry_price'] = round(last_price, 2)
        asset_data['sl_price'] = round(last_price - (sl_mult * atr), 2) if atr else round(last_price - 1.5, 2)
        asset_data['tp_price'] = round(last_price + (tp_mult * atr), 2) if atr else round(last_price + 4.0, 2)
        
        if rsi < 35 and is_uptrend_htf:
            asset_data['trade_signal'] = f"🔥 OVERSOLD (Win Prob: {confidence}%)"
        elif rsi > 70 and not is_uptrend_htf:
            asset_data['trade_signal'] = f"⚠️ OVERBOUGHT (Win Prob: {confidence-10}%)"
            asset_data['sl_price'] = round(last_price + (sl_mult * atr), 2) if atr else round(last_price + 1.5, 2)
            asset_data['tp_price'] = round(last_price - (tp_mult * atr), 2) if atr else round(last_price - 4.0, 2)
        else:
            asset_data['trade_signal'] = f"⚖️ Neutral (Win Prob: {confidence}%)"
        
        asset_data['rsi_15m'] = rsi # Keep legacy key for UI
        
        return {
            "status": "success",
            "data": [asset_data]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/idx-stocks")
def get_idx(timeframe: str = "15m"):
    try:
        stocks = get_idx_data(interval=timeframe)
        market_status = get_idx_market_status()
        
        for stock in stocks:
            rsi = stock['rsi']
            atr = stock['atr']
            ema_200_cur = stock['ema_200']
            ema_200_htf = stock['ema_200_htf']
            last_price = float(stock['lastPrice'])
            bid_size = stock.get('bid_size', 0)
            avg_vol = stock.get('avg_volume', 1)
            
            is_uptrend_cur = last_price > ema_200_cur
            is_uptrend_htf = last_price > ema_200_htf
            
            stock['trend'] = f"Bullish ({stock['htf']} Confirmed)" if (is_uptrend_cur and is_uptrend_htf) else \
                            f"Bearish ({stock['htf']} Confirmed)" if (not is_uptrend_cur and not is_uptrend_htf) else \
                            "Neutral/Transition"
            
            # Use the advanced demand score from get_idx_data
            demand_score = stock.get('demand_score', 0)
            stock['whale_ratio'] = round(stock.get('relative_volume', 1.0), 2)
            
            # Confidence Logic for IDX
            confidence = 40
            if is_uptrend_cur and is_uptrend_htf: confidence += 20
            if demand_score > 60: confidence += 20 
            if stock.get('cmf', 0) > 0.1: confidence += 10
            
            stock['entry_price'] = round(last_price, 0)
            stock['sl_price'] = round(last_price - (2.0 * atr), 0) if atr else round(last_price * 0.95, 0)
            stock['tp_price'] = round(last_price + (5.0 * atr), 0) if atr else round(last_price * 1.10, 0)
            
            if demand_score > 70:
                stock['trade_signal'] = f"🔥 WHALE ACCUMULATION ({confidence}% Win)"
            elif rsi < 40 and is_uptrend_htf:
                stock['trade_signal'] = f"📈 TREND BUY ({confidence}% Win)"
            elif rsi > 70:
                stock['trade_signal'] = f"⚠️ OVERBOUGHT ({confidence-20}% Win)"
            else:
                stock['trade_signal'] = f"⚖️ Neutral ({confidence}% Win)"

            stock['rsi_15m'] = rsi
            
        return {
            "status": "success",
            "market_status": market_status,
            "data": stocks
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
    # trade expect: {symbol, entry, tp, sl, market}
    try:
        success = log_trade(
            trade.get('symbol'), 
            float(trade.get('entry')), 
            float(trade.get('tp')), 
            float(trade.get('sl')),
            market=trade.get('market', 'crypto')
        )
        if success:
            return {"status": "success", "message": f"Trade {trade.get('symbol')} ({trade.get('market')}) berhasil disimpan!"}
        else:
            return {"status": "warning", "message": f"Trade {trade.get('symbol')} sudah ada di journal."}
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