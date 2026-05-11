import ccxt
import os
import json
from dotenv import load_dotenv

load_dotenv('backend/.env')

def forensic_audit():
    exchange = ccxt.bitget({
        'apiKey': os.getenv('BITGET_API_KEY'),
        'secret': os.getenv('BITGET_SECRET_KEY'),
        'password': os.getenv('BITGET_PASSPHRASE'),
        'options': {'defaultType': 'swap'},
        'enableRateLimit': True
    })
    # Bypass market loading for diagnostic
    exchange.markets = {} 
    
    print("="*60)
    print("BITGET FORENSIC AUDIT - TRADE HISTORY")
    print("="*60)
    
    try:
        # 1. Cek Posisi Aktif Saat Ini
        pos = exchange.fetch_positions(params={'productType': 'usdt-futures'})
        active = [p for p in pos if float(p.get('contracts', 0) or 0) > 0]
        print(f"\n[1] POSISI AKTIF SAAT INI ({len(active)}):")
        for p in active:
            print(f"    - {p['symbol']} | Side: {p['side']} | Size: {p['contracts']} | Entry: {p['entryPrice']}")

        # 2. Tarik Riwayat Order Terakhir (Fakta Eksekusi)
        print("\n[2] 10 ORDER TERAKHIR (CLOSED/FILLED):")
        orders = exchange.fetch_orders(params={'productType': 'usdt-futures'}, limit=10)
        for o in orders:
            # Cari tahu siapa yang buka order ini dari 'comment'
            info = o.get('info', {})
            comment = info.get('orderComment', 'NO_COMMENT')
            print(f"    - [{o['datetime']}] {o['symbol']} {o['side']} {o['status']} | Vol: {o['amount']} | Comment: {comment} | ID: {o['id']}")

        # 3. Cek Saldo Detail
        bal = exchange.fetch_balance(params={'productType': 'usdt-futures'})
        print(f"\n[3] AUDIT SALDO:")
        print(f"    - Total Equity: {bal['info'].get('equity', 'N/A')} USDT")
        print(f"    - Available: {bal['free'].get('USDT', 0)} USDT")
        print(f"    - Margin Used: {float(bal['info'].get('equity', 0)) - float(bal['free'].get('USDT', 0)) if bal['info'].get('equity') else 'N/A'} USDT")

    except Exception as e:
        print(f"\n[ERROR] Audit Gagal: {e}")

if __name__ == "__main__":
    forensic_audit()
