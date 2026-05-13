import os
import sys
import time
import datetime
from forex_executor import ForexExecutor

def diagnose_forex_current():
    print("=== FOREX REAL-TIME DIAGNOSTIC v1.0 ===")
    fx = ForexExecutor()
    if not fx.is_active:
        print("MetaAPI not connected.")
        return

    print("Fetching live data...")
    price_data = fx.get_live_price()
    print(f"Price: {price_data['mid']} | Spread: {price_data['spread_points']} pts")
    
    print("\nCalculating Indicators...")
    ind = fx._calc_indicators()
    if not ind:
        print("Failed to calculate indicators.")
        return

    # Print Key Indicator Status
    print("-" * 30)
    print(f"RSI (30m):   {ind['rsi']}")
    print(f"Trend (30m): {ind['trend']}")
    print(f"Trend (1h):  {ind['trend_1h']}")
    print(f"Trend (4h):  {ind['trend_4h']}")
    print(f"Pump Signal: {ind['pump_signal']}")
    print(f"MSS/CHoCH:   Bull:{ind['mss_bullish']} Bear:{ind['mss_bearish']}")
    print(f"FVG:         {ind['fvg']}")
    print(f"Price Pos:   {ind['price_position_pct']}% (Near ATH: {ind['near_ath']}, Near ATL: {ind['near_atl']})")
    print("-" * 30)

    # Scoring Analysis
    buy_score = fx._score_setup(ind, "buy", price_data['spread_points'])
    sell_score = fx._score_setup(ind, "sell", price_data['spread_points'])
    
    print(f"\nSCORE ANALYSIS:")
    print(f"BUY SCORE:  {buy_score}/100")
    print(f"SELL SCORE: {sell_score}/100")
    
    # Check Confluence
    mtf_buy = fx._get_mtf_confluence("buy")
    mtf_sell = fx._get_mtf_confluence("sell")
    e5m = fx._get_5m_entry_quality()
    
    print(f"\nCONFLUENCE:")
    print(f"MTF Buy:  {mtf_buy['confluence']} ({mtf_buy['aligned_count']}/4)")
    print(f"MTF Sell: {mtf_sell['confluence']} ({mtf_sell['aligned_count']}/4)")
    print(f"5m Entry Quality: {e5m['quality']} ({e5m['signal']})")

    # DXY Check
    dxy = fx._get_dxy_context()
    print(f"\nDXY MACRO:")
    print(f"DXY Trend: {dxy['trend']} | Change: {dxy['change']}%")

    # Final Verdict
    side, final_score, _ = fx._determine_side(ind, price_data['spread_points'])
    print("\n" + "="*40)
    if side:
        print(f"RESULT: Signal found! {side.upper()} with score {final_score}")
    else:
        print(f"RESULT: No trade signal at the moment.")
    print("="*40)

if __name__ == "__main__":
    diagnose_forex_current()
