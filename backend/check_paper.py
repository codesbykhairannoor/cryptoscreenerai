import sqlite3
import os
import time

def check_paper():
    # Gunakan absolute atau relative path ke db
    db_path = "trading_bot.db"
    if not os.path.exists(db_path):
        print(f"[!] Database {db_path} tidak ditemukan.")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("\n" + "="*50)
    print(" 📊 CRYPTOSCREENER AI - PAPER TRADING REPORT 📊")
    print("="*50)

    # 1. Cek Saldo Virtual
    try:
        cursor.execute("SELECT balance FROM virtual_account ORDER BY id ASC LIMIT 1")
        row = cursor.fetchone()
        balance = float(row['balance']) if row else 1000.0
        print(f"\n💰 Virtual Balance Saat Ini: ${balance:.2f}")
    except Exception as e:
        print(f"\n💰 Virtual Balance Saat Ini: $1000.00 (Belum ada perubahan)")

    # 2. Cek Performa Keseluruhan
    try:
        cursor.execute("SELECT COUNT(*) as total, SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins, SUM(CASE WHEN status='LOSS' THEN 1 ELSE 0 END) as losses, SUM(pnl_usd) as total_pnl FROM trades WHERE status IN ('WIN', 'LOSS') AND is_paper = 1")
        stats = cursor.fetchone()
        
        total_closed = stats['total'] or 0
        wins = stats['wins'] or 0
        losses = stats['losses'] or 0
        total_pnl = stats['total_pnl'] or 0.0
        
        winrate = (wins / total_closed * 100) if total_closed > 0 else 0
        
        print(f"\n📈 Statistik Performa (Paper Trading):")
        print(f"   Total Trade Selesai : {total_closed}")
        print(f"   Total Menang (WIN)  : {wins}")
        print(f"   Total Kalah (LOSS)  : {losses}")
        print(f"   Win Rate            : {winrate:.1f}%")
        print(f"   Total PnL (Bersih)  : ${total_pnl:.2f}")
    except Exception as e:
        print(f"\n📈 Statistik belum tersedia.")

    # 3. Cek Posisi Berjalan (RUNNING)
    try:
        cursor.execute("SELECT symbol, side, entry_price, sl_price, tp_price, pnl_pct, pnl_usd FROM trades WHERE status IN ('PENDING', 'RUNNING') AND is_paper = 1")
        running = cursor.fetchall()
        
        print(f"\n🟢 Posisi Aktif Berjalan: {len(running)}")
        for r in running:
            sym = r['symbol']
            side = r['side'].upper()
            ent = r['entry_price']
            pnl_pct = r['pnl_pct'] or 0
            pnl_usd = r['pnl_usd'] or 0
            sl = r['sl_price']
            print(f"   => {side} {sym} | Entry: {ent} | SL Trailing: {sl} | PnL: {pnl_pct:.2f}%")
    except Exception as e:
        pass

    # 4. Cek History Terbaru (Last 5)
    try:
        cursor.execute("SELECT symbol, side, status, pnl_usd, pnl_pct, reason FROM trades WHERE status IN ('WIN', 'LOSS') AND is_paper = 1 ORDER BY id DESC LIMIT 5")
        history = cursor.fetchall()
        
        if history:
            print(f"\n📜 Riwayat 5 Trade Terakhir:")
            for r in history:
                icon = "✅" if r['status'] == "WIN" else "❌"
                print(f"   {icon} {r['side'].upper()} {r['symbol']} | {r['status']} | PnL: {r['pnl_pct']:.2f}% (${r['pnl_usd']:.2f}) | {r['reason']}")
    except Exception as e:
        pass

    print("\n" + "="*50 + "\n")
    cursor.close()
    conn.close()

if __name__ == "__main__":
    check_paper()
