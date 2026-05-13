import os
import psycopg2
from psycopg2.extras import RealDictCursor
import datetime

DATABASE_URL = "postgres://postgres.ejqpkdwxkkcwiyfoqsfd:Kh%40iranaja09@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

def check_performance():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # 1. Overall Stats
        cursor.execute("SELECT COUNT(*) as total FROM trades WHERE market = 'forex'")
        total = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as wins FROM trades WHERE market = 'forex' AND status = 'WIN'")
        wins = cursor.fetchone()['wins']
        
        cursor.execute("SELECT COUNT(*) as losses FROM trades WHERE market = 'forex' AND status = 'LOSS'")
        losses = cursor.fetchone()['losses']
        
        cursor.execute("SELECT COUNT(*) as pending FROM trades WHERE market = 'forex' AND status IN ('PENDING', 'RUNNING')")
        pending = cursor.fetchone()['pending']
        
        cursor.execute("SELECT SUM(pnl_usd) as total_pnl FROM trades WHERE market = 'forex' AND status IN ('WIN', 'LOSS')")
        total_pnl = cursor.fetchone()['total_pnl'] or 0
        
        cursor.execute("SELECT AVG(pnl_usd) as avg_pnl FROM trades WHERE market = 'forex' AND status IN ('WIN', 'LOSS')")
        avg_pnl = cursor.fetchone()['avg_pnl'] or 0

        # 2. Recent History
        cursor.execute("SELECT symbol, side, entry_price, exit_price, pnl_usd, status, timestamp FROM trades WHERE market = 'forex' ORDER BY timestamp DESC LIMIT 10")
        recent_trades = cursor.fetchall()

        # 3. Session Stats
        cursor.execute("SELECT session, COUNT(*) as count, SUM(pnl_usd) as pnl FROM trades WHERE market = 'forex' AND status IN ('WIN', 'LOSS') GROUP BY session ORDER BY pnl DESC")
        session_stats = cursor.fetchall()

        print("=== FOREX PERFORMANCE REPORT ===")
        print(f"Total Trades: {total}")
        print(f"Wins: {wins}")
        print(f"Losses: {losses}")
        print(f"Pending: {pending}")
        
        total_closed = wins + losses
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0
        print(f"Win Rate: {win_rate:.2f}%")
        print(f"Total PnL: ${total_pnl:.2f}")
        print(f"Avg PnL: ${avg_pnl:.2f}")
        print("\n=== SESSION PERFORMANCE ===")
        for s in session_stats:
            print(f"Session {s['session']}: {s['count']} trades, PnL: ${s['pnl']:.2f}")
            
        print("\n=== RECENT TRADES ===")
        for t in recent_trades:
            ts = datetime.datetime.fromtimestamp(t['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{ts}] {t['symbol']} {t['side'].upper()}: {t['status']} | PnL: ${t['pnl_usd']:.2f} | Entry: {t['entry_price']} | Exit: {t['exit_price']}")

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error checking performance: {e}")

if __name__ == "__main__":
    check_performance()
