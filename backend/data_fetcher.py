import requests
import pandas as pd
import numpy as np
import time
import os
from patterns import detect_candle_patterns, detect_smart_money_concepts

def get_orderbook_analysis(symbol):
    """
    [L2 DATA ENGINE] - Analyzes Bitget Order Book for 'Big Walls'
    Logic: Detects where market makers are stacking orders (Order Flow)
    """
    try:
        # Convert symbol for Bitget API (e.g., BTCUSDT)
        clean_symbol = symbol.replace("/", "").split(":")[0]
        url = f"https://api.bitget.com/api/v3/market/orderbook?category=USDT-FUTURES&symbol={clean_symbol}&limit=20"
        res = requests.get(url, timeout=5)
        data = res.json()
        
        if data.get('code') == '00000' and 'data' in data:
            bids = data['data'].get('b', []) # Buying side
            asks = data['data'].get('a', []) # Selling side
            
            # Calculate Total Volume on both sides (Top 20 levels)
            bid_vol = sum([float(b[1]) for b in bids])
            ask_vol = sum([float(a[1]) for a in asks])
            
            # Wall Detection: If one side is 2x stronger than other
            ratio = bid_vol / ask_vol if ask_vol > 0 else 1.0
            
            is_buying_wall = ratio > 2.5
            is_selling_wall = ratio < 0.4
            
            return {
                "bid_vol": round(bid_vol, 2),
                "ask_vol": round(ask_vol, 2),
                "ratio": round(ratio, 2),
                "is_buying_wall": is_buying_wall,
                "is_selling_wall": is_selling_wall,
                "wall_sentiment": "BULLISH (Whale Support)" if is_buying_wall else "BEARISH (Big Resistance)" if is_selling_wall else "NEUTRAL"
            }
    except Exception as e:
        print(f"[ORDERBOOK ERROR] {symbol}: {e}")
    return {"bid_vol": 0, "ask_vol": 0, "ratio": 1, "is_buying_wall": False, "is_selling_wall": False, "wall_sentiment": "UNKNOWN"}

def get_funding_rate(symbol):
    """
    [MARKET OVERHEAT DETECTOR] - Tracks current funding rates
    Logic: High Positive Funding = Overleveraged Longs (Dump Risk)
    """
    try:
        clean_symbol = symbol.replace("/", "").split(":")[0]
        url = f"https://api.bitget.com/api/v3/market/current-fund-rate?symbol={clean_symbol}"
        res = requests.get(url, timeout=5)
        data = res.json()
        if data.get('code') == '00000' and 'data' in data:
            rates = data['data']
            if rates:
                rate = float(rates[0].get('fundingRate', 0))
    except:
        pass
    
    if rate != 0:
        print(f"[SENSORS] Funding Rate {symbol}: {round(rate * 100, 4)}%")
    return rate

def get_open_interest(symbol):
    """
    [INSTITUTIONAL RADAR] - Tracks market participation
    """
    oi = 0
    try:
        clean_symbol = symbol.replace("/", "").split(":")[0]
        url = f"https://api.bitget.com/api/v3/market/open-interest?category=USDT-FUTURES&symbol={clean_symbol}"
        res = requests.get(url, timeout=5)
        data = res.json()
        if data.get('code') == '00000' and 'data' in data:
            oi_list = data['data'].get('list', [])
            if oi_list:
                oi = float(oi_list[0].get('openInterest', 0))
    except:
        pass
    
    if oi > 0:
        # Bitget V3 Open Interest can be in USD or Contracts. 
        # If it's very large, it might be raw USD. If small, it might be contracts.
        # But typically Bitget returns USD value in 'openInterest'.
        # We will assume it's in USD but format it properly.
        if oi > 1e6:
            print(f"[SENSORS] Open Interest {symbol}: ${round(oi/1e6, 2)}M")
        elif oi > 1e3:
            print(f"[SENSORS] Open Interest {symbol}: ${round(oi/1e3, 2)}K")
        else:
            print(f"[SENSORS] Open Interest {symbol}: ${round(oi, 2)}")
    return oi

def fetch_all_tickers():
    """MIGRATED TO BITGET V3 ENGINE"""
    try:
        url = "https://api.bitget.com/api/v3/market/tickers?category=USDT-FUTURES"
        res = requests.get(url, timeout=10)
        data = res.json()
        if data.get('code') == '00000' and 'data' in data:
            raw_list = data['data']
            # Map Bitget fields to our internal format
            mapped_data = []
            for d in raw_list:
                mapped_data.append({
                    "symbol": d['symbol'],
                    "lastPrice": float(d.get('last', 0)),
                    "priceChangePercent": float(d.get('change24h', 0)) * 100,
                    "quoteVolume": float(d.get('quoteVolume', 0))
                })
            df = pd.DataFrame(mapped_data)
            print(f"[MARKET] Berhasil memetakan {len(df)} ticker dari Bitget.")
            return df
    except Exception as e:
        print(f"[BITGET FETCH ERROR] {e}")
        return pd.DataFrame()

def get_crypto_data(symbol, interval='5m'):
    """MIGRATED TO BITGET V3 CANDLE ENGINE"""
    try:
        # Standardize symbol for Bitget (BTCUSDT)
        clean_symbol = symbol.replace("/", "").split(":")[0]
        
        # 1. Fetch Candles from Bitget
        # Mapping interval to Bitget format
        bg_interval = interval if interval != '1h' else '1H'
        url = f"https://api.bitget.com/api/v3/market/candles?symbol={clean_symbol}&granularity={bg_interval}&limit=200&productType=USDT-FUTURES"
        res = requests.get(url, timeout=10)
        raw_candles = res.json()
        
        if not isinstance(raw_candles, list): 
            # Bitget V3 returns {code, msg, data} sometimes
            raw_candles = raw_candles.get('data', [])

        # Bitget Candle Format: [ts, open, high, low, close, vol, quoteVol]
        df_cur = pd.DataFrame(raw_candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'quoteVol'])
        for col in ['open', 'high', 'low', 'close', 'vol']:
            df_cur[col] = df_cur[col].astype(float)
        
        # Sort by timestamp (Bitget usually returns newest first)
        df_cur = df_cur.sort_values('ts').reset_index(drop=True)
        return df_cur

    except Exception as e:
        print(f"[DATA FETCH ERROR] {symbol}: {e}")
        return pd.DataFrame()

def get_order_book_details(symbol):
    try:
        url = f"https://data-api.binance.vision/api/v3/depth?symbol={symbol}&limit=5"
        res = requests.get(url)
        data = res.json()
        
        bids = data.get('bids', [])
        asks = data.get('asks', [])
        
        if not bids or not asks:
            return {"ratio": 1.0, "bid_wall_price": 0, "bid_wall_usdt": 0, "ask_wall_price": 0, "ask_wall_usdt": 0}

        top_bid = bids[0]
        top_ask = asks[0]
        
        bid_vol = sum(float(b[1]) for b in bids)
        ask_vol = sum(float(a[1]) for a in asks)
        ratio = bid_vol / ask_vol if ask_vol > 0 else 1.0
        
        return {
            "ratio": round(ratio, 2),
            "bid_wall_price": float(top_bid[0]),
            "bid_wall_usdt": float(top_bid[0]) * float(top_bid[1]),
            "ask_wall_price": float(top_ask[0]),
            "ask_wall_usdt": float(top_ask[0]) * float(top_ask[1])
        }
    except:
        return {"ratio": 1.0, "bid_wall_price": 0, "bid_wall_usdt": 0, "ask_wall_price": 0, "ask_wall_usdt": 0}

def get_technical_indicators(symbol, interval="15m", period=14):
    try:
        # Standardize symbol for Bitget
        clean_symbol = symbol.replace("/", "").split(":")[0]
        
        # Determine Higher Timeframe (HTF) for confirmation
        htf_map = {"15m": "1H", "1h": "4H", "4h": "12H", "1d": "1D"}
        htf = htf_map.get(interval, "1H")
        bg_interval = interval if interval != '1h' else '1H'

        # 1. Fetch Current Interval from BITGET (Hybrid V3 with V2 Fallback)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        data_cur = None  # Initialize before try blocks to prevent UnboundLocalError
        try:
            url_v3 = f"https://api.bitget.com/api/v3/market/candles?symbol={clean_symbol}&interval={bg_interval}&limit=100&category=USDT-FUTURES"
            res = requests.get(url_v3, headers=headers, timeout=5, verify=False)
            
            if res.status_code != 200:
                print(f"[V3 ERROR] {clean_symbol} HTTP {res.status_code}")
                raise ValueError("HTTP Error")
                
            try:
                data_cur = res.json()
            except:
                print(f"[V3 JSON ERROR] {clean_symbol} response was not JSON: {res.text[:100]}")
                raise ValueError("Not JSON")

            if not data_cur or 'data' not in data_cur or not data_cur['data']:
                print(f"[V3 DEBUG] {clean_symbol} Data Missing.")
                raise ValueError("V3 Empty")
        except Exception as e:
            # Fallback to V2 Mix API (Very Stable)
            try:
                v2_gran = interval if interval != '1h' else '1H'
                url_v2 = f"https://api.bitget.com/api/v2/mix/market/candles?symbol={clean_symbol}&granularity={v2_gran}&limit=200&productType=usdt-futures"
                res = requests.get(url_v2, headers=headers, timeout=5, verify=False)
                
                if res.status_code != 200:
                    raise ValueError(f"HTTP {res.status_code}")
                    
                try:
                    data_cur = res.json()
                except:
                    raise ValueError("Not JSON")

                if not data_cur or 'data' not in data_cur or not data_cur['data']:
                    raise ValueError("V2 Empty")
            except Exception as e2:
                print(f"[API ERROR] V2/V3 failed for {clean_symbol}: {e2}")

        if not data_cur or 'data' not in data_cur or not data_cur['data']:
            print(f"[DATA] Sinkronisasi {clean_symbol} gagal di semua jalur...")
            return {}
        
        # Bitget Format: [ts, open, high, low, close, vol, qvol]
        df_cur = pd.DataFrame(data_cur['data'], columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'quoteVol'])
        for col in ['open', 'high', 'low', 'close', 'vol']:
            df_cur[col] = df_cur[col].astype(float)
        # 2. Fetch HTF from BITGET (Hybrid)
        try:
            url_htf_v3 = f"https://api.bitget.com/api/v3/market/candles?symbol={clean_symbol}&interval={htf}&limit=100&category=USDT-FUTURES"
            res_h = requests.get(url_htf_v3, headers=headers, timeout=5, verify=False)
            data_htf = res_h.json()
            if not data_htf or 'data' not in data_htf or not data_htf['data']:
                raise ValueError("V3 Empty HTF")
        except:
            try:
                url_htf_v2 = f"https://api.bitget.com/api/v2/mix/market/candles?symbol={clean_symbol}&granularity={htf}&limit=200&productType=usdt-futures"
                res_h = requests.get(url_htf_v2, headers=headers, timeout=5, verify=False)
                data_htf = res_h.json()
            except:
                data_htf = {}

        if not data_htf or 'data' not in data_htf or not data_htf['data']:
            df_htf = df_cur.copy()
        else:
            df_htf = pd.DataFrame(data_htf['data'], columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'quoteVol'])
            for col in ['open', 'high', 'low', 'close', 'vol']:
                df_htf[col] = df_htf[col].astype(float)
            df_htf = df_htf.sort_values('ts').reset_index(drop=True)
        
        closes_cur = df_cur['close']
        closes_htf = df_htf['close']
        mark_price = float(df_cur['close'].iloc[-1])
        
        # RSI Current
        delta = closes_cur.diff()
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)
        avg_gain = gain.ewm(com=period-1, adjust=False).mean()
        avg_loss = loss.ewm(com=period-1, adjust=False).mean()
        rs = avg_gain / avg_loss
        rsi_cur = 100 - (100 / (1 + rs.replace(0, np.nan))).fillna(100)
        
        # ATR Current
        high_low = (df_cur['high'].values - df_cur['low'].values)
        high_close = np.abs(df_cur['high'].values - df_cur['close'].shift().values)
        low_close = np.abs(df_cur['low'].values - df_cur['close'].shift().values)
        true_range = np.nanmax([high_low, high_close, low_close], axis=0)
        atr_cur = pd.Series(true_range).rolling(period).mean()

        # 1. VWAP CALCULATION (Institutional Benchmark)
        typical_price = (df_cur['high'] + df_cur['low'] + df_cur['close']) / 3
        vol_sum = df_cur['vol'].cumsum()
        vwap = (typical_price * df_cur['vol']).cumsum() / vol_sum
        last_vwap = round(vwap.iloc[-1], 2) if not vwap.empty else 0
        
        # 2. EMA 200 (Current & HTF) - RESTORED
        ema_200_cur = closes_cur.ewm(span=200, adjust=False).mean()
        ema_200_htf = closes_htf.ewm(span=200, adjust=False).mean()

        # 3. INSTITUTIONAL DATA PREP
        last_candle = df_cur.iloc[-1]
        prev_candle = df_cur.iloc[-2]
        avg_vol = df_cur['vol'].rolling(20).mean().iloc[-1]
        
        # Bullish Sweep: Price drops below prev low then closes back above it
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
            
            # CHoCH: Change of Character (Internal structure break)
            if last_close > recent_highs: choch_bullish = True
            elif last_close < recent_lows: choch_bearish = True
            
            # MSS: Market Structure Shift (Swing break + Volume)
            if choch_bullish and last_candle['vol'] > avg_vol * 1.5: mss_bullish = True
            if choch_bearish and last_candle['vol'] > avg_vol * 1.5: mss_bearish = True

        # 5. FIBONACCI PREDICTIVE LEVELS
        high_p = df_cur['high'].max()
        low_p = df_cur['low'].min()
        diff = high_p - low_p
        fib_618 = high_p - (diff * 0.618)
        fib_ext = high_p + (diff * 0.618) if mss_bullish else low_p - (diff * 0.618)

        # 6. VOLUME-TO-PRICE DIVERGENCE (Whale Accumulation Detector)
        # Logic: Volume surge > 300% but price change < 2% (Whales buying quietly)
        vol_surge = last_candle['vol'] / avg_vol if avg_vol > 0 else 1
        price_change_abs = abs((last_candle['close'] - last_candle['open']) / last_candle['open'] * 100)
        is_whale_accumulation = vol_surge > 3.0 and price_change_abs < 2.0

        # 4. FAIR VALUE GAP (FVG) DETECTION (SMC)
        # Logic: Gap between high of candle 1 and low of candle 3
        fvg_up = []
        if len(df_cur) >= 3:
            for i in range(len(df_cur)-3, len(df_cur)):
                c1, c2, c3 = df_cur.iloc[i-2], df_cur.iloc[i-1], df_cur.iloc[i]
                if c1['high'] < c3['low']: # Bullish FVG
                    fvg_up.append((c1['high'], c3['low']))

        # 5. SESSION AWARENESS (Anti-Prank Guard)
        # Identify London (07:00 UTC) and NY (12:00/13:00 UTC)
        current_hour = time.gmtime().tm_hour
        current_min = time.gmtime().tm_min
        is_session_danger = False
        # Avoid 15 mins around London/NY Open
        if (current_hour == 7 or current_hour == 12 or current_hour == 13) and (current_min < 15 or current_min > 45):
            is_session_danger = True

        # Smart detection
        pattern = detect_candle_patterns(df_cur)
        smc = detect_smart_money_concepts(df_cur)
        inst_flow = detect_institutional_flow(df_cur)
        ob_analysis = get_orderbook_analysis(symbol)
        oi = get_open_interest(symbol)
        funding = get_funding_rate(symbol)
        
        return {
            "mark_price": mark_price,
            "rsi": round(rsi_cur.iloc[-1], 2) if not rsi_cur.empty else 50,
            "atr": round(atr_cur.iloc[-1], 4) if not atr_cur.empty else 0,
            "is_liquidity_sweep": is_sweep,
            "mss_bullish": mss_bullish,
            "mss_bearish": mss_bearish,
            "choch_bullish": choch_bullish,
            "choch_bearish": choch_bearish,
            "fib_618": fib_618,
            "fib_ext": fib_ext,
            "is_whale_accumulation": is_whale_accumulation,
            "fvg_up": fvg_up,
            "is_session_danger": is_session_danger,
            "ema_200": round(ema_200_cur.iloc[-1], 2) if not ema_200_cur.empty else 0,
            "ema_200_htf": round(ema_200_htf.iloc[-1], 2) if not ema_200_htf.empty else 0,
            "candle_pattern": pattern,
            "order_block": smc["ob"],
            "fvg": smc["fvg"],
            "inst_flow": inst_flow,
            "ob_analysis": ob_analysis,
            "open_interest": oi,
            "funding_rate": funding,
            "htf": htf
        }
    except Exception as e:
        print(f"Error indicators for {symbol}: {e}")
        return {}

def get_forex_data(symbol="XAUUSD", interval="15m"):
    """
    Fetch RSI, ATR, OB/FVG indicators for Forex.
    Uses Bitget PAXGUSDT as Gold proxy for SMC indicators.
    Gets exact price from MetaAPI (broker-synced).
    """
    try:
        import os
        token = os.getenv("FOREX_META_API_TOKEN")
        account_id = os.getenv("FOREX_ACCOUNT_ID")
        headers_meta = {"auth-token": token}
        base_url = "https://mt-client-api-v1.london.agiliumtrade.ai"

        # 1. Get real broker price via MetaAPI
        exact_price = 0
        spread = 0
        working_symbol = symbol
        for suffix in ["", "c", ".m"]:
            try:
                sym_try = f"{symbol}{suffix}"
                r = requests.get(
                    f"{base_url}/users/current/accounts/{account_id}/symbols/{sym_try}/current-price",
                    headers=headers_meta, timeout=5
                )
                if r.status_code == 200:
                    d = r.json()
                    bid = float(d.get('bid', 0))
                    ask = float(d.get('ask', 0))
                    if bid > 0:
                        exact_price = bid
                        working_symbol = sym_try
                        if ask > 0:
                            spread = round((ask - bid) * 100, 1)
                        break
            except: continue

        # 2. Get SMC indicators from PAXGUSDT (Gold proxy on Bitget)
        proxy_symbol = "PAXGUSDT"
        indicators = get_technical_indicators(proxy_symbol, interval=interval)
        if not indicators:
            indicators = {"rsi": 50, "atr": 1.5, "order_block": "NONE", "fvg": "NONE", "inst_flow": "NORMAL", "is_liquidity_sweep": False}

        return {
            "symbol": symbol,
            "lastPrice": exact_price if exact_price > 0 else indicators.get("mark_price", 0),
            "spread": spread,
            "rsi": indicators.get("rsi", 50),
            "atr": indicators.get("atr", 1.5),
            "order_block": indicators.get("order_block", "NONE"),
            "fvg": indicators.get("fvg", "NONE"),
            "inst_flow": indicators.get("inst_flow", "NORMAL"),
            "is_liquidity_sweep": indicators.get("is_liquidity_sweep", False),
            "trend": "BULLISH" if exact_price > indicators.get("ema_200", 0) else "BEARISH",
            "ema_200": indicators.get("ema_200", 0),
            "working_symbol": working_symbol
        }
    except Exception as e:
        print(f"Forex fetch error for {symbol}: {e}")
        return {}

def get_idx_market_status():
    from datetime import datetime, time
    import pytz
    
    jakarta_tz = pytz.timezone('Asia/Jakarta')
    now = datetime.now(jakarta_tz)
    
    if now.weekday() >= 5: # Weekend
        return "CLOSED (Weekend)"
        
    current_time = now.time()
    s1_start = time(9, 0)
    s1_end = time(11, 30)
    s2_start = time(13, 30) if now.weekday() != 4 else time(14, 0)
    s2_end = time(16, 0)
    
    if s1_start <= current_time <= s1_end:
        return "OPEN (Session 1)"
    elif s1_end < current_time < s2_start:
        return "CLOSED (Break)"
    elif s2_start <= current_time <= s2_end:
        return "OPEN (Session 2)"
    else:
        return "CLOSED"

def get_retail_sentiment(symbol):
    """
    Fetches Long/Short Ratio from Binance as a proxy for Retail vs Institutional sentiment.
    High L/S Ratio usually means retail is heavy long (potentially a bearish indicator).
    """
    try:
        # Binance Global Futures Data (Public)
        url = f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={symbol}&period=1h&limit=1"
        res = requests.get(url, timeout=5)
        data = res.json()
        if isinstance(data, list) and len(data) > 0:
            ratio = float(data[0]['longShortRatio'])
            sentiment = "Retail Over-Long" if ratio > 2.0 else "Retail Over-Short" if ratio < 0.5 else "Balanced"
            return {"ratio": ratio, "sentiment": sentiment}
        return {"ratio": 1.0, "sentiment": "Neutral"}
    except:
        return {"ratio": 1.0, "sentiment": "Neutral"}

def detect_institutional_flow(df):
    """
    Analyzes volume spikes and price action to detect institutional footprint.
    Institutional bots usually accumulate/distribute without moving price much (Divergence).
    """
    try:
        if len(df) < 20: return "NORMAL"
        
        avg_vol = df['vol'].rolling(window=20).mean().iloc[-1]
        last_vol = df['vol'].iloc[-1]
        last_price_change = abs(df['close'].iloc[-1] - df['open'].iloc[-1])
        avg_price_change = (df['high'] - df['low']).rolling(window=20).mean().iloc[-1]
        
        # Pattern: High Volume, Small Price Change = Institutional Absorption
        if last_vol > avg_vol * 2.5 and last_price_change < avg_price_change * 0.5:
            return "INSTITUTIONAL_ABSORPTION"
        
        # Pattern: High Volume, Significant Price Move from low = Accumulation
        if last_vol > avg_vol * 2.0 and df['close'].iloc[-1] > df['open'].iloc[-1]:
            return "INSTITUTIONAL_ACCUMULATION"
            
        return "RETAIL_DOMINATED"
    except:
        return "NORMAL"

def get_idx_data(interval="15m"):
    """
    IDX Scanner disabled to ensure zero-reliance on TradingView proxies.
    Direct API integration required for future stock expansion.
    """
    return []
