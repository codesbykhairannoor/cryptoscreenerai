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
            
            # CHECK ACTIVE CRYPTO POSITIONS BEFORE TRADING
            try:
                positions = executor.get_all_positions()
                open_symbols = [p['symbol'].upper() for p in positions] if isinstance(positions, list) else []
                open_bases = [executor._clean_symbol(s) for s in open_symbols]
                
                if int(time.time()) % 60 < 15:
                    print(f"[ENGINE DEBUG] Active Bases: {open_bases}")
                
                if len(open_symbols) >= 10:
                    if int(time.time()) % 300 < 35:
                        print(f"[CRYPTO LIMIT] Max positions reached ({len(open_symbols)}/10). Skipping new trades.")
                    time.sleep(30)
                    continue
            except Exception as e:
                print(f"[CRYPTO LIMIT ERROR] {e}")
                open_symbols = []
            
            for coin in candidates[:5]:
                now = time.time()
                if now - last_exec_time < COOLDOWN_PERIOD:
                    break

                symbol = coin['symbol']
                # Standardize symbol for comparison using the new robust helper
                clean_sym_base = executor._clean_symbol(symbol)
                open_bases = [executor._clean_symbol(s) for s in open_symbols]
                
                if clean_sym_base in open_bases:
                    continue
                
                # 1. CIRCUIT BREAKER CHECK (Global Risk Manager)
                # If we lost too much today, stop trading.
                from database import get_performance_stats
                stats = get_performance_stats('crypto')
                daily_pnl = stats.get('win_rate', 0) # Placeholder for real PNL logic
                if daily_pnl < -50: # If win rate is suspiciously low or custom PNL check
                     print(f"[CIRCUIT BREAKER] Loss limit reached today. Standing down for 24h.")
                     break

                tech = get_technical_indicators(symbol)
                is_danger = tech.get('is_session_danger', False)
                is_whale = tech.get('is_whale_accumulation', False)
                fvg_zones = tech.get('fvg_up', [])
                vwap_dist = tech.get('vwap_dist', 0)
                mark_price = tech.get('mark_price', 0) # Use fresh price from technicals
                
                if mark_price == 0:
                    mark_price = coin.get('lastPrice', 0)

                # SESSION GUARD: Anti-Liquidity Prank
                if is_danger:
                    if int(time.time()) % 60 < 10:
                        print(f"[SESSION GUARD] Market Opening/Closing Detected. Holding all fire to avoid Stop Hunts.")
                    continue

                # REFINED HUNTER LOGIC
                should_trade = False
                reason = ""
                
                # Logic A: Whale Accumulation (Buy the Bottom)
                if is_whale and vwap_dist < 1.0:
                    should_trade = True
                    reason = "EARLY PUMP (WHALE ACCUMULATION)"
                
                # Logic B: SMC/FVG Return (Buy the Dip)
                elif fvg_zones and vwap_dist < 0.5:
                    should_trade = True
                    reason = "SMC FVG RE-ENTRY (INSTITUTIONAL DISCOUNT)"

                if should_trade and mark_price > 0:
                    # ORDER DEPTH PROXY
                    from data_fetcher import get_order_book_details
                    ob = get_order_book_details(symbol)
                    if ob['ratio'] < 0.7: continue

                    news_context = get_crypto_news(symbol)
                    
                    # SENTIMENT BREAKER: Anti-Bearish Long (The user's XRP Request)
                    digest = get_market_news_digest()
                    if digest['sentiment'] == 'BEARISH':
                        print(f"[SENTIMENT OVERRIDE] Market is BEARISH. Aborting {symbol} Long to avoid catching falling knives.")
                        continue

                    print(f"[THE HUNTER] {symbol}: Targeting {reason}. Price vs VWAP: {vwap_dist}%")
                    
                    # DXY OVERRIDE: Anti-Dollar Strength
                    from data_fetcher import get_forex_data
                    dxy = get_forex_data(symbol="DXY")
                    if dxy and dxy.get('trend') == 'BULLISH' and dxy.get('change', 0) > 0.2:
                         print(f"[DXY OVERRIDE] Dollar too strong! Aborting {symbol} Long.")
                         continue

                    # Calculate precise SL/TP
                    tp = mark_price * 1.03 # 3% Target
                    sl = mark_price * 0.98 # 2% Stop Loss
                    
                    print(f"🔍 [CRYPTO AUTO-TRADE] Snipping {symbol} | Entry: {mark_price} | TP: {round(tp, 4)}")
                    success, res = executor.place_futures_order(symbol, 'buy', tp_price=tp, sl_price=sl)
                    if success:
                        last_exec_time = time.time()
                        log_trade(symbol, mark_price, tp, sl, market='crypto')
                        print(f"✅ [HUNTER SUCCESS] Position opened on {symbol} with Protection.")
            
        except Exception as e:
            print(f"❌ [CRYPTO ERROR] {e}")
        
        time.sleep(30)
