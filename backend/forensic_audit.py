import psycopg2

db_url = "postgres://postgres.ejqpkdwxkkcwiyfoqsfd:Kh%40iranaja09@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

def forensic_loss_audit():
    print("="*120)
    print("FORENSIC LOSS AUDIT - MENCARI PENYEBAB 10 TRADE TERAKHIR LOSE")
    print("="*120)
    
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        # Tarik 15 transaksi terakhir untuk melihat pola kekalahan
        query = """
            SELECT id, symbol, side, entry_price, exit_price, sl_price, tp_price, pnl_pct, reason, status, timestamp 
            FROM trades 
            ORDER BY timestamp DESC 
            LIMIT 15
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if not rows:
            print("[-] Tidak ada data transaksi.")
            return

        print(f"{'ID':<4} | {'SYMBOL':<12} | {'SIDE':<5} | {'ENTRY':<10} | {'SL':<10} | {'EXIT':<10} | {'PNL%':<8} | {'STATUS':<6} | {'REASON'}")
        print("-" * 120)
        
        lose_count = 0
        for r in rows:
            rid, symbol, side, entry, exit_p, sl, tp, pnl, reason, status, ts = r
            pnl_str = f"{pnl:+.2f}%" if pnl is not None else "0.00%"
            
            # Tandai yang rugi parah
            alert = " [!] GHOST_LOSS" if (pnl is not None and pnl < -10) else ""
            
            print(f"{rid:<4} | {symbol:<12} | {side:<5} | {entry:<10} | {sl:<10} | {exit_p:<10} | {pnl_str:<8} | {status:<6} | {reason}{alert}")
            
            if status == "LOSS": lose_count += 1

        print("-" * 120)
        print(f"[*] Total LOSS di scan terakhir: {lose_count}/15")
        
        # ANALISIS POLA
        print("\n[ANALISIS AWAL SAYA]:")
        # Kita cek apakah ada koin yang sama berulang kali
        symbols = [r[1] for r in rows]
        most_common = max(set(symbols), key=symbols.count)
        if symbols.count(most_common) > 2:
            print(f"⚠️  DETEKSI OVER-TRADING: Koin {most_common} di-trade {symbols.count(most_common)} kali dalam waktu singkat!")
            
        # Cek apakah PnL jauh lebih besar dari SL
        for r in rows:
            if r[7] is not None and r[7] < -5: # Rugi > 5%
                print(f"⚠️  SL FAILURE: ID {r[0]} ({r[1]}) rugi {r[7]:.2f}%. SL harusnya di {r[5]}. Ada indikasi Slippage atau SL tidak terpasang di Bitget!")

        conn.close()
    except Exception as e:
        print(f"[ERR] Audit Gagal: {e}")

if __name__ == "__main__":
    forensic_loss_audit()
