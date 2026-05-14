
import os
import psycopg2
import pandas as pd
from datetime import datetime, timedelta

print("="*80)
print("ANALISIS DATABASE CRYPTO BOT")
print("="*80)

# Database URL dari kamu
DATABASE_URL = "postgres://postgres.ejqpkdwxkkcwiyfoqsfd:Kh%40iranaja09@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

def connect_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("[OK] Berhasil konek ke database!")
        return conn
    except Exception as e:
        print(f"[ERROR] Gagal konek: {e}")
        return None

def get_trades(conn):
    try:
        query = "SELECT * FROM trades ORDER BY timestamp DESC LIMIT 100"
        df = pd.read_sql(query, conn)
        print(f"\n[OK] Ditemukan {len(df)} trades di database!")
        return df
    except Exception as e:
        print(f"[ERROR] Gagal ambil trades: {e}")
        return pd.DataFrame()

def analyze_trades(df):
    if df.empty:
        print("\nTidak ada data trades untuk dianalisis!")
        return
    
    print("\n" + "="*80)
    print("ANALISIS TRADE HISTORY")
    print("="*80)
    
    print(f"\nTotal Trades: {len(df)}")
    
    if 'pnl_usd' in df.columns:
        winning = df[df['pnl_usd'] > 0]
        losing = df[df['pnl_usd'] <= 0]
        
        print(f"Winning Trades: {len(winning)}")
        print(f"Losing Trades: {len(losing)}")
        
        if len(df) > 0:
            wr = len(winning) / len(df) * 100
            print(f"Win Rate: {wr:.1f}%")
        
        total_pnl = df['pnl_usd'].sum()
        print(f"Total PnL: ${total_pnl:.2f}")
        
        avg_win = winning['pnl_usd'].mean() if len(winning) > 0 else 0
        avg_loss = losing['pnl_usd'].mean() if len(losing) > 0 else 0
        print(f"Avg Win: ${avg_win:.2f}")
        print(f"Avg Loss: ${avg_loss:.2f}")
    
    if 'symbol' in df.columns:
        print(f"\nTrades per Symbol:")
        print(df['symbol'].value_counts().head(10))
    
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        if len(df) >= 2:
            start = df['timestamp'].min()
            end = df['timestamp'].max()
            days = (end - start).total_seconds() / (24 * 3600)
            if days > 0:
                tpd = len(df) / days
                print(f"\nTrades per Day: {tpd:.1f}")
    
    print("\n" + "="*80)
    print("5 TRADE TERAKHIR:")
    print("="*80)
    print(df.head())

def main():
    conn = connect_db()
    if not conn:
        return
    
    df_trades = get_trades(conn)
    
    if not df_trades.empty:
        analyze_trades(df_trades)
    
    # Coba lihat semua tabel
    try:
        query = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        tables = pd.read_sql(query, conn)
        print(f"\nTabel di database: {tables['table_name'].tolist()}")
    except Exception as e:
        print(f"[ERROR] Gagal lihat tabel: {e}")
    
    conn.close()

if __name__ == "__main__":
    main()
