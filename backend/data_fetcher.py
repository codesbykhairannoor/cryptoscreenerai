import requests
import pandas as pd
import yfinance as yf
import numpy as np

def fetch_all_tickers():
    url = "https://data-api.binance.vision/api/v3/ticker/24hr"
    response = requests.get(url)
    data = response.json()

    df = pd.DataFrame(data)
    df = df[df['symbol'].str.endswith('USDT')]

    df['lastPrice'] = df['lastPrice'].astype(float)
    df['priceChangePercent'] = df['priceChangePercent'].astype(float)
    df['volume'] = df['volume'].astype(float)
    df['quoteVolume'] = df['quoteVolume'].astype(float)

    df = df[df['quoteVolume'] > 50000]
    return df

def get_order_book_details(symbol):
    try:
        url = f"https://data-api.binance.vision/api/v3/depth?symbol={symbol}&limit=20"
        res = requests.get(url)
        data = res.json()
        
        bids = data['bids']
        asks = data['asks']

        bid_vol = sum([float(b[1]) for b in bids])
        ask_vol = sum([float(a[1]) for a in asks])
        ratio = bid_vol / ask_vol if ask_vol > 0 else 0
        
        top_bid = max(bids, key=lambda x: float(x[0]) * float(x[1]))
        top_ask = max(asks, key=lambda x: float(x[0]) * float(x[1]))

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
        df_cur = pd.DataFrame(res_cur.json(), columns=['time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'q_vol', 'trades', 'taker_base', 'taker_quote', 'ignore'])
        df_cur['close'] = df_cur['close'].astype(float)
        df_cur['high'] = df_cur['high'].astype(float)
        df_cur['low'] = df_cur['low'].astype(float)
        
        # Fetch HTF data for MTF Trend
        url_htf = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={htf}&limit=200"
        res_htf = requests.get(url_htf)
        df_htf = pd.DataFrame(res_htf.json(), columns=['time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'q_vol', 'trades', 'taker_base', 'taker_quote', 'ignore'])
        df_htf['close'] = df_htf['close'].astype(float)
        
        closes_cur = df_cur['close']
        closes_htf = df_htf['close']
        
        # RSI Current
        delta = closes_cur.diff()
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)
        avg_gain = gain.ewm(com=period-1, adjust=False).mean()
        avg_loss = loss.ewm(com=period-1, adjust=False).mean()
        rs = avg_gain / avg_loss
        rsi_cur = 100 - (100 / (1 + rs))
        
        # ATR Current
        high_low = df_cur['high'] - df_cur['low']
        high_close = (df_cur['high'] - df_cur['close'].shift()).abs()
        low_close = (df_cur['low'] - df_cur['close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        atr_cur = true_range.rolling(period).mean()

        # EMA 200 (Current & HTF)
        ema_200_cur = closes_cur.ewm(span=200, adjust=False).mean()
        ema_200_htf = closes_htf.ewm(span=200, adjust=False).mean()
        
        return {
            "rsi": round(rsi_cur.iloc[-1], 2),
            "atr": atr_cur.iloc[-1],
            "ema_200": ema_200_cur.iloc[-1],
            "ema_200_htf": ema_200_htf.iloc[-1],
            "htf": htf
        }
    except Exception as e:
        print(f"Error indicators for {symbol}: {e}")
        return {"rsi": 50.0, "atr": 0.0, "ema_200": 0.0, "ema_200_htf": 0.0, "htf": "1h"}

def get_forex_data(symbol="XAUUSD", interval="15m"):
    try:
        # Use PAXGUSDT as momentum proxy for Gold
        indicators = get_technical_indicators("PAXGUSDT", interval=interval)
        
        # Fetch EXACT Spot Price from TradingView (OANDA)
        exact_price = 0
        try:
            tv_url = 'https://scanner.tradingview.com/cfd/scan'
            tv_payload = {'symbols': {'tickers': [f'OANDA:{symbol}']}, 'columns': ['close']}
            tv_res = requests.post(tv_url, json=tv_payload, timeout=5)
            tv_data = tv_res.json()
            if tv_data.get('data') and len(tv_data['data']) > 0:
                exact_price = float(tv_data['data'][0]['d'][0])
        except Exception as e:
            print("Failed to fetch exact TV price, using indicators proxy price:", e)
        
        return {
            "symbol": symbol,
            "lastPrice": exact_price if exact_price > 0 else indicators.get("ema_200", 0),
            **indicators
        }
    except Exception as e:
        print(f"Forex fetch error: {e}")
        return {}

def get_idx_market_status():
    from datetime import datetime, time
    import pytz
    
    jakarta_tz = pytz.timezone('Asia/Jakarta')
    now = datetime.now(jakarta_tz)
    
    # Monday = 0, Sunday = 6
    if now.weekday() >= 5: # Weekend
        return "CLOSED (Weekend)"
        
    current_time = now.time()
    
    # Session 1: 09:00 - 11:30
    # Session 2: 13:30 - 16:00 (Fri 14:00 - 16:00)
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

def get_idx_data(interval="15m"):
    try:
        tv_url = 'https://scanner.tradingview.com/indonesia/scan'
        payload = {
            "filter": [
                {"left": "is_primary", "operation": "equal", "right": True},
                {"left": "type", "operation": "in_range", "right": ["stock", "dr", "fund"]},
                {"left": "close", "operation": "greater", "right": 50}
            ],
            "options": {"lang": "id_ID"},
            "markets": ["indonesia"],
            "symbols": {"query": {"types": []}, "tickers": []},
            "columns": [
                "name", "close", "change", "volume", "relative_volume_10d_calc",
                "market_cap_basic", "bid_size", "ask_size", "RSI", "ATR", 
                "EMA200", "ChaikinMoneyFlow", "description"
            ],
            "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
            "range": [0, 100]
        }
        
        res = requests.post(tv_url, json=payload, timeout=5)
        data = res.json()
        
        raw_stocks = data.get('data') or []
        print(f"IDX Fetch: Found {len(raw_stocks)} stocks using official filters")
        
        results = []
        for item in raw_stocks:
            symbol = item['s'].split(':')[-1]
            cols = item['d']
            
            # Map columns safely
            # 0: name, 1: close, 2: change, 3: volume, 4: rel_vol, 5: mkt_cap,
            # 6: bid_size, 7: ask_size, 8: RSI, 9: ATR, 10: EMA200, 11: CMF, 12: desc
            
            last_price = cols[1] or 0
            if last_price == 0: continue
            
            bid_size = cols[6] or 0
            ask_size = cols[7] or 0
            
            # Handle Market Closed for Bid/Ask
            if bid_size == 0 and ask_size == 0:
                bid_ask_ratio = 1.0
            else:
                bid_ask_ratio = bid_size / ask_size if ask_size > 0 else 2.0
                
            rel_vol = cols[4] or 0
            cmf = cols[11] or 0
            rsi = cols[8] or 50.0
            atr = cols[9] or (last_price * 0.02)
            ema_200 = cols[10] or last_price
            
            demand_score = 0
            if bid_ask_ratio > 1.5: demand_score += 40
            elif bid_ask_ratio > 1.0: demand_score += 20
            if rel_vol > 1.2: demand_score += 30
            if cmf > 0: demand_score += 30
            
            results.append({
                "symbol": symbol,
                "name": cols[0],
                "lastPrice": last_price,
                "change": cols[2],
                "rsi": rsi,
                "atr": atr,
                "ema_200": ema_200,
                "ema_200_htf": ema_200,
                "volume": cols[3] or 0,
                "bid_size": bid_size,
                "ask_size": ask_size,
                "avg_volume": (cols[3] / rel_vol) if rel_vol > 0 else 1,
                "relative_volume": rel_vol,
                "cmf": cmf,
                "demand_score": demand_score,
                "htf": "1h"
            })
        
        results.sort(key=lambda x: x['demand_score'], reverse=True)
        return results[:40]
    except Exception as e:
        print(f"Error fetching IDX data: {e}")
        return []
        
        # Sort by demand score to show the "Best" stocks first
        results.sort(key=lambda x: x['demand_score'], reverse=True)
        return results[:30] # Return top 30 highest demand stocks
    except Exception as e:
        print(f"Error fetching IDX data: {e}")
        return []