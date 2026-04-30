import time
import requests
import random
from data_fetcher import (
    fetch_all_tickers, get_technical_indicators, 
    get_retail_sentiment, detect_institutional_flow
)
from sentiment import get_crypto_news, get_global_market_data
from ai_model import analyze_and_sort
from database import log_trade
from bitget_executor import BitgetExecutor

def detect_volatility_spike(symbol, timeframe="1m"):
    """Sniper Tool: Detects if institutional bots are pumping/dumping."""
    try:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={timeframe}&limit=5"
        res = requests.get(url, timeout=2)
        data = res.json()
        if not data or len(data) < 5: return False
        
        last_vol = float(data[-1][5])
        avg_vol = sum(float(d[5]) for d in data[:-1]) / 4
        
        if last_vol > avg_vol * 3.0: 
            return True
        return False
    except:
        return False

def run_crypto_engine():
    """
    [THE HUNTER] - Institutional-Grade Crypto Trading Engine.
    Uses Whale Accumulation, SMC/FVG, and Intelligent Logging.
    """
    executor = BitgetExecutor()
    from database import check_pending_trades
    from sentiment import get_market_news_digest, get_crypto_news
    print("🛰️ [SYSTEM] Crypto Hunter Engine AKTIF!")
    
    last_exec_time = 0
    last_news_report = 0
    COOLDOWN_PERIOD = 900 # 15 Mins cooldown
    
    while True:
        try:
            # 1. MONITOR ACTIVE POSITIONS (Intelligent Dashboard)
            # This shows PNL, Trailing SL status, and Price Action in one line
            executor.manage_open_positions()
            check_pending_trades()
            
            # 2. PERIODIC NEWS VELOCITY (Every 10 Mins)
            if time.time() - last_news_report > 600:
                digest = get_market_news_digest()
                print(f"🗞️ [NEWS VELOCITY] Sentiment: {digest['sentiment']} | Top: {digest['crypto_top']}")
                last_news_report = time.time()

            # 3. GLOBAL CONTEXT
            global_context = get_global_market_data()
            if int(time.time()) % 300 < 35:
                print(f"🌍 [GLOBAL] {global_context}")
            
            raw_data = fetch_all_tickers()
            candidates = analyze_and_sort(raw_data)
            
            for coin in candidates[:5]:
                now = time.time()
                if now - last_exec_time < COOLDOWN_PERIOD:
                    break

                symbol = coin['symbol']
                entry = coin['lastPrice']
                
                tech = get_technical_indicators(symbol)
                is_danger = tech.get('is_session_danger', False)
                is_whale = tech.get('is_whale_accumulation', False)
                fvg_zones = tech.get('fvg_up', [])
                vwap_dist = tech.get('vwap_dist', 0)
                
                # SESSION GUARD: Anti-Liquidity Prank
                if is_danger:
                    if int(time.time()) % 60 < 10:
                        print(f"⚠️ [SESSION GUARD] Market Opening/Closing Detected. Holding all fire to avoid Stop Hunts.")
                    continue

                # REFINED HUNTER LOGIC
                should_trade = False
                reason = ""
                
                # Logic A: Whale Accumulation (Buy the Bottom before the pump)
                if is_whale and vwap_dist < 1.0:
                    should_trade = True
                    reason = "EARLY PUMP (WHALE ACCUMULATION)"
                
                # Logic B: SMC/FVG Return (Buy the Dip at institutional discount)
                elif fvg_zones and vwap_dist < 0.5:
                    should_trade = True
                    reason = "SMC FVG RE-ENTRY (INSTITUTIONAL DISCOUNT)"

                if should_trade:
                    # ORDER DEPTH PROXY: Check for Supporting Walls
                    from data_fetcher import get_order_book_details
                    ob = get_order_book_details(symbol)
                    if ob['ratio'] < 0.7: # Still want some buyer support
                        continue

                    news_context = get_crypto_news(symbol)
                    print(f"🏛️ [THE HUNTER] {symbol}: Targeting {reason}. Price vs VWAP: {vwap_dist}%")
                    print(f"🔮 [FUTURE OUTLOOK] OrderBook Ratio {ob['ratio']} confirms accumulation. {news_context}")
                    
                    tp = coin.get('tp_price') or (entry * 1.03) 
                    sl = coin.get('sl_price') or (entry * 0.985) # Slightly wider SL for SMC
                    
                    print(f"🔍 [CRYPTO AUTO-TRADE] Snipping {symbol} | Entry: {entry} | TP: {round(tp, 4)}")
                    success, res = executor.place_futures_order(symbol, 'buy', tp_price=tp, sl_price=sl)
                    if success:
                        last_exec_time = time.time()
                        from database import log_trade
                        log_trade(symbol, entry, tp, sl, market='crypto')
                        print(f"✅ [HUNTER SUCCESS] Position opened on {symbol}")
            
        except Exception as e:
            print(f"❌ [CRYPTO ERROR] {e}")
        
        time.sleep(30)
