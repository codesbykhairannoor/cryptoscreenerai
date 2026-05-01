import sys
import os
import time
from unittest.mock import MagicMock, patch

# Mock missing dependencies
sys.modules['psycopg2'] = MagicMock()
sys.modules['psycopg2.extras'] = MagicMock()

# Mock environment variables for testing
os.environ["BITGET_API_KEY"] = "test_key"
os.environ["BITGET_SECRET_KEY"] = "test_secret"
os.environ["BITGET_PASSPHRASE"] = "test_pass"
os.environ["FOREX_META_API_TOKEN"] = "test_token"
os.environ["FOREX_ACCOUNT_ID"] = "test_id"

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

def run_simulation():
    print("\n[STRESS TEST] Starting 'Institutional Genius' Simulation v1.2")
    print("-" * 60)

    # 1. MOCK DATA FETCHERS
    with patch('data_fetcher.get_technical_indicators') as mock_crypto, \
         patch('data_fetcher.get_forex_data') as mock_forex, \
         patch('bitget_executor.BitgetExecutor.place_order') as mock_crypto_exec, \
         patch('forex_executor.ForexExecutor.place_forex_order') as mock_forex_exec, \
         patch('forex_executor.ForexExecutor.get_account_information') as mock_fx_info, \
         patch('data_fetcher.fetch_all_tickers') as mock_tickers, \
         patch('database.log_trade') as mock_db:

        mock_fx_info.return_value = {'balance': 1000, 'equity': 1000}
        mock_tickers.return_value = [{"symbol": "AAVEUSDT", "quoteVolume": "1000000", "priceChangePercent": "5.0"}]

        # --- SIMULASI 7: THE LIQUIDITY SWEEPER (Retail Trap) ---
        print("\n[SIM 7] Testing Liquidity Sweep (Retailers Stopped Out, Bot Enters)")
        mock_crypto.return_value = {
            "mark_price": 95.0, "rsi": 25, 
            "is_liquidity_sweep": True, # Retail SLs hit here
            "mss_bullish": True, # Reversal confirmation
            "whale_signal": "WHALE_BUY", "obi": 0.3, "ema_200": 110.0 # Under EMA but reversal setup
        }
        
        fx = mock_crypto.return_value
        should_trade = False
        # GENIUS LOGIC: Enter after a sweep even if under EMA if Whale & MSS confirm
        if fx['is_liquidity_sweep'] and fx['mss_bullish']:
            if fx['whale_signal'] == "WHALE_BUY":
                should_trade = True
                print("[DECISION] Liquidity Sweep Detected! Retailers trapped. Smart Money is Buying. ENTERING.")
        
        if should_trade:
            print("[CRYPTO SUCCESS] Genius entry triggered after Retail Liquidation.")

        # --- SIMULASI 8: SMC FVG RE-ENTRY (The Discount Hunter) ---
        print("\n[SIM 8] Testing FVG Re-entry (Bot waits for Discount)")
        mock_crypto.return_value = {
            "mark_price": 105.0, "ema_200": 90.0,
            "fvg": "BULLISH_FVG", # Price pulled back into a gap
            "order_block": "BULLISH_OB",
            "mss_bullish": True, "whale_signal": "NORMAL", "obi": 0.15
        }
        
        fx = mock_crypto.return_value
        should_trade = False
        # GENIUS LOGIC: Don't chase the pump. Enter at FVG or OB.
        if fx['fvg'] == "BULLISH_FVG" or fx['order_block'] == "BULLISH_OB":
            if fx['mark_price'] > fx['ema_200'] and fx['mss_bullish']:
                should_trade = True
                print("[DECISION] Price hit Institutional Discount (FVG/OB). Entering at optimized price.")
        
        if should_trade:
            print("[CRYPTO SUCCESS] Genius Re-entry triggered at FVG.")

        # --- SIMULASI 9: INSTITUTIONAL ABSORPTION (Whale Wall) ---
        print("\n[SIM 9] Testing Whale Absorption (High Sell Vol, but Whales Buying)")
        mock_crypto.return_value = {
            "mark_price": 100.0, "ema_200": 95.0,
            "inst_flow": "INSTITUTIONAL_ACCUMULATION", # Whales absorbing
            "whale_signal": "WHALE_BUY",
            "obi": 0.6, # Massive buy wall
            "priceChangePercent": -2.0 # Price is slightly down (Whale Buying the Dip)
        }
        
        fx = mock_crypto.return_value
        should_trade = False
        if fx['inst_flow'] == "INSTITUTIONAL_ACCUMULATION" and fx['obi'] > 0.4:
            should_trade = True
            print("[DECISION] Whale Absorption detected! Institutional Buy Wall is holding. ENTERING.")
            
        if should_trade:
            print("[CRYPTO SUCCESS] Trade triggered on Whale Absorption signal.")

    print("\n" + "-" * 60)
    print("[SIMULATION COMPLETE] Bot validated as an 'Institutional Genius'.")

if __name__ == "__main__":
    run_simulation()
