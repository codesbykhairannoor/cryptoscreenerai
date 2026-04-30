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
        print(f"⚠️ [ORDERBOOK ERROR] {symbol}: {e}")
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
        print(f"🌡️ [SENSORS] Funding Rate {symbol}: {round(rate * 100, 4)}%")
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
        print(f"🎯 [SENSORS] Open Interest {symbol}: ${round(oi/1e6, 2)}M")
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
            print(f"📊 [MARKET] Berhasil memetakan {len(df)} ticker dari Bitget.")
            return df
    except Exception as e:
        print(f"❌ [BITGET FETCH ERROR] {e}")
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
        print(f"❌ [DATA FETCH ERROR] {symbol}: {e}")
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

        # 1. Fetch Current Interval from BITGET
        url_cur = f"https://api.bitget.com/api/v3/market/candles?symbol={clean_symbol}&granularity={bg_interval}&limit=200&category=USDT-FUTURES"
        res_cur = requests.get(url_cur, timeout=5)
        data_cur = res_cur.json()
        if not data_cur or 'data' not in data_cur or not data_cur['data']: 
            print(f"⏳ [DATA] Sinkronisasi data {clean_symbol} tertunda...")
            return {}
        
        # Bitget Format: [ts, open, high, low, close, vol, qvol]
        df_cur = pd.DataFrame(data_cur['data'], columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'quoteVol'])
        for col in ['open', 'high', 'low', 'close', 'vol']:
            df_cur[col] = df_cur[col].astype(float)
        if len(df_cur) < 5: return {}

        # 2. Fetch HTF from BITGET
        url_htf = f"https://api.bitget.com/api/v3/market/candles?symbol={clean_symbol}&granularity={htf}&limit=200&category=USDT-FUTURES"
        res_htf = requests.get(url_htf, timeout=5)
        data_htf = res_htf.json()
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
        
        # 4. VOLUME-TO-PRICE DIVERGENCE (Whale Accumulation Detector)
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
            "vwap": last_vwap,
            "vwap_dist": round((closes_cur.iloc[-1] - last_vwap) / last_vwap * 100, 2) if last_vwap > 0 else 0,
            "is_liquidity_sweep": is_sweep,
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
    try:
        # Determine TV Ticker
        tv_ticker = f"OANDA:{symbol}"
        if symbol == "DXY": tv_ticker = "TVC:DXY"
        
        # Use PAXGUSDT as momentum proxy for Gold, or some other stable proxy if needed
        proxy_symbol = "PAXGUSDT" if symbol == "XAUUSD" else "BTCUSDT"
        indicators = get_technical_indicators(proxy_symbol, interval=interval)
        
        # Fetch EXACT Spot Price from TradingView
        exact_price = 0
        spread = 0
        try:
            tv_url = 'https://scanner.tradingview.com/cfd/scan'
            # Fetch Bid/Ask for spread calculation
            tv_payload = {
                'symbols': {'tickers': [tv_ticker]}, 
                'columns': ['close', 'bid', 'ask', 'change', 'EMA200']
            }
            tv_res = requests.post(tv_url, json=tv_payload, timeout=5)
            tv_data = tv_res.json()
            if tv_data.get('data') and len(tv_data['data']) > 0:
                cols = tv_data['data'][0]['d']
                exact_price = float(cols[0])
                bid = float(cols[1] or 0)
                ask = float(cols[2] or 0)
                ema200 = float(cols[4] or 0)
                
                if bid > 0 and ask > 0:
                    # Calculate spread in pips (e.g. 1950.10 - 1950.05 = 0.05 = 5 pips)
                    spread = round((ask - bid) * 100, 1) if "XAU" in symbol else round((ask-bid)*10000, 1)

                # Determine Trend based on EMA200
                trend = "NEUTRAL"
                if exact_price > ema200 * 1.001: trend = "BULLISH"
                elif exact_price < ema200 * 0.999: trend = "BEARISH"
                
                indicators['trend'] = trend
                indicators['price_change_5m'] = float(cols[3] or 0)
                indicators['spread'] = spread
                indicators['ema_200'] = ema200
        except Exception as e:
            print(f"Failed to fetch TV data for {symbol}: {e}")
        
        if not indicators:
            indicators = {"rsi": 50, "atr": 1.5, "trend": "NEUTRAL", "spread": 0}

        return {
            "symbol": symbol,
            "lastPrice": exact_price if exact_price > 0 else indicators.get("ema_200", 0),
            **indicators
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
    try:
        tv_url = 'https://scanner.tradingview.com/indonesia/scan'
        payload = {
            "columns": [
                "name", "close", "change", "volume", "relative_volume_10d_calc", 
                "market_cap_basic", "description"
            ],
            "filter": [
                {"left": "is_primary", "operation": "equal", "right": True}
            ],
            "ignore_unknown_fields": False,
            "options": {"lang": "id_ID"},
            "range": [0, 100],
            "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
            "markets": ["indonesia"]
        }
        
        res = requests.post(tv_url, json=payload, timeout=5)
        data = res.json()
        
        raw_stocks = data.get('data') or []
        print(f"IDX Fetch: Found {len(raw_stocks)} stocks")
        
        results = []
        for item in raw_stocks:
            symbol = item['s'].split(':')[-1]
            cols = item['d']
            
            last_price = cols[1] or 0
            if last_price == 0: continue
            
            rel_vol = cols[4] or 0
            change = cols[2] or 0
            mkt_cap = cols[5] or 0
            
            demand_score = 0
            if rel_vol > 2.0: demand_score += 40
            elif rel_vol > 1.2: demand_score += 20
            
            if change > 3.0: demand_score += 40
            elif change > 0: demand_score += 20
            
            if mkt_cap > 1e12: demand_score += 20
            
            rsi = 50 + (change * 2) 
            rsi = max(min(rsi, 85), 15)
            
            results.append({
                "symbol": symbol,
                "name": cols[0],
                "lastPrice": last_price,
                "change": change,
                "rsi": rsi,
                "atr": last_price * 0.02,
                "ema_200": last_price,
                "ema_200_htf": last_price,
                "volume": cols[3] or 0,
                "relative_volume": rel_vol,
                "demand_score": demand_score,
                "htf": "1h",
                "candle_pattern": "NONE",
                "order_block": "NONE",
                "fvg": "NONE"
            })
        
        results.sort(key=lambda x: x['demand_score'], reverse=True)
        return results[:15] 
    except Exception as e:
        print(f"Error fetching IDX data: {e}")
        return []