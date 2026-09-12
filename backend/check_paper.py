import sqlite3
import os
import time
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

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
        cursor.execute("""SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN status='LOSS' THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN status='NEUTRAL' THEN 1 ELSE 0 END) as neutrals,
            SUM(CASE WHEN status='WIN' THEN pnl_usd ELSE 0 END) as win_pnl,
            SUM(CASE WHEN status='LOSS' THEN pnl_usd ELSE 0 END) as loss_pnl,
            SUM(pnl_usd) as total_pnl
            FROM trades WHERE status IN ('WIN', 'LOSS', 'NEUTRAL') AND is_paper = 1""")
        stats = cursor.fetchone()
        
        total_closed = stats['total'] or 0
        wins = stats['wins'] or 0
        losses = stats['losses'] or 0
        neutrals = stats['neutrals'] or 0
        win_pnl = stats['win_pnl'] or 0.0
        loss_pnl = stats['loss_pnl'] or 0.0
        total_pnl = stats['total_pnl'] or 0.0
        
        # Win Rate dihitung hanya dari WIN vs LOSS (bukan termasuk NEUTRAL)
        decisive = wins + losses
        winrate = (wins / decisive * 100) if decisive > 0 else 0
        
        print(f"\n📈 Statistik Performa (Paper Trading):")
        print(f"   Total Trade Selesai : {total_closed} (WIN:{wins} LOSS:{losses} NEUTRAL:{neutrals})")
        print(f"   Win Rate (W vs L)   : {winrate:.1f}%  [{wins}W / {losses}L] (Sideways Timeout tidak dihitung)")
        print(f"   Total PnL WIN       : ${win_pnl:.2f}")
        print(f"   Total PnL LOSS      : ${loss_pnl:.2f}")
        print(f"   Total PnL (Bersih)  : ${total_pnl:.2f}")
    except Exception as e:
        print(f"\n📈 Statistik belum tersedia: {e}")

    # 3. Cek Posisi Berjalan (RUNNING)
    try:
        cursor.execute("SELECT symbol, side, entry_price, sl_price, tp_price, pnl_pct, pnl_usd, so_count, total_cost, lot_size FROM trades WHERE status IN ('PENDING', 'RUNNING') AND is_paper = 1")
        running = cursor.fetchall()
        
        print(f"\n🟢 Posisi Aktif Berjalan: {len(running)}")
        for r in running:
            sym = r['symbol']
            side = r['side'].upper()
            ent = r['entry_price']
            pnl_pct = r['pnl_pct'] or 0
            sl = r['sl_price']
            tp = r['tp_price']
            keys = r.keys() if hasattr(r, 'keys') else []
            so = r['so_count'] if 'so_count' in keys and r['so_count'] is not None else 0
            lot = r['lot_size'] or 0
            cost = r['total_cost'] if ('total_cost' in keys and r['total_cost'] is not None and r['total_cost'] > 0) else (lot * ent if ent else 0)
            print(f"   => {side} {sym:<10} | Avg Entry: {ent:.6f} | TP: {tp:.6f} | SL: {sl:.6f} | SO: {so}/2 | Margin: ${cost:.2f} | PnL: {pnl_pct:+.2f}%")
    except Exception as e:
        pass

    # 4. Cek History Terbaru (Bisa semua jika ada argumen --all)
    try:
        limit_query = "LIMIT 50"
        if len(sys.argv) > 1 and sys.argv[1] == '--all':
            limit_query = ""
            print(f"\n📜 Riwayat SEMUA Trade:")
        else:
            print(f"\n📜 Riwayat 50 Trade Terakhir (Gunakan 'python check_paper.py --all' untuk melihat semua):")
            
        cursor.execute(f"SELECT symbol, side, status, pnl_usd, pnl_pct, reason, closed_at FROM trades WHERE status IN ('WIN', 'LOSS') AND is_paper = 1 ORDER BY id DESC {limit_query}")
        history = cursor.fetchall()
        
        if history:
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
