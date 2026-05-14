import ccxt
import os
from dotenv import load_dotenv

def deep_balance_audit():
    load_dotenv()
    api_key = os.getenv("BITGET_API_KEY")
    secret = os.getenv("BITGET_SECRET_KEY")
    passphrase = os.getenv("BITGET_PASSPHRASE")

    print("\n" + "="*60)
    print("BITGET DEEP BALANCE AUDIT")
    print("="*60)

    exchange = ccxt.bitget({
        'apiKey': api_key,
        'secret': secret,
        'password': passphrase,
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'}
    })

    # 1. TEST SPOT WALLET
    print("\n[1] MENGECEK DOMPET SPOT...")
    try:
        spot_bal = exchange.fetch_balance({'type': 'spot'})
        usdt_spot = spot_bal.get('USDT', {}).get('total', 0)
        print(f"    Saldo USDT di SPOT: ${usdt_spot}")
    except Exception as e:
        print(f"    [ERROR] Gagal akses SPOT: {e}")

    # 2. TEST USDT-M FUTURES (SWAP)
    print("\n[2] MENGECEK DOMPET USDT-M FUTURES (Ini laci bot)...")
    try:
        swap_bal = exchange.fetch_balance({'type': 'swap'})
        usdt_swap = swap_bal.get('USDT', {}).get('total', 0)
        print(f"    Saldo USDT di FUTURES: ${usdt_swap}")
        if usdt_swap == 0:
            print("    --> PERHATIAN: Saldo Futures KOSONG. Bot tidak bisa jalan.")
    except Exception as e:
        print(f"    [ERROR] Gagal akses FUTURES: {e}")

    # 3. TEST API PERMISSIONS
    print("\n[3] MENGECEK IZIN API KEY...")
    try:
        # Mencoba ambil posisi (hanya butuh izin Read)
        exchange.fetch_positions()
        print("    Izin Baca (Read): OK")
    except Exception as e:
        print(f"    [CRITICAL] Izin Baca GAGAL: {e}")
        print("    --> Cek apakah API Key Bos sudah dicentang 'Futures' & 'Read'.")

    print("\n" + "="*60)
    print("KESIMPULAN:")
    if usdt_spot > 0 and usdt_swap == 0:
        print(f"SALDO BOS ADA DI SPOT (${usdt_spot}).")
        print("SILAHKAN PINDAHKAN (TRANSFER) KE 'USDT-M FUTURES' AGAR BOT BISA JALAN.")
    elif usdt_swap > 0:
        print("SALDO SUDAH DI TEMPAT YANG BENAR. BOT SIAP GAS!")
    else:
        print("SALDO TIDAK DITEMUKAN DI MANA-PUN. CEK BITGET BOS!")
    print("="*60 + "\n")

if __name__ == "__main__":
    deep_balance_audit()
