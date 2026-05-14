
"""
ANALISIS CRYPTO NON-BLACKLIST DAN YANG WIN!
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
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary"])
    import psycopg2
    from psycopg2.extras import RealDictCursor

print("="*80)
print("ANALISIS CRYPTO NON-BLACKLIST &amp; YANG WIN!")
print("="*80)

DATABASE_URL = "postgres://postgres.ejqpkdwxkkcwiyfoqsfd:Kh%40iranaja09@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

DATA_PROVEN_BLACKLIST = {
    'LABUSDT', 'BSBUSDT', 'SKYAIUSDT', 'RAVEUSDT', 'ORCAUSDT',
    'ERAUSDT', 'NOMUSDT', 'SNDKUSDT', 'USUALUSDT', 'SIRENUSDT',
    'CHIPUSDT', 'PARTIUSDT', 'JCTUSDT', 'LUNCUSDT', 'CRCLUSDT',
    'CARVUSDT', 'UBUSDT', 'INTCUSDT', 'PROSUSDT', 'NEIROCTOUSDT',
    'SAHARAUSDT'
}

def connect_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("\n[OK] Berhasil konek ke database!")
        return conn
    except Exception as e:
        print(f"\n[ERROR] Gagal konek ke database: {e}")
        return None

def main():
    conn = connect_db()
    if not conn:
        return
    
    # Ambil semua crypto trades
    query = "SELECT * FROM trades WHERE market = 'crypto' ORDER BY timestamp DESC"
    df = pd.read_sql(query, conn)
    
    if df.empty:
        print("\n[WARNING] Tidak ada data!")
        conn.close()
        return
    
    print(f"\nTotal Crypto Trades: {len(df)}")
    
    # Filter non-blacklist
    df['clean_symbol'] = df['symbol'].str.replace('USDT', '').str.strip()
    df['is_blacklist'] = df['symbol'].isin(DATA_PROVEN_BLACKLIST) | df['clean_symbol'].isin(DATA_PROVEN_BLACKLIST)
    
    df_good = df[~df['is_blacklist']].copy()
    df_bad = df[df['is_blacklist']].copy()
    
    print(f"\nTrades di Blacklist: {len(df_bad)}")
    print(f"Trades Non-Blacklist: {len(df_good)}")
    
    # Analisis WIN trades
    if 'status' in df_good.columns:
        df_win = df_good[df_good['status'] == 'WIN'].copy()
        print(f"\nWIN Trades Non-Blacklist: {len(df_win)}")
        
        if len(df_win) &gt; 0:
            print(f"\nSYMBOL YANG PERNAH WIN (Non-Blacklist):")
            print(df_win['symbol'].value_counts())
    
    # Analisis status
    print(f"\nStatus Distribution Non-Blacklist:")
    print(df_good['status'].value_counts())
    
    # 10 Trades Non-Blacklist Terakhir
    print(f"\n" + "="*80)
    print("10 CRYPTO NON-BLACKLIST TERAKHIR:")
    print("="*80)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    print(df_good.head(10))
    
    # Rekomendasi
    print(f"\n" + "="*80)
    print("REKOMENDASI:")
    print("="*80)
    print("1. PASTIKAN SELL_TRADING_ENABLED = False di crypto_engine.py")
    print("2. FOKUS ke koin yang pernah WIN (ZECUSDT, BTCUSDT, XRPUSDT, dll)")
    print("3. Pastikan database mencatat PnL dengan benar!")
    print("4. Hindari trading di koin blacklist!")
    
    conn.close()
    print("\n[OK] Analisis selesai!")

if __name__ == "__main__":
    main()
