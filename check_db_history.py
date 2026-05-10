import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

# Use the DB URL provided by the user
DATABASE_URL = "postgres://postgres.ejqpkdwxkkcwiyfoqsfd:Kh%40iranaja09@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

def check_history():
    print("Connecting to Supabase Database...")
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cursor = conn.cursor()
        
        # Ambil 10 trade terakhir
        cursor.execute("""
            SELECT id, symbol, side, entry_price, exit_price, pnl_usd, pnl_pct, status, market, closed_at 
            FROM trades 
            WHERE market = 'crypto'
            ORDER BY id DESC 
            LIMIT 20
        """)
        
        rows = cursor.fetchall()
        
        if not rows:
            print("Belum ada riwayat trade di database.")
        else:
            print(f"{'ID':<5} | {'SYMBOL':<10} | {'SIDE':<5} | {'ENTRY':<10} | {'EXIT':<10} | {'PNL $':<8} | {'PNL %':<8} | {'STATUS':<10}")
            print("-" * 90)
            for r in rows:
                pnl_pct = r['pnl_pct'] if r['pnl_pct'] is not None else 0.0
                pnl_usd = r['pnl_usd'] if r['pnl_usd'] is not None else 0.0
                status = r['status']
                exit_p = r['exit_price'] if r['exit_price'] is not None else 0.0
                
                print(f"{r['id']:<5} | {r['symbol']:<10} | {r['side']:<5} | {r['entry_price']:<10.4f} | {exit_p:<10.4f} | {pnl_usd:<8.2f} | {pnl_pct:<8.2f} | {status:<10}")
        
        print("="*80)
        
        # Summary
        cursor.execute("SELECT COUNT(*) as total, SUM(pnl_pct) as total_pnl FROM trades WHERE status = 'CLOSED' AND market = 'crypto'")
        summary = cursor.fetchone()
        if summary and summary['total'] > 0:
            print(f"Total Trade Selesai: {summary['total']}")
            print(f"Total PnL Akumulasi: {summary['total_pnl'] or 0:.2f}%")
        
        conn.close()
    except Exception as e:
        print(f"Database Error: {e}")

if __name__ == "__main__":
    check_history()
