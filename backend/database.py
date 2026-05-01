import psycopg2
from psycopg2.extras import RealDictCursor
import os
import time
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    # Create table with market column if it doesn't exist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            entry_price DOUBLE PRECISION,
            tp_price DOUBLE PRECISION,
            sl_price DOUBLE PRECISION,
            status TEXT DEFAULT 'PENDING',
            market TEXT DEFAULT 'crypto',
            timestamp BIGINT
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()

def log_trade(symbol, entry, tp, sl, market='crypto'):
    # Safety: ensure all numeric values are standard python floats
    entry = float(entry) if entry is not None else 0.0
    tp = float(tp) if tp is not None else 0.0
    sl = float(sl) if sl is not None else 0.0
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Check if a pending trade for this symbol already exists in this market
    cursor.execute("SELECT id FROM trades WHERE symbol = %s AND status = 'PENDING' AND market = %s", (symbol, market))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        return False

    cursor.execute('''
        INSERT INTO trades (symbol, entry_price, tp_price, sl_price, status, market, timestamp)
        VALUES (%s, %s, %s, %s, 'PENDING', %s, %s)
    ''', (symbol, entry, tp, sl, market, int(time.time() * 1000)))
    conn.commit()
    cursor.close()
    conn.close()
    return True

import requests

def get_current_price(symbol, market='crypto'):
    """
    GENIUS SYNC: Uses DIRECT API credentials from .env to fetch prices.
    No more TradingView proxies.
    """
    try:
        if market == 'forex' or "XAU" in symbol:
            from forex_executor import ForexExecutor
            fx = ForexExecutor()
            price = fx.get_live_price("XAUUSD")
            if price > 0: return price
            
        # Crypto Fallback (Bitget Direct)
        clean_symbol = symbol.replace("/", "").replace(":USDT", "").replace("USDT", "") + "USDT"
        url = f"https://api.bitget.com/api/v3/market/tickers?symbol={clean_symbol}"
        res = requests.get(url, timeout=5, verify=False).json()
        if res.get('code') == '00000' and res.get('data'):
            return float(res['data'][0].get('last', 0))
            
        # Last Resort: Binance Public (Stable)
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={clean_symbol}"
        res = requests.get(url, timeout=5).json()
        if 'price' in res:
            return float(res['price'])
    except Exception as e:
        pass
    return None

def check_pending_trades():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT id, symbol, entry_price, tp_price, sl_price, status, market FROM trades WHERE status IN ('PENDING', 'RUNNING')")
    pending_trades = cursor.fetchall()
    
    for trade in pending_trades:
        trade_id = trade['id']
        symbol = trade['symbol']
        entry = trade['entry_price']
        tp = trade['tp_price']
        sl = trade['sl_price']
        current_status = trade['status']
        market = trade.get('market', 'crypto')
        
        try:
            current_price = get_current_price(symbol, market=market)
            if not current_price:
                continue
                
            status = current_status
            is_long = tp > sl
            
            if is_long:
                if current_price >= tp:
                    status = 'WIN'
                elif current_price <= sl:
                    status = 'LOSS'
                elif current_status == 'PENDING' and current_price <= entry:
                    status = 'RUNNING'
            else:
                if current_price <= tp:
                    status = 'WIN'
                elif current_price >= sl:
                    status = 'LOSS'
                elif current_status == 'PENDING' and current_price >= entry:
                    status = 'RUNNING'
                    
            if status != current_status:
                cursor.execute("UPDATE trades SET status = %s WHERE id = %s", (status, trade_id))
                conn.commit()
        except Exception as e:
            print(f"Error checking trade {trade_id}: {e}")
            
    cursor.close()
    conn.close()

def get_performance_stats(market=None):
    conn = get_connection()
    cursor = conn.cursor()
    
    if market:
        cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'WIN' AND market = %s", (market,))
        wins = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'LOSS' AND market = %s", (market,))
        losses = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM trades WHERE status IN ('PENDING', 'RUNNING') AND market = %s", (market,))
        pending = cursor.fetchone()[0]
    else:
        cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'WIN'")
        wins = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'LOSS'")
        losses = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM trades WHERE status IN ('PENDING', 'RUNNING')")
        pending = cursor.fetchone()[0]
    
    cursor.close()
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
