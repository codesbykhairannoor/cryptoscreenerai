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

    # Tabel utama trades
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            entry_price DOUBLE PRECISION,
            tp_price DOUBLE PRECISION,
            sl_price DOUBLE PRECISION,
            exit_price DOUBLE PRECISION DEFAULT 0,
            status TEXT DEFAULT 'PENDING',
            market TEXT DEFAULT 'crypto',
            side TEXT DEFAULT 'buy',
            lot_size DOUBLE PRECISION DEFAULT 0,
            pnl_usd DOUBLE PRECISION DEFAULT 0,
            pnl_pct DOUBLE PRECISION DEFAULT 0,
            score INTEGER DEFAULT 0,
            reason TEXT DEFAULT '',
            session TEXT DEFAULT '',
            timestamp BIGINT,
            closed_at BIGINT DEFAULT 0
        )
    ''')

    # Tambah kolom baru kalau belum ada (untuk database yang sudah ada)
    new_columns = [
        ("exit_price", "DOUBLE PRECISION DEFAULT 0"),
        ("side", "TEXT DEFAULT 'buy'"),
        ("lot_size", "DOUBLE PRECISION DEFAULT 0"),
        ("pnl_usd", "DOUBLE PRECISION DEFAULT 0"),
        ("pnl_pct", "DOUBLE PRECISION DEFAULT 0"),
        ("score", "INTEGER DEFAULT 0"),
        ("reason", "TEXT DEFAULT ''"),
        ("session", "TEXT DEFAULT ''"),
        ("closed_at", "BIGINT DEFAULT 0"),
    ]
    for col_name, col_def in new_columns:
        try:
            cursor.execute(f"ALTER TABLE trades ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
        except Exception:
            pass

    conn.commit()
    cursor.close()
    conn.close()

def log_trade(symbol, entry, tp, sl, market='crypto', side='buy',
              lot_size=0, score=0, reason='', session=''):
    """
    Log trade baru ke database.
    Setiap trade SELALU disimpan — tidak ada cek duplikat yang memblok.
    Duplikat diizinkan karena bot bisa punya multiple posisi untuk symbol yang sama.
    """
    entry = float(entry) if entry is not None else 0.0
    tp    = float(tp)    if tp    is not None else 0.0
    sl    = float(sl)    if sl    is not None else 0.0

    # Deteksi session saat ini
    if not session:
        import datetime
        hour = datetime.datetime.utcnow().hour
        wib  = (hour + 7) % 24
        if 7 <= hour < 12:    session = f"London({wib:02d}WIB)"
        elif 12 <= hour < 17: session = f"London+NY({wib:02d}WIB)"
        elif 17 <= hour < 21: session = f"NY({wib:02d}WIB)"
        elif 2 <= hour < 6:   session = f"Asia({wib:02d}WIB)"
        else:                  session = f"Off({wib:02d}WIB)"

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO trades
                (symbol, entry_price, tp_price, sl_price, status, market, side,
                 lot_size, score, reason, session, timestamp)
            VALUES (%s, %s, %s, %s, 'PENDING', %s, %s, %s, %s, %s, %s, %s)
        ''', (symbol, entry, tp, sl, market, side,
              float(lot_size), int(score), str(reason)[:200], session,
              int(time.time() * 1000)))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB LOG ERROR] {symbol}: {e}")
        return False

def close_trade(symbol, exit_price, pnl_usd=0, market='crypto'):
    """
    Update trade yang sudah close dengan exit price dan PnL aktual.
    Dipanggil saat SL/TP kena atau manual close.
    """
    exit_price = float(exit_price) if exit_price else 0.0
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE trades
        SET exit_price = %s,
            pnl_usd    = %s,
            status     = CASE WHEN %s >= 0 THEN 'WIN' ELSE 'LOSS' END,
            closed_at  = %s
        WHERE symbol = %s AND market = %s AND status IN ('PENDING', 'RUNNING')
    ''', (exit_price, float(pnl_usd), float(pnl_usd),
          int(time.time() * 1000), symbol, market))
    conn.commit()
    cursor.close()
    conn.close()

import requests

def get_current_price(symbol, market='crypto'):
    try:
        if market == 'forex' or "XAU" in symbol:
            from forex_executor import ForexExecutor
            fx = ForexExecutor()
            price_data = fx.get_live_price()
            mid = price_data.get("mid", 0)
            if mid > 0: return mid

        clean_symbol = symbol.replace("/", "").replace(":USDT", "").replace("USDT", "") + "USDT"
        url = f"https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
        res = requests.get(url, timeout=5, verify=False).json()
        if res.get('code') == '00000':
            for t in res.get('data', []):
                if t.get('symbol') == clean_symbol:
                    return float(t.get('lastPr', 0))

        url = f"https://api.binance.com/api/v3/ticker/price?symbol={clean_symbol}"
        res = requests.get(url, timeout=5).json()
        if 'price' in res:
            return float(res['price'])
    except Exception:
        pass
    return None

def check_pending_trades():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(
        "SELECT id, symbol, entry_price, tp_price, sl_price, status, market "
        "FROM trades WHERE status IN ('PENDING', 'RUNNING')"
    )
    pending_trades = cursor.fetchall()

    for trade in pending_trades:
        trade_id = trade['id']
        symbol   = trade['symbol']
        entry    = trade['entry_price']
        tp       = trade['tp_price']
        sl       = trade['sl_price']
        current_status = trade['status']
        market   = trade.get('market', 'crypto')

        try:
            current_price = get_current_price(symbol, market=market)
            if not current_price:
                continue

            status   = current_status
            is_long  = tp > sl

            if is_long:
                if current_price >= tp:   status = 'WIN'
                elif current_price <= sl: status = 'LOSS'
                elif current_status == 'PENDING' and current_price <= entry:
                    status = 'RUNNING'
            else:
                if current_price <= tp:   status = 'WIN'
                elif current_price >= sl: status = 'LOSS'
                elif current_status == 'PENDING' and current_price >= entry:
                    status = 'RUNNING'

            if status != current_status:
                pnl = (current_price - entry) if is_long else (entry - current_price)
                cursor.execute(
                    "UPDATE trades SET status = %s, exit_price = %s, closed_at = %s WHERE id = %s",
                    (status, current_price, int(time.time() * 1000), trade_id)
                )
                conn.commit()
        except Exception as e:
            print(f"Error checking trade {trade_id}: {e}")

    cursor.close()
    conn.close()

def get_performance_stats(market=None):
    conn = get_connection()
    cursor = conn.cursor()

    q_filter = "AND market = %s" if market else ""
    params   = (market,) if market else ()

    def count(where):
        cursor.execute(f"SELECT COUNT(*) FROM trades WHERE {where} {q_filter}", params)
        return cursor.fetchone()[0]

    def sum_col(col, where):
        cursor.execute(f"SELECT COALESCE(SUM({col}), 0) FROM trades WHERE {where} {q_filter}", params)
        return float(cursor.fetchone()[0])

    wins    = count("status = 'WIN'")
    losses  = count("status = 'LOSS'")
    pending = count("status IN ('PENDING', 'RUNNING')")
    total_pnl = sum_col("pnl_usd", "status IN ('WIN', 'LOSS')")

    cursor.close()
    conn.close()

    total_closed = wins + losses
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0

    return {
        "wins":         wins,
        "losses":       losses,
        "pending":      pending,
        "win_rate":     round(win_rate, 2),
        "total_closed": total_closed,
        "total_pnl":    round(total_pnl, 2),
    }

def get_trade_history(market=None, limit=50):
    """Ambil history trade untuk analisis."""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    if market:
        cursor.execute(
            "SELECT * FROM trades WHERE market = %s ORDER BY timestamp DESC LIMIT %s",
            (market, limit)
        )
    else:
        cursor.execute(
            "SELECT * FROM trades ORDER BY timestamp DESC LIMIT %s",
            (limit,)
        )

    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]
