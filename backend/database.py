import sqlite3
import os
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "trades.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            entry_price REAL,
            tp_price REAL,
            sl_price REAL,
            status TEXT,
            timestamp INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def log_trade(symbol, entry, tp, sl):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if a pending trade for this symbol already exists to avoid spamming
    cursor.execute("SELECT id FROM trades WHERE symbol = ? AND status = 'PENDING'", (symbol,))
    if cursor.fetchone():
        conn.close()
        return False

    cursor.execute('''
        INSERT INTO trades (symbol, entry_price, tp_price, sl_price, status, timestamp)
        VALUES (?, ?, ?, ?, 'PENDING', ?)
    ''', (symbol, entry, tp, sl, int(time.time())))
    conn.commit()
    conn.close()
    return True

import requests

def get_current_price(symbol):
    try:
        if symbol == "XAUUSD" or symbol == "GC=F":
            # Use the same accurate OANDA Spot price from TradingView
            tv_url = 'https://scanner.tradingview.com/cfd/scan'
            tv_payload = {'symbols': {'tickers': ['OANDA:XAUUSD']}, 'columns': ['close']}
            tv_res = requests.post(tv_url, json=tv_payload, timeout=5)
            tv_data = tv_res.json()
            if tv_data.get('data') and len(tv_data['data']) > 0:
                return float(tv_data['data'][0]['d'][0])
        else:
            url = f"https://data-api.binance.vision/api/v3/ticker/price?symbol={symbol}"
            res = requests.get(url).json()
            if 'price' in res:
                return float(res['price'])
    except Exception as e:
        print(f"Price check error for {symbol}: {e}")
    return None

def check_pending_trades():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, symbol, entry_price, tp_price, sl_price, status FROM trades WHERE status IN ('PENDING', 'RUNNING')")
    pending_trades = cursor.fetchall()
    
    for trade in pending_trades:
        trade_id, symbol, entry, tp, sl, current_status = trade
        try:
            current_price = get_current_price(symbol)
            if not current_price:
                continue
                
            status = current_status
            
            # Side detection
            is_long = tp > sl
            
            if is_long:
                # LONG: Entry is usually below last price (buy dip)
                if current_price >= tp:
                    status = 'WIN'
                elif current_price <= sl:
                    status = 'LOSS'
                elif current_status == 'PENDING' and current_price <= entry:
                    status = 'RUNNING'
            else:
                # SHORT: Entry is usually above last price (sell bounce)
                if current_price <= tp:
                    status = 'WIN'
                elif current_price >= sl:
                    status = 'LOSS'
                elif current_status == 'PENDING' and current_price >= entry:
                    status = 'RUNNING'
                    
            if status != current_status:
                cursor.execute("UPDATE trades SET status = ? WHERE id = ?", (status, trade_id))
                conn.commit()
        except Exception as e:
            print(f"Error checking trade {trade_id}: {e}")
            
    conn.close()

def get_performance_stats():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'WIN'")
    wins = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'LOSS'")
    losses = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'PENDING'")
    pending = cursor.fetchone()[0]
    
    conn.close()
    
    total_closed = wins + losses
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0
    
    return {
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "win_rate": round(win_rate, 2),
        "total_closed": total_closed
    }
