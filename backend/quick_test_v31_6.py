import time
from bitget_executor import BitgetExecutor
from crypto_engine import get_technical_indicators, _determine_trade_side

def quick_test():
    print("\n" + "="*60)
    print("QUICK TEST v31.6: SINGLE ASSET EVALUATION")
    print("="*60)
    
    executor = BitgetExecutor()
    symbol = "BTCUSDT"
    
    print(f"\n[1] FETCHING TECH DATA FOR {symbol}...")
    tech = get_technical_indicators(symbol)
    if not tech:
        print("    [ERROR] Gagal ambil data teknikal!")
        return
        
    rsi = tech.get('rsi', 50)
    vwap_dist = tech.get('vwap_dist', 0)
    rvol = tech.get('rvol', 1.0)
    
    # Mock pump/dump score dari AI (Simulasi Gainer)
    pump_sc = 85.0
    dump_sc = 20.0
    
    print(f"\n[2] DATA TERDETEKSI:")
    print(f"    RSI: {rsi:.1f} | VWAP: {vwap_dist:+.2f}% | RVOL: {rvol:.1f}")
    print(f"    Trend 1h: {tech.get('trend_1h')} | 4h: {tech.get('trend_4h')}")
    print(f"    Zone: {tech.get('dsz_status')} | Candle: {'Green' if tech.get('is_bullish') else 'Red'}")
    
    print(f"\n[3] EVALUASI LOGIKA SNIPER (v31.6):")
    side, reason, score = _determine_trade_side(tech, rsi, vwap_dist, "NEUTRAL", 0, pump_sc, dump_sc)
    
    if side:
        print(f"    >>> HASIL: SIAP {side.upper()}! Skor: {score} ({reason})")
    else:
        print(f"    >>> HASIL: SKIP ({reason})")
    
    print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    quick_test()



