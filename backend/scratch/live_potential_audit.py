import sys
import os
import time
import json

# Ensure backend path is accessible
sys.path.append(os.getcwd())

# Import components
from data_fetcher import get_technical_indicators
from bitget_executor import BitgetExecutor
from crypto_engine import _determine_trade_side

def run_live_audit():
    print("\n" + "="*80)
    print("=" + " "*25 + "LIVE POTENTIAL AUDIT v1.0" + " "*25 + "=")
    print("=" + " "*22 + "SCANNING 100 LIVE SYMBOLS FOR TRIGGERS" + " "*17 + "=")
    print("="*80 + "\n")

    executor = BitgetExecutor()
    print("[1/2] Fetching top 100 symbols from Bitget...")
    
    # Simple way to get symbols
    try:
        symbols_info = executor.exchange.fetch_tickers()
        all_symbols = [s for s in symbols_info.keys() if s.endswith('USDT')]
        # Filter only Perpetual/Swap
        symbols = [s for s in all_symbols if ':' in s or '/' in s]
        if not symbols: symbols = all_symbols[:100]
        symbols = symbols[:100]
    except:
        print("  [!] Error fetching symbols. Using fallback list.")
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT", "SUIUSDT"]

    results = {
        'score_70+': 0,
        'score_80+': 0,
        'score_90+': 0,
        'score_100': 0,
        'candidates': []
    }

    print(f"[2/2] Auditing {len(symbols)} symbols live...")
    
    for i, s in enumerate(symbols):
        try:
            print(f"  [{i+1}/{len(symbols)}] Checking {s}...", end="\r")
            tech = get_technical_indicators(s)
            if not tech: continue
            
            # Use current ENGINE logic
            rsi = tech.get('rsi', 50)
            mark_price = tech.get('mark_price', 0)
            
            side, reason, score = _determine_trade_side(tech, rsi, 0, "NEUTRAL", mark_price, 50, 50)
            
            if score >= 70: results['score_70+'] += 1
            if score >= 80: results['score_80+'] += 1
            if score >= 90: results['score_90+'] += 1
            if score >= 100: results['score_100'] += 1
            
            if score >= 70:
                results['candidates'].append({
                    'symbol': s, 'side': side, 'score': score, 'reason': reason
                })
        except: continue

    print("\n\n" + "="*80)
    print("=" + " "*28 + "LIVE AUDIT SUMMARY" + " "*33 + "=")
    print("="*80)
    print(f"  Opportunities found (Score 70+)  : {results['score_70+']}")
    print(f"  Opportunities found (Score 80+)  : {results['score_80+']}")
    print(f"  Opportunities found (Score 90+)  : {results['score_90+']}")
    print(f"  Opportunities found (Score 100)  : {results['score_100']}")
    print("="*80)

    if results['candidates']:
        print("\n[TOP CANDIDATES RIGHT NOW]")
        sorted_cand = sorted(results['candidates'], key=lambda x: x['score'], reverse=True)
        for c in sorted_cand[:10]:
            print(f"  {c['symbol']:<15} | Side: {str(c['side']).upper():<5} | Score: {c['score']:>3} | Reason: {c['reason']}")
    else:
        print("\n  [!] No opportunities found at current market conditions.")

    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    run_live_audit()
