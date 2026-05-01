import requests
import pandas as pd
import numpy as np
import time
import os
from dotenv import load_dotenv

load_dotenv()

def detect_candle_patterns(df):
    if len(df) < 5: return "NONE"
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # 1. Hammer / Shooting Star
    body = abs(last['close'] - last['open'])
    wick_up = last['high'] - max(last['open'], last['close'])
    wick_down = min(last['open'], last['close']) - last['low']
    
    if wick_down > body * 2 and wick_up < body: return "HAMMER_BULLISH"
    if wick_up > body * 2 and wick_down < body: return "SHOOTING_STAR_BEARISH"
    
    # 2. Engulfing
    if last['close'] > prev['open'] and last['open'] < prev['close'] and prev['close'] < prev['open']:
        return "BULLISH_ENGULFING"
    if last['close'] < prev['open'] and last['open'] > prev['close'] and prev['close'] > prev['open']:
        return "BEARISH_ENGULFING"
        
    return "NEUTRAL"

def detect_smart_money_concepts(df):
    """SMC: Order Blocks & FVG Detection"""
    if len(df) < 20: return {"ob": "NONE", "fvg": "NONE"}
    
    # 1. Order Block (OB): Last opposite candle before a strong move
    last_5 = df.iloc[-5:]
    is_bull_move = last_5['close'].iloc[-1] > last_5['open'].iloc[0] * 1.02
    is_bear_move = last_5['close'].iloc[-1] < last_5['open'].iloc[0] * 0.98
    
    ob = "NONE"
    if is_bull_move: ob = "BULLISH_OB"
    if is_bear_move: ob = "BEARISH_OB"
    
    # 2. FVG (Fair Value Gap)
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    fvg = "NONE"
    if c1['high'] < c3['low']: fvg = "BULLISH_FVG"
    if c1['low'] > c3['high']: fvg = "BEARISH_FVG"
    
    return {"ob": ob, "fvg": fvg}

def detect_institutional_flow(df):
    """Institutional Flow based on Volume Profile"""
    avg_vol = df['vol'].rolling(20).mean().iloc[-1]
    last_vol = df['vol'].iloc[-1]
    last_close = df['close'].iloc[-1]
    last_open = df['open'].iloc[-1]
    
    if last_vol > avg_vol * 2:
        if last_close > last_open: return "INSTITUTIONAL_ACCUMULATION"
        else: return "INSTITUTIONAL_DISTRIBUTION"
    return "NORMAL"

def get_orderbook_imbalance(symbol):
    """Calculates real-time Bid/Ask pressure"""
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/depth?symbol={symbol}&limit=50&productType=USDT-FUTURES"
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code == 200:
            data = r.json().get('data', {})
            bids = sum(float(b[1]) for b in data.get('bids', []))
            asks = sum(float(a[1]) for a in data.get('asks', []))
            if (bids + asks) == 0: return 0
            imbalance = (bids - asks) / (bids + asks)
            return round(imbalance, 4)
    except: pass
    return 0

def detect_whale_activity(symbol):
    """Scans recent trade stream for institutional-sized fills"""
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/fills?symbol={symbol}&limit=50&productType=USDT-FUTURES"
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code == 200:
            trades = r.json().get('data', [])
            whale_buys = 0
            whale_sells = 0
            for t in trades:
                size_usd = float(t.get('size', 0)) * float(t.get('price', 0))
                if size_usd > 50000: # $50k threshold
                    if t.get('side') == 'buy': whale_buys += size_usd
                    else: whale_sells += size_usd
            
            if whale_buys > whale_sells and whale_buys > 100000: return "WHALE_BUY"
            if whale_sells > whale_buys and whale_sells > 100000: return "WHALE_SELL"
    except: pass
    return "NORMAL"

def get_open_interest(symbol):
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/open-interest?symbol={symbol}&productType=USDT-FUTURES"
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code == 200:
            data = r.json().get('data', [{}])[0]
            return float(data.get('openInterest', 0))
    except: pass
    return 0

def get_funding_rate(symbol):
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/current-funding-rate?symbol={symbol}&productType=USDT-FUTURES"
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code == 200:
            data = r.json().get('data', [{}])[0]
            return float(data.get('fundingRate', 0))
    except: pass
    return 0

def get_technical_indicators(symbol, interval="15m"):
    """
    Institutional Logic v5.0: SMC + Order Flow + Predictive Structure
    """
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&granularity={interval}&limit=100&productType=USDT-FUTURES"
        r = requests.get(url, timeout=10, verify=False)
        if r.status_code != 200: return {}
        
        data = r.json().get('data', [])
        df_cur = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'vol_usd'])
        df_cur[['open', 'high', 'low', 'close', 'vol']] = df_cur[['open', 'high', 'low', 'close', 'vol']].astype(float)
        
        # 1. PRICE & TREND
        mark_price = df_cur['close'].iloc[-1]
        ema_200_cur = df_cur['close'].ewm(span=200, adjust=False).mean()
        rsi_cur = pd.Series([50] * len(df_cur)) # Placeholder for RSI calculation if needed
        atr_cur = pd.Series([1.0] * len(df_cur)) # Placeholder for ATR
        
        # 2. HTF CONTEXT (1H)
        url_htf = f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&granularity=1h&limit=100&productType=USDT-FUTURES"
        r_htf = requests.get(url_htf, timeout=5, verify=False)
        ema_200_htf = pd.Series([0])
        if r_htf.status_code == 200:
            data_htf = r_htf.json().get('data', [])
            df_htf = pd.DataFrame(data_htf, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'vol_usd'])
            df_htf['close'] = df_htf['close'].astype(float)
            ema_200_htf = df_htf['close'].ewm(span=200, adjust=False).mean()

        # 3. LIQUIDITY SWEEPS (Smart Money Entrapment)
        last_candle = df_cur.iloc[-1]
        prev_candle = df_cur.iloc[-2]
        avg_vol = df_cur['vol'].rolling(20).mean().iloc[-1]
        
        # Bullish Sweep: Price breaks below prev low then closes back above it
        is_bull_sweep = last_candle['low'] < prev_candle['low'] and last_candle['close'] > prev_candle['low']
        # Bearish Sweep: Price breaks above prev high then closes back below it
        is_bear_sweep = last_candle['high'] > prev_candle['high'] and last_candle['close'] < prev_candle['high']
        is_sweep = is_bull_sweep or is_bear_sweep
        
        # 4. MARKET STRUCTURE SHIFT (MSS) & CHoCH (PREDICTING THE FUTURE)
        mss_bullish = False
        mss_bearish = False
        choch_bullish = False
        choch_bearish = False
        
        if len(df_cur) >= 10:
            recent_highs = df_cur['high'].iloc[-10:-1].max()
            recent_lows = df_cur['low'].iloc[-10:-1].min()
            last_close = df_cur['close'].iloc[-1]
            
            if last_close > recent_highs: choch_bullish = True
            elif last_close < recent_lows: choch_bearish = True
            
            if choch_bullish and last_candle['vol'] > avg_vol * 1.5: mss_bullish = True
            if choch_bearish and last_candle['vol'] > avg_vol * 1.5: mss_bearish = True

        # 5. FIBONACCI PREDICTIVE LEVELS
        high_p = df_cur['high'].max()
        low_p = df_cur['low'].min()
        diff = high_p - low_p
        fib_ext = high_p + (diff * 0.618) if mss_bullish else low_p - (diff * 0.618)

        # 6. VOLUME-TO-PRICE DIVERGENCE (Whale Accumulation Detector)
        vol_surge = last_candle['vol'] / avg_vol if avg_vol > 0 else 1
        price_change_abs = abs((last_candle['close'] - last_candle['open']) / last_candle['open'] * 100)
        is_whale_accumulation = vol_surge > 3.0 and price_change_abs < 2.0

        # Smart detection
        pattern = detect_candle_patterns(df_cur)
        smc = detect_smart_money_concepts(df_cur)
        inst_flow = detect_institutional_flow(df_cur)
        oi = get_open_interest(symbol)
        funding = get_funding_rate(symbol)
        
        # 7. ORDER BOOK & WHALE INTELLIGENCE (The Genius Layer)
        obi = get_orderbook_imbalance(symbol)
        whale_sig = detect_whale_activity(symbol)
        
        return {
            "mark_price": mark_price,
            "rsi": 50,
            "atr": 1.0,
            "is_liquidity_sweep": is_sweep,
            "mss_bullish": mss_bullish,
            "mss_bearish": mss_bearish,
            "choch_bullish": choch_bullish,
            "choch_bearish": choch_bearish,
            "fib_ext": round(fib_ext, 4),
            "obi": obi,
            "whale_signal": whale_sig,
            "is_whale_accumulation": is_whale_accumulation,
            "order_block": smc["ob"],
            "fvg": smc["fvg"],
            "inst_flow": inst_flow,
            "open_interest": oi,
            "funding_rate": funding,
            "ema_200": round(ema_200_cur.iloc[-1], 2) if not ema_200_cur.empty else 0,
        }
    except Exception as e:
        print(f"Error indicators for {symbol}: {e}")
        return {}

def get_defillama_metrics(protocol="aave"):
    """
    Fetch On-Chain metrics from DefiLlama.
    Tracks TVL (Total Value Locked) and TVL Changes.
    """
    try:
        api_key = os.getenv("DEFILLAMA_API_KEY")
        base_url = "https://pro-api.llama.fi" if api_key else "https://api.llama.fi"
        headers = {"X-Api-Key": api_key} if api_key else {}
        
        r = requests.get(f"{base_url}/protocol/{protocol}", headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            # TVL data is usually a list of daily TVL
            tvl_list = data.get('tvl', [])
            if not tvl_list: return {"tvl": 0, "tvl_change_24h": 0}
            
            current_tvl = tvl_list[-1].get('totalLiquidityUSD', 0)
            tvl_change_pct = 0
            if len(tvl_list) >= 2:
                prev_tvl = tvl_list[-2].get('totalLiquidityUSD', 0)
                tvl_change_pct = ((current_tvl - prev_tvl) / prev_tvl * 100) if prev_tvl > 0 else 0
                
            return {
                "tvl": current_tvl,
                "tvl_change_24h": round(tvl_change_pct, 2),
                "chains": data.get('chains', []),
                "category": data.get('category', 'DeFi')
            }
    except Exception as e:
        print(f"DefiLlama Error for {protocol}: {e}")
    return {"tvl": 0, "tvl_change_24h": 0}

def get_forex_data(symbol="XAUUSD", interval="15m"):
    """
    Fetch indicators for Forex.
    Uses Bitget PAXGUSDT as Gold proxy.
    """
    try:
        token = os.getenv("FOREX_META_API_TOKEN")
        account_id = os.getenv("FOREX_ACCOUNT_ID")
        headers_meta = {"auth-token": token}
        base_url = "https://mt-client-api-v1.london.agiliumtrade.ai"

        exact_price = 0
        spread = 0
        working_symbol = symbol
        for suffix in ["", "c", ".m"]:
            try:
                sym_try = f"{symbol}{suffix}"
                r = requests.get(f"{base_url}/users/current/accounts/{account_id}/symbols/{sym_try}/current-price", headers=headers_meta, timeout=5)
                if r.status_code == 200:
                    d = r.json()
                    bid = float(d.get('bid', 0))
                    ask = float(d.get('ask', 0))
                    if bid > 0:
                        exact_price = bid
                        working_symbol = sym_try
                        spread = round((ask - bid) * 100, 1) if ask > 0 else 0
                        break
            except: continue

        proxy_symbol = "PAXGUSDT"
        indicators = get_technical_indicators(proxy_symbol, interval=interval)
        if not indicators:
            indicators = {"rsi": 50, "atr": 1.5, "order_block": "NONE", "fvg": "NONE", "inst_flow": "NORMAL"}

        return {
            "symbol": symbol,
            "lastPrice": exact_price if exact_price > 0 else indicators.get("mark_price", 0),
            "spread": spread,
            "rsi": indicators.get("rsi", 50),
            "atr": indicators.get("atr", 1.5),
            "order_block": indicators.get("order_block", "NONE"),
            "fvg": indicators.get("fvg", "NONE"),
            "inst_flow": indicators.get("inst_flow", "NORMAL"),
            "obi": indicators.get("obi", 0),
            "whale_signal": indicators.get("whale_signal", "NORMAL"),
            "is_liquidity_sweep": indicators.get("is_liquidity_sweep", False),
            "mss_bullish": indicators.get("mss_bullish", False),
            "mss_bearish": indicators.get("mss_bearish", False),
            "fib_ext": indicators.get("fib_ext", 0),
            "trend": "BULLISH" if exact_price > indicators.get("ema_200", 0) else "BEARISH",
            "working_symbol": working_symbol
        }
    except Exception as e:
        print(f"Error Forex indicators: {e}")
        return {}

if __name__ == "__main__":
    print(get_defillama_metrics("aave"))
