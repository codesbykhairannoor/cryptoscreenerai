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
    print("[SYSTEM] Crypto Hunter Engine AKTIF!")
    
    last_exec_time = 0
    last_news_report = 0
    COOLDOWN_PERIOD = 900 # 15 Mins cooldown
    
    while True:
        try:
            # 1. MONITOR ACTIVE POSITIONS (Intelligent Dashboard)
            executor.manage_open_positions()
            check_pending_trades()
            
            # 2. PERIODIC NEWS VELOCITY (Every 10 Mins)
            if time.time() - last_news_report > 600:
                digest = get_market_news_digest()
                print(f"[NEWS VELOCITY] Sentiment: {digest['sentiment']} | Top: {digest['crypto_top']}")
                last_news_report = time.time()

            # 3. GLOBAL CONTEXT
            global_context = get_global_market_data()
            if int(time.time()) % 300 < 35:
                print(f"[GLOBAL] {global_context}")
            
            raw_data = fetch_all_tickers()
            candidates = analyze_and_sort(raw_data)
            
            if int(time.time()) % 60 < 15:
                print(f"[SCANNER] Found {len(candidates)} candidates matching basic filters.")
            
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
            
                # MILITARY LIMIT: FOCUS ON ONE BEST ENTRY (SINGLE SNIPER MODE)
                if len(open_symbols) >= 1:
                    if int(time.time()) % 60 < 10:
                        print(f"[LIMIT GUARD] Active trade found. Standing by for completion...")
                    break # Exit candidate loop, focus on managing existing
                
                for coin in candidates[:20]:
                    now = time.time()
                    if now - last_exec_time < 60: # Increased cooldown for settlement
                        break

                symbol = coin['symbol']
                # Standardize symbol for comparison using the new robust helper
                clean_sym_base = executor._clean_symbol(symbol)
                open_bases = [executor._clean_symbol(s) for s in open_symbols]
                
                if clean_sym_base in open_bases:
                    continue

                # ALTCOIN PRIORITY: If capital is small, skip BTC to focus on higher-alpha Alts
                if clean_sym_base == 'BTC' and len(candidates) > 3:
                    if int(time.time()) % 60 < 10:
                        print(f"[ALT PRIORITY] Skipping BTC to focus on high-alpha Altcoins.")
                    continue
                
                # 1. CIRCUIT BREAKER CHECK (Global Risk Manager)
                from database import get_performance_stats
                stats = get_performance_stats('crypto')
                daily_pnl = stats.get('win_rate', 0) 
                if daily_pnl < -50: 
                     print(f"[CIRCUIT BREAKER] Loss limit reached today. Standing down for 24h.")
                     break

                tech = get_technical_indicators(symbol)
                is_danger = tech.get('is_session_danger', False)
                is_whale = tech.get('is_whale_accumulation', False)
                fvg_up = tech.get('fvg_up', [])
                fvg_down = tech.get('fvg_down', [])
                vwap_dist = tech.get('vwap_dist', 0)
                mark_price = tech.get('mark_price', 0) 
                
                if mark_price == 0:
                    mark_price = coin.get('lastPrice', 0)

                # SESSION GUARD: Anti-Liquidity Prank
                if is_danger:
                    if int(time.time()) % 60 < 10:
                        print(f"[SESSION GUARD] Market Opening/Closing Detected. Holding all fire to avoid Stop Hunts.")
                    continue

                # REFINED HUNTER LOGIC: MILITARY BI-DIRECTIONAL
                should_trade = False
                side = "buy"
                reason = ""
                
                digest = get_market_news_digest()
                market_is_bullish = digest['sentiment'] == 'BULLISH'
                
                # Logic A: Whale Accumulation (Buy the Bottom)
                if is_whale and vwap_dist < 1.0 and market_is_bullish:
                    should_trade = True
                    side = "buy"
                    reason = "EARLY PUMP (WHALE ACCUMULATION)"
                
                # Logic B: SMC/FVG Return (Buy the Dip)
                elif fvg_up and vwap_dist < 0.5:
                    should_trade = True
                    side = "buy"
                    reason = "SMC FVG RE-ENTRY (INSTITUTIONAL DISCOUNT)"
                
                # Logic C: Whale Distribution (Short the Top)
                elif is_whale and vwap_dist > 5.0 and not market_is_bullish:
                    should_trade = True
                    side = "sell"
                    reason = "WHALE DISTRIBUTION (INSTITUTIONAL SELL)"
                
                # Logic D: Bearish FVG Rejection (Short the Rally)
                elif fvg_down and vwap_dist > 1.5:
                    should_trade = True
                    side = "sell"
                    reason = "BEARISH SMC FVG REJECTION (PREMIUM)"
                
                # Logic E: Sentiment Momentum Short (Military Style)
                elif not market_is_bullish and vwap_dist > 0.7:
                    should_trade = True
                    side = "sell"
                    reason = "BEARISH MOMENTUM (RELIEF PUMP RELIANCE)"

                if should_trade and mark_price > 0:
                    # ORDER DEPTH PROXY
                    from data_fetcher import get_order_book_details
                    ob = get_order_book_details(symbol)
                    if ob['ratio'] < 0.7: continue

                    news_context = get_crypto_news(symbol)

                    print(f"[THE HUNTER] {symbol}: Targeting {reason}. Price vs VWAP: {vwap_dist}%")
                    
                    # DXY OVERRIDE: Anti-Dollar Strength
                    from data_fetcher import get_forex_data
                    dxy = get_forex_data(symbol="DXY")
                    # If DXY market is CLOSED (change is 0 on weekend), ignore the override
                    is_dxy_active = dxy and abs(dxy.get('change', 0)) > 0.0001
                    if is_dxy_active and dxy.get('trend') == 'BULLISH' and dxy.get('change', 0) > 0.2:
                         print(f"[DXY OVERRIDE] Dollar too strong! Aborting {symbol} Long.")
                         continue

                    # Calculate precise SL/TP (Institutional Grade: 30% SL / 100% TP at 10x)
                    # 10x Leverage: 10% price move = 100% PnL, 3% price move = 30% PnL
                    if side == "buy":
                        tp = mark_price * 1.10 # 10% Price Target (100% PnL)
                        sl = mark_price * 0.97 # 3% Stop Loss (30% PnL)
                    else:
                        tp = mark_price * 0.90 # 10% Price Target (100% PnL)
                        sl = mark_price * 1.03 # 3% Stop Loss (30% PnL)
                    
                    amount = executor.get_max_available(symbol, leverage=10)
                    if amount > 0:
                        print(f"[CRYPTO AUTO-TRADE] Snipping {symbol} {side.upper()} | Entry: {mark_price}")
                        success, order = executor.place_order(symbol, side, amount, tp=tp, sl=sl)
                        if success:
                            log_trade(symbol, mark_price, tp, sl)
                            last_exec_time = time.time()
                    else:
                        if int(time.time()) % 60 < 15:
                            print(f"[MARGIN GUARD] Insufficient Free USDT for {symbol} (Min 5 USDT Notional).")
                
            time.sleep(20)
        except Exception as e:
            print(f"[ENGINE ERROR] {e}")
            time.sleep(30)
