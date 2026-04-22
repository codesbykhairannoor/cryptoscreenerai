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
        return

    cursor.execute('''
        INSERT INTO trades (symbol, entry_price, tp_price, sl_price, status, timestamp)
        VALUES (?, ?, ?, ?, 'PENDING', ?)
    ''', (symbol, entry, tp, sl, int(time.time())))
    conn.commit()
    conn.close()

import requests

def get_current_price(symbol):
    try:
        if symbol == "GC=F" or symbol == "XAUUSD":
            import yfinance as yf
            ticker = yf.Ticker("GC=F")
            hist = ticker.history(period="1d", interval="1m")
            if not hist.empty:
                return float(hist['Close'].iloc[-1])
        else:
            url = f"https://data-api.binance.vision/api/v3/ticker/price?symbol={symbol}"
            res = requests.get(url).json()
            if 'price' in res:
                return float(res['price'])
    except:
        pass
    return None

def check_pending_trades():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, symbol, tp_price, sl_price FROM trades WHERE status = 'PENDING'")
    pending_trades = cursor.fetchall()
    
    for trade in pending_trades:
        trade_id, symbol, tp, sl = trade
        try:
            current_price = get_current_price(symbol)
            if not current_price:
                continue
                
            status = 'PENDING'
            # Determine if it hit TP or SL (assuming a long position for now)
            # If tp > entry (Long position)
            if tp > sl:
                if current_price >= tp:
                    status = 'WIN'
                elif current_price <= sl:
                    status = 'LOSS'
            else:
                # Short position
                if current_price <= tp:
                    status = 'WIN'
                elif current_price >= sl:
                    status = 'LOSS'
                    
            if status != 'PENDING':
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
