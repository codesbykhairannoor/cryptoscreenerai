import requests
import pandas as pd
import numpy as np
from patterns import detect_candle_patterns, detect_smart_money_concepts

def fetch_all_tickers():
    try:
        url = "https://data-api.binance.vision/api/v3/ticker/24hr"
        res = requests.get(url)
        data = res.json()
        if isinstance(data, list):
            # FILTER: Only USDT pairs and exclude leveraged tokens/fiat pairs
            filtered_data = [
                d for d in data 
                if d['symbol'].endswith('USDT') 
                and not any(x in d['symbol'] for x in ['UPUSDT', 'DOWNUSDT', 'RUB', 'GBP', 'EUR', 'AUD', 'FDUSD', 'TUSD', 'BUSD', 'DAI'])
            ]
            df = pd.DataFrame(filtered_data)
            for col in ['quoteVolume', 'priceChangePercent', 'lastPrice']:
                df[col] = pd.to_numeric(df[col], errors='coerce').astype(float)
            return df
        return pd.DataFrame()
    except Exception as e:
        print(f"Error fetching tickers: {e}")
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
        # Determine Higher Timeframe (HTF) for confirmation
        htf_map = {"15m": "1h", "1h": "4h", "4h": "1d", "1d": "1w"}
        htf = htf_map.get(interval, "1h")
        
        # Fetch Current Interval data
        url_cur = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit=200"
        res_cur = requests.get(url_cur)
        data_cur = res_cur.json()
        if not isinstance(data_cur, list) or len(data_cur) < period: return {}

        df_cur = pd.DataFrame(data_cur, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'q_vol', 'trades', 'taker_base', 'taker_quote', 'ignore'])
        for col in ['open', 'high', 'low', 'close', 'vol']:
            df_cur[col] = pd.to_numeric(df_cur[col], errors='coerce').astype(float)
        
        # Fetch HTF data for MTF Trend
        url_htf = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={htf}&limit=200"
        res_htf = requests.get(url_htf)
        data_htf = res_htf.json()
        if not isinstance(data_htf, list): 
            df_htf = df_cur.copy()
        else:
            df_htf = pd.DataFrame(data_htf, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'q_vol', 'trades', 'taker_base', 'taker_quote', 'ignore'])
            for col in ['open', 'high', 'low', 'close']:
                df_htf[col] = pd.to_numeric(df_htf[col], errors='coerce').astype(float)
        
        closes_cur = df_cur['close']
        closes_htf = df_htf['close']
        
        # RSI Current
        delta = closes_cur.diff()
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)
        avg_gain = gain.ewm(com=period-1, adjust=False).mean()
        avg_loss = loss.ewm(com=period-1, adjust=False).mean()
        rs = avg_gain / avg_loss
        rsi_cur = 100 - (100 / (1 + rs.replace(0, np.nan))).fillna(100)
        
        # ATR Current (Robust calc to avoid ufunc error)
        high_low = (df_cur['high'].values - df_cur['low'].values)
        high_close = np.abs(df_cur['high'].values - df_cur['close'].shift().values)
        low_close = np.abs(df_cur['low'].values - df_cur['close'].shift().values)
        true_range = np.nanmax([high_low, high_close, low_close], axis=0)
        atr_cur = pd.Series(true_range).rolling(period).mean()


        # 1. VWAP CALCULATION (Institutional Benchmark)
        # Formula: cumulative(typical_price * volume) / cumulative(volume)
        typical_price = (df_cur['high'] + df_cur['low'] + df_cur['close']) / 3
        vwap = (typical_price * df_cur['vol']).cumsum() / df_cur['vol'].cumsum()
        last_vwap = round(vwap.iloc[-1], 2)
        
        # 2. LIQUIDITY SWEEP DETECTION (Anti-Stop Hunt)
        # Logic: Price dips below previous low but closes back above with volume
        last_candle = df_cur.iloc[-1]
        prev_candle = df_cur.iloc[-2]
        avg_vol = df_cur['vol'].rolling(20).mean().iloc[-1]
        is_sweep = False
        if last_candle['low'] < prev_candle['low'] and last_candle['close'] > prev_candle['low']:
            if float(last_candle['vol']) > float(avg_vol) * 1.5: # Volume confirmation
                is_sweep = True

        # Smart detection
        pattern = detect_candle_patterns(df_cur)
        smc = detect_smart_money_concepts(df_cur)
        inst_flow = detect_institutional_flow(df_cur)
        
        return {
            "rsi": round(rsi_cur.iloc[-1], 2) if not rsi_cur.empty else 50,
            "atr": round(atr_cur.iloc[-1], 4) if not atr_cur.empty else 0,
            "vwap": last_vwap,
            "vwap_dist": round((closes_cur.iloc[-1] - last_vwap) / last_vwap * 100, 2),
            "is_liquidity_sweep": is_sweep,
            "ema_200": round(ema_200_cur.iloc[-1], 2) if not ema_200_cur.empty else 0,
            "ema_200_htf": round(ema_200_htf.iloc[-1], 2) if not ema_200_htf.empty else 0,
            "candle_pattern": pattern,
            "order_block": smc["ob"],
            "fvg": smc["fvg"],
            "inst_flow": inst_flow,
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