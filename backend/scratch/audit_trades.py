# -*- coding: utf-8 -*-
import os, sys
from dotenv import load_dotenv
from supabase import create_client

# Load ENV
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

def audit_recent_trades():
    if not url or not key:
        print("Error: Supabase credentials not found.")
        return

    supabase = create_client(url, key)
    
    print("="*80)
    print("AUDIT TRANSAKSI CRYPTO (12 JAM TERAKHIR)")
    print("="*80)
    
    try:
        # Ambil trade dari tabel 'trades' atau 'logs'
        # Kita asumsikan tabelnya bernama 'trades' sesuai log_trade
        response = supabase.table('trades').select('*').order('created_at', desc=True).limit(20).execute()
        trades = response.data
        
        if not trades:
            print("Tidak ada transaksi ditemukan di database.")
            return

        wins = 0
        losses = 0
        total_pnl = 0
        
        for t in trades:
            sym = t.get('symbol', 'N/A')
            side = t.get('side', 'N/A')
            price = t.get('price', 0)
            tp = t.get('tp', 0)
            sl = t.get('sl', 0)
            time_str = t.get('created_at', 'N/A')
            
            # Analisis sederhana: Jika harga penutupan (nanti) > price untuk BUY, maka Win
            # Tapi di database biasanya kita simpan entry. 
            # Saya akan tampilkan daftar trade-nya dulu.
            print(f"[{time_str}] {sym:<12} | {side.upper():<4} | Price: {price:<10} | TP: {tp:<10} | SL: {sl}")

    except Exception as e:
        print(f"Error accessing database: {e}")

if __name__=="__main__":
    audit_recent_trades()
