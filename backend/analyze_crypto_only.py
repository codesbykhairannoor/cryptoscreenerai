
"""
SCRIPT ANALISIS PERFORMA CRYPTO SAJA!
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
print("ANALISIS PERFORMA CRYPTO SAJA")
print("="*80)

DATABASE_URL = "postgres://postgres.ejqpkdwxkkcwiyfoqsfd:Kh%40iranaja09@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

def connect_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("\n[OK] Berhasil konek ke database!")
        return conn
    except Exception as e:
        print(f"\n[ERROR] Gagal konek ke database: {e}")
        return None

def get_crypto_trades(conn):
    try:
        query = "SELECT * FROM trades WHERE market = 'crypto' ORDER BY timestamp DESC"
        df = pd.read_sql(query, conn)
        print(f"\n[OK] Ditemukan {len(df)} crypto trades!")
        return df
    except Exception as e:
        print(f"[ERROR] Gagal dapatkan crypto trades: {e}")
        return pd.DataFrame()

def analyze_crypto(df):
    if df.empty:
        print("\n[WARNING] Tidak ada data crypto trade!")
        return
    
    print("\n" + "="*80)
    print("ANALISIS DETAIL PERFORMA CRYPTO")
    print("="*80)
    
    print(f"\nTotal Crypto Trades: {len(df)}")
    
    if 'pnl_usd' in df.columns:
        winning = df[df['pnl_usd'] > 0]
        losing = df[df['pnl_usd'] <= 0]
        
        print(f"\nWinning Trades: {len(winning)}")
        print(f"Losing Trades: {len(losing)}")
        
        if len(df) > 0:
            wr = len(winning) / len(df) * 100
            print(f"Win Rate Crypto: {wr:.1f}%")
        
        total_pnl = df['pnl_usd'].sum()
        print(f"Total PnL Crypto: ${total_pnl:.2f}")
        
        if len(winning) > 0:
            avg_win = winning['pnl_usd'].mean()
            print(f"Avg Win Crypto: ${avg_win:.2f}")
        
        if len(losing) > 0:
            avg_loss = losing['pnl_usd'].mean()
            print(f"Avg Loss Crypto: ${avg_loss:.2f}")
    
    if 'symbol' in df.columns:
        print(f"\nTop 10 Crypto Symbols:")
        print(df['symbol'].value_counts().head(10))
    
    if 'status' in df.columns:
        print(f"\nStatus Distribution:")
        print(df['status'].value_counts())
    
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['date'] = df['timestamp'].dt.date
        
        trades_per_day = df.groupby('date').size()
        print(f"\nCrypto Trades per Day:")
        print(trades_per_day)
        
        if len(trades_per_day) > 0:
            print(f"Avg Crypto Trades/Day: {trades_per_day.mean():.1f}")
            print(f"Max Crypto Trades/Day: {trades_per_day.max()}")
    
    print(f"\n" + "="*80)
    print("10 CRYPTO TRADE TERAKHIR:")
    print("="*80)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    print(df.head(10))
    
    print(f"\n" + "="*80)
    print("REKOMENDASI UNTUK CRYPTO:")
    print("="*80)
    
    if len(df) > 0:
        if 'pnl_usd' in df.columns:
            wr = len(df[df['pnl_usd'] > 0]) / len(df) * 100
            if wr < 50:
                print("[WARNING] Win Rate crypto di bawah 50%!")
                print("   - Periksa kembali filter score")
                print("   - Kurangi frekuensi trading crypto")
                print("   - Fokus ke koin yang terbukti profit")
            elif wr > 70:
                print("[OK] Win Rate crypto sangat bagus!")
                print("   - Bisa meningkatkan MAX_POSITIONS crypto")
                print("   - Bisa menurunkan min_score crypto")
                print("   - Pertimbangkan meningkatkan margin per trade crypto")
            else:
                print("[OK] Win Rate crypto normal! Lanjutkan saja.")

def main():
    conn = connect_db()
    if not conn:
        return
    
    df_crypto = get_crypto_trades(conn)
    
    if not df_crypto.empty:
        analyze_crypto(df_crypto)
    
    conn.close()
    print("\n[OK] Analisis crypto selesai!")

if __name__ == "__main__":
    main()



