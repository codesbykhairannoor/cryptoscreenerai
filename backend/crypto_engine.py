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
    print("🚀 [CRYPTO] Trading Engine AKTIF!")
    
    last_exec_time = 0
    COOLDOWN_PERIOD = 600 
    
    while True:
        try:
            # 1. MONITOR ACTIVE POSITIONS (PNL Logging)
            # This shows the user exactly what the bot is managing
            executor.manage_open_positions()
            check_pending_trades()
            
            # 2. GLOBAL CONTEXT & HEARTBEAT
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
                
                # ANTI-FOMO FILTER: 
                # Don't buy if price is already up > 10% in 24h (Pucuk Check)
                price_change_24h = coin.get('priceChangePercent', 0)
                if price_change_24h > 10.0:
                    continue

                tech = get_technical_indicators(symbol)
                rsi = tech.get('rsi', 50)
                
                # OVERBOUGHT GUARD: Don't buy if RSI > 65
                if rsi > 65:
                    continue

                is_vol_spike = detect_volatility_spike(symbol)
                inst_flow = tech.get('inst_flow', "NORMAL")
                retail = get_retail_sentiment(symbol)
                
                should_trade = False
                reason = ""
                
                # SMART SCAN: Institutional Accumulation + RSI Bottom
                if inst_flow == "INSTITUTIONAL_ACCUMULATION" and rsi < 50:
                    should_auto = True
                    reason = "INSTITUTIONAL ACCUMULATION (BOTTOM)"
                elif is_vol_spike and rsi < 60:
                    should_trade = True
                    reason = "VOLATILITY REJECTION"
                
                if should_trade:
                    # SMART FALLBACK: Calculate SL/TP if AI model doesn't provide them
                    tp = coin.get('tp_price') or (entry * 1.03) # 3% Target
                    sl = coin.get('sl_price') or (entry * 0.98) # 2% Stop Loss
                    
                    print(f"🔍 [CRYPTO AUTO-TRADE] {reason} on {symbol} | Target: {round(tp, 4)} | SL: {round(sl, 4)}")
                    success, res = executor.place_futures_order(symbol, 'buy', tp_price=tp, sl_price=sl)
                    if success:
                        last_exec_time = time.time()
                        log_trade(symbol, entry, tp, sl, market='crypto')
                        print(f"✅ [CRYPTO SUCCESS] Auto-Order Filled at ${entry}")
            
        except Exception as e:
            print(f"❌ [CRYPTO ERROR] {e}")
        
        time.sleep(30)
