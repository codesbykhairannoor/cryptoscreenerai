import psycopg2
import time
from datetime import datetime, timedelta

DATABASE_URL = "postgres://postgres.ejqpkdwxkkcwiyfoqsfd:Kh%40iranaja09@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

def fetch_trades():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # 6 jam yang lalu (dalam ms)
        six_hours_ago_ms = int((time.time() - 6 * 3600) * 1000)
        
        print("="*100)
        print("AUDIT TRANSAKSI CRYPTO (6 JAM TERAKHIR)")
        print("="*100)
        
        # Query yang benar berdasarkan inspeksi kolom
        cur.execute("""
            SELECT symbol, side, entry_price, tp_price, sl_price, status, pnl_usd, timestamp
            FROM trades 
            WHERE timestamp > %s 
            ORDER BY timestamp DESC 
        """, (six_hours_ago_ms,))
        
        rows = cur.fetchall()
        if not rows:
            print("Tidak ada transaksi ditemukan dalam 6 jam terakhir.")
            # Coba ambil 12 jam terakhir jika 6 jam kosong
            print("Mencoba mengambil 24 jam terakhir...")
            day_ago_ms = int((time.time() - 24 * 3600) * 1000)
            cur.execute("""
                SELECT symbol, side, entry_price, tp_price, sl_price, status, pnl_usd, timestamp
                FROM trades 
                WHERE timestamp > %s 
                ORDER BY timestamp DESC 
                LIMIT 10
            """, (day_ago_ms,))
            rows = cur.fetchall()

        if not rows:
            print("Database benar-benar kosong untuk hari ini.")
            return

        total_profit = 0
        wins = 0
        losses = 0

        for row in rows:
            symbol, side, entry, tp, sl, status, pnl, ts = row
            dt = datetime.fromtimestamp(ts / 1000) + timedelta(hours=8)
            pnl_val = pnl if pnl else 0
            
            pnl_str = f"${pnl_val:>+6.2f}" if pnl_val != 0 else " OPEN "
            
            print(f"[{dt.strftime('%H:%M:%S')}] {symbol:<12} | {side.upper():<4} | Ent: {entry:<8.4f} | TP: {tp:<8.4f} | SL: {sl:<8.4f} | Status: {status:<8} | PnL: {pnl_str}")
            
            if pnl_val > 0: wins += 1
            elif pnl_val < 0: losses += 1
            total_profit += pnl_val

        print("="*100)
        print(f"RINGKASAN: Wins: {wins} | Losses: {losses} | Total PnL: ${total_profit:.2f}")

        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fetch_trades()
