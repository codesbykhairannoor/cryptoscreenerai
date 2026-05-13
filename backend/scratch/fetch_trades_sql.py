import psycopg2
import os
from datetime import datetime, timedelta

DATABASE_URL = "postgres://postgres.ejqpkdwxkkcwiyfoqsfd:Kh%40iranaja09@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

def fetch_trades():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Ambil trade dalam 12 jam terakhir
        twelve_hours_ago = datetime.utcnow() - timedelta(hours=12)
        
        print("="*90)
        print("AUDIT TRANSAKSI CRYPTO (12 JAM TERAKHIR)")
        print("="*90)
        
        # Kita coba ambil data dari tabel 'trades'
        # Query kolom yang umum ada: symbol, side, price, tp, sl, created_at, pnl
        cur.execute("""
            SELECT symbol, side, price, tp, sl, created_at 
            FROM trades 
            WHERE created_at > %s 
            ORDER BY created_at DESC 
            LIMIT 30
        """, (twelve_hours_ago,))
        
        rows = cur.fetchall()
        if not rows:
            print("Tidak ada transaksi ditemukan dalam 12 jam terakhir.")
            return

        for row in rows:
            symbol, side, price, tp, sl, created_at = row
            # Format time
            time_local = created_at + timedelta(hours=8) # Convert to WITA (User local time)
            print(f"[{time_local.strftime('%H:%M:%S')}] {symbol:<12} | {side.upper():<4} | Entry: {price:<10} | TP: {tp:<10} | SL: {sl}")

        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fetch_trades()
