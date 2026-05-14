
"""
SCRIPT EVALUASI DATABASE & RIWAYAT TRANSAKSI BOT CRYPTO
"""

import os
import sys
import time
import pandas as pd
import numpy as np

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("Installing psycopg2-binary...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary"])
    import psycopg2
    from psycopg2.extras import RealDictCursor

print("="*80)
print("EVALUASI DATABASE CRYPTO BOT")
print("="*80)

# Database URL dari kamu
DATABASE_URL = "postgres://postgres.ejqpkdwxkkcwiyfoqsfd:Kh%40iranaja09@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

def connect_db():
    """Konek ke database"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("\n[OK] Berhasil konek ke database!")
        return conn
    except Exception as e:
        print(f"\n[ERROR] Gagal konek ke database: {e}")
        return None

def get_tables(conn):
    """Dapatkan semua tabel di database"""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = [row[0] for row in cursor.fetchall()]
        print(f"\n[TABEL] Tabel di database: {tables}")
        return tables
    except Exception as e:
        print(f"[ERROR] Gagal dapatkan tabel: {e}")
        return []

def get_trades(conn, table_name="trades"):
    """Dapatkan semua riwayat trade"""
    try:
        query = f"SELECT * FROM {table_name} ORDER BY timestamp DESC"
        df = pd.read_sql(query, conn)
        print(f"\n[OK] Ditemukan {len(df)} trades di tabel {table_name}!")
        return df
    except Exception as e:
        print(f"[ERROR] Gagal dapatkan trades: {e}")
        return pd.DataFrame()

def analyze_trades(df):
    """Analisis detail riwayat trade"""
    if df.empty:
        print("\n[WARNING] Tidak ada data trade untuk dianalisis!")
        return
    
    print("\n" + "="*80)
    print("ANALISIS DETAIL TRADE")
    print("="*80)
    
    print(f"\nTotal Trades: {len(df)}")
    
    # Cek kolom yang tersedia
    print(f"\nKolom di tabel: {df.columns.tolist()}")
    
    # Hitung win rate jika ada kolom pnl
    if 'pnl_usd' in df.columns:
        winning = df[df['pnl_usd'] > 0]
        losing = df[df['pnl_usd'] <= 0]
        
        print(f"\nWinning Trades: {len(winning)}")
        print(f"Losing Trades: {len(losing)}")
        
        if len(df) > 0:
            wr = len(winning) / len(df) * 100
            print(f"Win Rate: {wr:.1f}%")
        
        total_pnl = df['pnl_usd'].sum()
        print(f"Total PnL: ${total_pnl:.2f}")
        
        if len(winning) > 0:
            avg_win = winning['pnl_usd'].mean()
            print(f"Avg Win: ${avg_win:.2f}")
        
        if len(losing) > 0:
            avg_loss = losing['pnl_usd'].mean()
            print(f"Avg Loss: ${avg_loss:.2f}")
    
    # Trades per symbol
    if 'symbol' in df.columns:
        print(f"\nTop 10 Symbols:")
        print(df['symbol'].value_counts().head(10))
    
    # Trades per day
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['date'] = df['timestamp'].dt.date
        
        trades_per_day = df.groupby('date').size()
        print(f"\nTrades per Day:")
        print(trades_per_day)
        
        if len(trades_per_day) > 0:
            print(f"Avg Trades/Day: {trades_per_day.mean():.1f}")
            print(f"Max Trades/Day: {trades_per_day.max()}")
    
    # 10 Trade Terakhir
    print(f"\n" + "="*80)
    print("10 TRADE TERAKHIR:")
    print("="*80)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    print(df.head(10))
    
    # Rekomendasi
    print(f"\n" + "="*80)
    print("REKOMENDASI:")
    print("="*80)
    
    if len(df) > 0:
        if 'pnl_usd' in df.columns:
            wr = len(df[df['pnl_usd'] > 0]) / len(df) * 100
            if wr < 50:
                print("[WARNING] Win Rate di bawah 50%! Pertimbangkan untuk:")
                print("   - Meningkatkan min_score filter")
                print("   - Menambah konfirmasi sinyal")
                print("   - Mengurangi frekuensi trading")
            elif wr > 70:
                print("[OK] Win Rate sangat bagus! Pertimbangkan untuk:")
                print("   - Meningkatkan MAX_POSITIONS")
                print("   - Menurunkan min_score untuk lebih banyak trade")
                print("   - Meningkatkan margin per trade (jika berani)")
            else:
                print("[OK] Win Rate normal! Lanjutkan saja, monitor secara berkala.")

def main():
    conn = connect_db()
    if not conn:
        return
    
    tables = get_tables(conn)
    
    # Coba cari tabel trades
    trade_tables = [t for t in tables if 'trade' in t.lower()]
    
    if trade_tables:
        for table in trade_tables:
            df = get_trades(conn, table)
            if not df.empty:
                analyze_trades(df)
    else:
        print("\n[WARNING] Tidak ada tabel dengan nama 'trade'! Coba semua tabel:")
        for table in tables:
            print(f"\n--- Tabel: {table} ---")
            try:
                cursor = conn.cursor()
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"Jumlah baris: {count}")
                
                if count > 0:
                    cursor.execute(f"SELECT * FROM {table} LIMIT 5")
                    rows = cursor.fetchall()
                    col_names = [desc[0] for desc in cursor.description]
                    print(f"Kolom: {col_names}")
                    print("5 baris pertama:")
                    for row in rows:
                        print(row)
            except Exception as e:
                print(f"Error: {e}")
    
    conn.close()
    print("\n[OK] Evaluasi selesai!")

if __name__ == "__main__":
    main()
