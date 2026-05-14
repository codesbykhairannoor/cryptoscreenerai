import time
import pandas as pd
from bitget_executor import BitgetExecutor
from crypto_engine import get_technical_indicators, _determine_trade_side, fetch_all_tickers, analyze_and_sort

# --- LIVE DIAGNOSTIC v31.6: MOMENTUM & CONNECTION TEST ---

def run_live_test():
    print("\n" + "="*80)
    print("LIVE DIAGNOSTIC v31.6: INSTITUTIONAL PREDATOR ENGINE")
    print("="*80)
    
    executor = BitgetExecutor()
    print(f"\n[1] KONEKSI BITGET: OK")
    
    try:
        bal = executor.get_balance()
        print(f"    Saldo USDT: ${bal['total']} (Free: ${bal['free']})")
    except Exception as e:
        print(f"    [ERROR] Gagal ambil saldo: {e}")
        return

    print("\n[2] SCANNING TOP 15 HOT COINS...")
    raw_data = fetch_all_tickers()
    candidates = analyze_and_sort(raw_data)
    top_15 = candidates[:15]
    
    results = []
    print(f"\n[3] EVALUASI LOGIKA ENTRY (v31.6)...")
    print(f"{'SYMBOL':<12} | {'AI_BIAS':<8} | {'SCORE':<5} | {'RVOL':<5} | {'DECISION'}")
    print("-" * 80)
    
    for coin in top_15:
        symbol = coin['symbol']
        clean_base = symbol.replace('USDT', '')
        
        # Ambil tech data
        tech = get_technical_indicators(symbol)
        if not tech:
            print(f"{symbol:<12} | ERROR FETCHING TECH")
            continue
            
        rsi = tech.get('rsi', 50)
        vwap_dist = tech.get('vwap_dist', 0)
        pump_sc = float(coin.get('pump_score', 0))
        dump_sc = float(coin.get('dump_score', 0))
        rvol = tech.get('rvol', 1.0)
        
        side, reason, score = _determine_trade_side(tech, rsi, vwap_dist, "NEUTRAL", 0, pump_sc, dump_sc)
        
        ai_bias = "PUMP" if pump_sc >= dump_sc else "DUMP"
        decision = f"READY TO {side.upper()}" if side else f"SKIP: {reason}"
        
        print(f"{symbol:<12} | {ai_bias:<8} | {score:<5} | {rvol:<5.1f} | {decision}")
        
        if side:
            results.append((symbol, side, score, reason))

    print("\n" + "="*80)
    if results:
        print(f"HASIL: Ditemukan {len(results)} koin yang SIAP TEMBAK!")
        for r in results:
            print(f" >> {r[0]} ({r[1].upper()}) - Skor: {r[2]} - Alasan: {r[3]}")
    else:
        print("HASIL: Market sedang Ranging. Belum ada koin yang menembus skor 60.")
    print("="*80 + "\n")

if __name__ == "__main__":
    run_live_test()



