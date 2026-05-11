import sys
import os
import time

sys.path.append(os.path.join(os.getcwd(), "backend"))
from bitget_executor import BitgetExecutor

def audit_bot_brain():
    executor = BitgetExecutor()
    print("="*60)
    print("BOT BRAIN AUDIT - REAL TIME STATE")
    print("="*60)
    
    positions = executor.get_all_positions()
    if not positions:
        print("Tidak ada posisi aktif.")
        return

    for p in positions:
        sym = p['symbol']
        ent = p['entry']
        mrk = p['mark_price']
        lev = p['leverage']
        pnl = p['pnl']
        
        print(f"\n[ASSET: {sym}]")
        print(f"  Entry: {ent}")
        print(f"  Mark : {mrk}")
        print(f"  Lev  : {lev}x")
        print(f"  PnL  : {pnl}%")
        
        # Simulasi hitungan Trailing
        if pnl >= 10:
            locked = float(int(pnl / 5) * 5 - 5)
            target_sl = ent * (1 + (locked / 100.0) / lev) if p['side'] == 'long' else ent * (1 - (locked / 100.0) / lev)
            print(f"  ==> TARGET TRAILING SL: {target_sl} (Locked {locked}%)")
            
            # Cek SL saat ini di bursa
            plans = executor.get_pending_plan_orders(sym)
            current_sl = 0
            for pl in plans:
                if 'loss' in pl['type'] or 'sl' in pl['type']:
                    current_sl = pl['price']
            print(f"  ==> CURRENT SL ON EXCHANGE: {current_sl}")
            
            if target_sl > current_sl and current_sl > 0:
                print(f"  ==> STATUS: BOT HARUSNYA UPDATE SEKARANG!")
            elif current_sl == 0:
                print(f"  ==> STATUS: SL TIDAK TERDETEKSI DI BURSA!")
            else:
                print(f"  ==> STATUS: SL SUDAH OPTIMAL ATAU LEBIH TINGGI.")

if __name__ == "__main__":
    audit_bot_brain()
