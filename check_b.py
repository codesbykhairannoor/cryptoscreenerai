import psycopg2
from psycopg2.extras import RealDictCursor
import os

DATABASE_URL = "postgres://postgres.ejqpkdwxkkcwiyfoqsfd:Kh%40iranaja09@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

def check_b():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades WHERE symbol LIKE '%B%USDT%' ORDER BY id DESC LIMIT 5")
    rows = cur.fetchall()
    for r in rows:
        print(f"ID: {r['id']} | Symbol: {r['symbol']} | Side: {r['side']} | Entry: {r['entry_price']} | Exit: {r['exit_price']} | PnL%: {r['pnl_pct']} | Status: {r['status']}")
    conn.close()

if __name__ == "__main__":
    check_b()
