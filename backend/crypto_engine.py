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
    Dedicated Crypto Trading Engine.
    Isolated from Forex and Stocks.
    """
    executor = BitgetExecutor()
    from database import check_pending_trades
    from sentiment import get_market_news_digest, get_crypto_news
    print("🚀 [CRYPTO] Trading Engine AKTIF!")
    
    last_exec_time = 0
    last_news_report = 0
    COOLDOWN_PERIOD = 600 
    
    while True:
        try:
            # 1. MONITOR ACTIVE POSITIONS (PNL Logging)
            executor.manage_open_positions()
            check_pending_trades()
            
            # 2. PERIODIC NEWS DIGEST (Every 10 Mins)
            if time.time() - last_news_report > 600:
                digest = get_market_news_digest()
                print(f"🗞️ [NEWS DIGEST] Sentiment: {digest['sentiment']}")
                print(f"🗞️ [TOP CRYPTO] {digest['crypto_top']}")
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
                rsi = tech.get('rsi', 50)
                vwap = tech.get('vwap', entry)
                vwap_dist = tech.get('vwap_dist', 0)
                is_sweep = tech.get('is_liquidity_sweep', False)
                
                # 1. INSTITUTIONAL FAIR VALUE CHECK (Anti-FOMO)
                # Don't buy if price is > 3% above VWAP (Price is too expensive/over-extended)
                if vwap_dist > 3.0:
                    continue

                # 2. ORDER BOOK IMBALANCE (Whale Tracker)
                from data_fetcher import get_order_book_details
                ob = get_order_book_details(symbol)
                # If Ask Wall is 2x Bid Wall,Institutions are likely pushing price down. Avoid.
                if ob['ratio'] < 0.5:
                    continue

                is_vol_spike = detect_volatility_spike(symbol)
                inst_flow = tech.get('inst_flow', "NORMAL")
                
                should_trade = False
                reason = ""
                
                # REFINED STRATEGY: Institutional Reversals
                if is_sweep:
                    should_trade = True
                    reason = "INSTITUTIONAL LIQUIDITY SWEEP (STOP-HUNT REVERSAL)"
                elif inst_flow == "INSTITUTIONAL_ACCUMULATION" and vwap_dist < 1.0:
                    should_trade = True
                    reason = "INSTITUTIONAL VWAP ACCUMULATION"
                elif is_vol_spike and rsi < 55 and vwap_dist < 2.0:
                    should_trade = True
                    reason = "VWAP SUPPORT BREAKOUT"
                
                if should_trade:
                    # 4. FUTURE PROJECTION: Combined News + Tech
                    news_context = get_crypto_news(symbol)
                    print(f"🏛️ [WALL STREET LOGIC] {symbol}: Trading with the Whales. Reason: {reason}. Price vs VWAP: {vwap_dist}%")
                    print(f"🔮 [FUTURE OUTLOOK] RSI {rsi} & OrderBook Ratio {ob['ratio']} suggests upward momentum. {news_context}")
                    
                    tp = coin.get('tp_price') or (entry * 1.03) 
                    sl = coin.get('sl_price') or (entry * 0.98) 
                    
                    print(f"🔍 [CRYPTO AUTO-TRADE] Executing on {symbol} | Target: {round(tp, 4)} | SL: {round(sl, 4)}")
                    success, res = executor.place_futures_order(symbol, 'buy', tp_price=tp, sl_price=sl)
                    if success:
                        last_exec_time = time.time()
                        log_trade(symbol, entry, tp, sl, market='crypto')
                        print(f"✅ [CRYPTO SUCCESS] Auto-Order Filled at ${entry}")
            
        except Exception as e:
            print(f"❌ [CRYPTO ERROR] {e}")
        
        time.sleep(30)
