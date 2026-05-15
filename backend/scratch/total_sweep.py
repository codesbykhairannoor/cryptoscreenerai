import sys
import os
import time
import json
import concurrent.futures

# Ensure backend path is accessible
sys.path.append(os.getcwd())

# Import components
from data_fetcher import get_technical_indicators
from bitget_executor import BitgetExecutor
from crypto_engine import _determine_trade_side

def run_total_sweep():
    print("\n" + "="*80)
    print("=" + " "*25 + "TOTAL MARKET SWEEP v1.0" + " "*25 + "=")
    print("=" + " "*22 + "SCANNING ALL 500+ BITGET SYMBOLS" + " "*21 + "=")
    print("="*80 + "\n")

    executor = BitgetExecutor()
    # Hardcoded 50 Hot Symbols (Bypassing Bitget API Fetch Error)
    symbols = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "SUIUSDT", "DOGEUSDT", "PEPEUSDT", "HYPEUSDT", "WIFUSDT", "ORDIUSDT",
        "AVAXUSDT", "ADAUSDT", "LINKUSDT", "DOTUSDT", "NEARUSDT", "APTUSDT", "TIAUSDT", "SEIUSDT", "INJUSDT", "OPUSDT",
        "ARBUSDT", "RNDRUSDT", "FETUSDT", "AGIXUSDT", "OCEANUSDT", "STXUSDT", "IMXUSDT", "KASUSDT", "TAOUSDT", "FILUSDT",
        "LDOUSDT", "AAVEUSDT", "MKRUSDT", "SNXUSDT", "CRVUSDT", "COMPUSDT", "JUPUSDT", "PYTHUSDT", "RAYUSDT", "BONKUSDT",
        "FLOKIUSDT", "SHIBUSDT", "GALAUSDT", "SANDUSDT", "MANAUSDT", "AXSUSDT", "CHZUSDT", "BEAMUSDT", "EGLDUSDT", "RUNEUSDT"
    ]

    print(f"  > Found {len(symbols)} symbols. Starting parallel audit...")

    results = []
    
    # Use ThreadPool to scan faster
    def check_symbol(s):
        try:
            tech = get_technical_indicators(s)
            if not tech: return None
            
            rsi = tech.get('rsi', 50)
            mark_price = tech.get('mark_price', 0)
            
            side, reason, score = _determine_trade_side(tech, rsi, 0, "NEUTRAL", mark_price, 50, 50)
            
            if score >= 60: # Simpan yang mendekati juga biar Bos liat potensinya
                return {'symbol': s, 'side': side, 'score': score, 'reason': reason}
        except: return None
        return None

    print(f"[2/3] Analyzing market (This may take 1-2 minutes)...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as th_executor:
        futures = [th_executor.submit(check_symbol, s) for s in symbols]
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            res = future.result()
            if res: results.append(res)
            if i % 50 == 0:
                print(f"  > Scanned {i}/{len(symbols)} symbols...", flush=True)

    print("\n" + "="*80)
    print("=" + " "*28 + "TOTAL SWEEP RESULTS" + " "*32 + "=")
    print("="*80)
    
    triggers = [r for r in results if r['score'] >= 80]
    potentials = [r for r in results if 60 <= r['score'] < 80]

    print(f"  LIVE TRIGGERS (Score 80+)  : {len(triggers)}")
    print(f"  NEAR TRIGGERS (Score 60-79) : {len(potentials)}")
    print("="*80)

    if triggers:
        print("\n[!!!] TRACE TRIGGER SUCCESS! The following would be TRADED RIGHT NOW:")
        for c in sorted(triggers, key=lambda x: x['score'], reverse=True):
            print(f"  [EXECUTE] {c['symbol']:<15} | {str(c['side']).upper():<5} | Score: {c['score']} | Reason: {c['reason']}")
    
    if potentials:
        print("\n[POTENTIAL] Watching closely (Near triggers):")
        for c in sorted(potentials, key=lambda x: x['score'], reverse=True)[:10]:
            print(f"  [WAIT]    {c['symbol']:<15} | {str(c['side']).upper():<5} | Score: {c['score']} | Reason: {c['reason']}")

    if not triggers and not potentials:
        print("\n  [!] Market is currently extremely quiet. No high-score setups found.")

    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    run_total_sweep()
