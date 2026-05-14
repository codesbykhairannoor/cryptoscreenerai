
import psycopg2
import pandas as pd

print("="*80)
print("CEK DATABASE CRYPTO SAJA")
print("="*80)

DATABASE_URL = "postgres://postgres.ejqpkdwxkkcwiyfoqsfd:Kh%40iranaja09@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

DATA_PROVEN_BLACKLIST = [
    'LABUSDT', 'BSBUSDT', 'SKYAIUSDT', 'RAVEUSDT', 'ORCAUSDT',
    'ERAUSDT', 'NOMUSDT', 'SNDKUSDT', 'USUALUSDT', 'SIRENUSDT',
    'CHIPUSDT', 'PARTIUSDT', 'JCTUSDT', 'LUNCUSDT', 'CRCLUSDT',
    'CARVUSDT', 'UBUSDT', 'INTCUSDT', 'PROSUSDT', 'NEIROCTOUSDT',
    'SAHARAUSDT'
]

def main():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("\n[OK] Konek database sukses!")
        
        # Ambil crypto trades
        query = "SELECT * FROM trades WHERE market = 'crypto' ORDER BY timestamp DESC"
        df = pd.read_sql(query, conn)
        print(f"\nTotal Crypto Trades: {len(df)}")
        
        # Hitung WIN trades
        if 'status' in df.columns:
            df_win = df[df['status'] == 'WIN']
            print(f"WIN Trades: {len(df_win)}")
        
        # Filter non-blacklist
        df['is_blacklist'] = df['symbol'].isin(DATA_PROVEN_BLACKLIST)
        df_good = df[~df['is_blacklist']]
        print(f"\nTrades Non-Blacklist: {len(df_good)}")
        
        if len(df_good) > 0:
            print("\nSymbol Non-Blacklist:")
            print(df_good['symbol'].value_counts())
            
            if 'status' in df_good.columns:
                df_good_win = df_good[df_good['status'] == 'WIN']
                print(f"\nWIN Non-Blacklist: {len(df_good_win)}")
                if len(df_good_win) > 0:
                    print("\nSymbol yang WIN (Non-Blacklist):")
                    print(df_good_win['symbol'].value_counts())
        
        print("\n10 Trade Terakhir:")
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 200)
        print(df_good.head(10))
        
        conn.close()
        print("\n[OK] Selesai!")
        
    except Exception as e:
        print(f"\n[ERROR] {e}")

if __name__ == "__main__":
    main()
