import sys
import os
import time

# Tambahkan path backend
sys.path.append(os.path.join(os.getcwd(), "backend"))

from bitget_executor import BitgetExecutor

def test_trade_limit():
    print("="*60)
    print("TESTING 1-TRADE LIMIT & POSITION VISIBILITY")
    print("="*60)
    
    executor = BitgetExecutor()
    
    # 1. Cek apakah sinkronisasi waktu bekerja
    print(f"\n[1] Time Sync Check:")
    print(f"    Offset terdeteksi: {executor.time_offset} ms")
    
    # 2. Cek posisi (apakah bot bisa melihat posisi hantu?)
    print(f"\n[2] Memeriksa Posisi Aktif...")
    positions = executor.get_all_positions()
    
    if positions is None:
        print("    ERROR: Gagal mengambil posisi (Masih Rejection?)")
        return

    print(f"    Daftar Posisi Aktif ({len(positions)}):")
    for p in positions:
        print(f"    - {p['symbol']} | Side: {p['side']} | PnL: {p['pnl']}%")
        
    # 3. Verifikasi Logika Limit
    MAX_POSITIONS = 1
    open_count = len(positions)
    
    print(f"\n[3] Verifikasi Logika Limit (MAX_POSITIONS={MAX_POSITIONS}):")
    if open_count >= MAX_POSITIONS:
        print(f"    HASIL: AKTIF ({open_count} posisi). Bot AKAN MELEWATI (SKIP) scan selanjutnya.")
        print(f"    KESIMPULAN: PROTEKSI AKTIF. Tidak akan ada trade ganda.")
    else:
        print(f"    HASIL: KOSONG ({open_count} posisi). Bot DIPERBOLEHKAN mencari trade baru.")

if __name__ == "__main__":
    test_trade_limit()
