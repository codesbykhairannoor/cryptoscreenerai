import sys
import os
import time
import json

# Pastikan path backend terbaca
sys.path.append(os.getcwd())

# Import globals first to avoid side effects
import crypto_engine
crypto_engine.SELL_TRADING_ENABLED = True

# Import functions
from crypto_engine import _determine_trade_side, _calc_tp_sl
from bitget_executor import BitgetExecutor

def run_super_test():
    print("\n" + "="*60)
    print("=== CRYPTO ENGINE SUPER INTEGRITY TEST ===")
    print("="*60)

    # 1. SIMULASI DATA (MENIRU LOG DOGS YANG SKIP TADI)
    # RSI: 50, RVOL: 1.5, ATR%: 1.66
    # Signals: MSS Bullish, FVG Bullish
    mock_tech = {
        'symbol': 'DOGSUSDT',
        'mark_price': 0.0006,
        'rvol': 1.5,
        'atr': 0.00001,
        'mss_bullish': True,
        'mss_bearish': False,
        'fvg': 'BULLISH',
        'in_demand': True,
        'trend_1h': 'UP',
        'trend_4h': 'UP'
    }
    mock_rsi = 50.0
    mock_vwap = 0.5
    mock_sentiment = "PENDING"
    
    print(f"\n[STEP 1] Mocking Data for DOGS:")
    print(f"  RSI: {mock_rsi} | RVOL: {mock_tech['rvol']} | ATR: {mock_tech['atr']}")
    print(f"  Signals: MSS_BULL={mock_tech['mss_bullish']}, FVG={mock_tech['fvg']}, OB={mock_tech['in_demand']}")

    # 2. TEST LOGIKA PENENTUAN SIDE (CORE PROBLEM)
    print(f"\n[STEP 2] Running _determine_trade_side...")
    side, reason, tech_score = _determine_trade_side(
        mock_tech, mock_rsi, mock_vwap, mock_sentiment, mock_tech['mark_price'], 77.0, 0.0
    )
    
    print(f"  RESULT -> Side: {side} | Reason: {reason} | Tech Score: {tech_score}")
    
    if side is None:
        print(f"  !!! ALERT: LOGIC REJECTED THE TRADE. Reason: {reason}")
        print(f"  ADVICE: Relaxing RSI requirements for SMC trades might be needed.")
    else:
        print(f"  SUCCESS: Trade Side identified as {side.upper()}")

    # 3. TEST PERHITUNGAN TP/SL
    print(f"\n[STEP 3] Running _calc_tp_sl...")
    tp, sl = _calc_tp_sl(mock_tech['mark_price'], side or "buy", mock_tech)
    print(f"  RESULT -> TP: {tp} | SL: {sl}")

    # 4. TEST BITGET EXECUTOR (KONEKSI & AUTH)
    print(f"\n[STEP 4] Initializing BitgetExecutor...")
    try:
        executor = BitgetExecutor()
        print(f"  Executor Initialized OK.")
        
        # Test Balance
        bal = executor.get_max_available("XRPUSDT")
        print(f"  Available Margin for Test: {bal} USDT")
        
        # 5. DRY RUN ORDER (TANPA KIRIM KE API JIKA SIDE NONE, TAPI KITA TEST AUTH)
        print(f"\n[STEP 5] Final Verdict:")
        if side:
            print(f"  BOT WOULD EXECUTE: {side.upper()} {mock_tech['symbol']} @ {mock_tech['mark_price']}")
        else:
            print(f"  BOT WOULD SKIP: No trade side determined.")
            
    except Exception as e:
        print(f"  EXECUTOR ERROR: {e}")

    print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    run_super_test()
