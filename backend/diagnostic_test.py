import os
import time
from dotenv import load_dotenv

# Paksa load .env
load_dotenv()

from bitget_executor import BitgetExecutor
from crypto_engine import _determine_trade_side, _calc_tp_sl

print("\n" + "="*80)
print("DIAGNOSTIC TEST: SANG JUARA (v39.0)")
print("Mengecek Koneksi API & Simulasi Sinyal Tembak")
print("="*80 + "\n")

def run_diagnostics():
    # 1. TEST KONEKSI BITGET
    print("[1] MENGHUBUNGI SATELIT BITGET...")
    try:
        executor = BitgetExecutor()
        bal_dict = executor.get_balance()
        balance = float(bal_dict.get('free', 0))
        print(f"    -> BERHASIL! Koneksi API Bitget Tersambung.")
        print(f"    -> Saldo USDT Tersedia: ${balance:.2f}")
    except Exception as e:
        print(f"    -> GAGAL! Ada masalah dengan API Bitget: {e}")
        return

    # 2. TEST LOGIKA MESIN JUARA (v39.0)
    print("\n[2] MENSIMULASIKAN KONDISI PASAR GILA (MEMANCING SNIPER)...")
    
    # Fake Market Data (Kondisi Kiamat: RSI Tinggi, Volume Meledak)
    fake_tech = {
        'symbol': 'BTCUSDT',
        'rvol': 3.5, # Volume 3.5x lipat
        'atr': 500.0,
        'limit_price': 60000.0
    }
    
    fake_rsi = 72.5
    fake_vwap_dist = 1.0
    fake_market_sentiment = "BULLISH"
    fake_mark_price = 60000.0
    fake_pump_sc = 90.0
    fake_dump_sc = 10.0
    
    print(f"    -> Menyuntikkan Data Palsu: RSI {fake_rsi} | RVOL {fake_tech['rvol']} | ATR {fake_tech['atr']}")
    
    side, reason, score = _determine_trade_side(
        fake_tech, fake_rsi, fake_vwap_dist, fake_market_sentiment, 
        fake_mark_price, fake_pump_sc, fake_dump_sc
    )
    
    if side == "buy" and score == 100:
        print(f"    -> MESIN BEREAKSI NORMAL! Keputusan: {side.upper()} | Skor: {score} | Alasan: {reason}")
    else:
        print(f"    -> GAGAL! Mesin tidak bereaksi. Keputusan: {side} | Alasan: {reason}")
        return
        
    # 3. TEST KALKULASI LIMIT ORDER (TP 4%, SL 5%)
    print("\n[3] MENSIMULASIKAN PEMASANGAN RANJAU (TP & SL)...")
    tp_price, sl_price = _calc_tp_sl(fake_mark_price, side, fake_tech)
    
    tp_pct_actual = ((tp_price - fake_mark_price) / fake_mark_price) * 100
    sl_pct_actual = ((fake_mark_price - sl_price) / fake_mark_price) * 100
    
    print(f"    -> Entry Price : ${fake_mark_price:,.2f}")
    print(f"    -> Take Profit : ${tp_price:,.2f} (+{tp_pct_actual:.1f}% Harga / +{tp_pct_actual*10:.0f}% PnL)")
    print(f"    -> Stop Loss   : ${sl_price:,.2f} (-{sl_pct_actual:.1f}% Harga / -{sl_pct_actual*10:.0f}% PnL)")
    
    if round(tp_pct_actual, 1) == 4.0 and round(sl_pct_actual, 1) == 5.0:
        print("    -> KALKULASI LIMIT SEMPURNA! Sesuai Settingan Juara 1.")
    else:
        print("    -> GAGAL! Kalkulasi Limit Meleset dari Settingan Juara 1.")
        return
        
    print("\n" + "="*80)
    print("ALL SYSTEMS GO! 🟢 BOT SIAP MENEMBAK KAPAN SAJA MARKET MELEDAK!")
    print("="*80 + "\n")

if __name__ == "__main__":
    run_diagnostics()
