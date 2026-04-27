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
            df = pd.DataFrame(data)
            for col in ['quoteVolume', 'priceChangePercent', 'lastPrice']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            return df
        return pd.DataFrame()
    except Exception as e:
        print(f"Error fetching tickers: {e}")
        return pd.DataFrame()

def get_order_book_details(symbol):
    try:
        url = f"https://data-api.binance.vision/api/v3/depth?symbol={symbol}&limit=50"
        res = requests.get(url)
        data = res.json()
        
        bids = np.array(data.get('bids', []), dtype=float)
        asks = np.array(data.get('asks', []), dtype=float)
        
        if len(bids) == 0 or len(asks) == 0:
            return {"ratio": 1.0, "bid_wall_price": 0, "bid_wall_usdt": 0, "ask_wall_price": 0, "ask_wall_usdt": 0}

        bid_vol = np.sum(bids[:, 1])
        ask_vol = np.sum(asks[:, 1])
        ratio = bid_vol / ask_vol if ask_vol > 0 else 1.0
        
        bid_wall_idx = np.argmax(bids[:, 1])
        ask_wall_idx = np.argmax(asks[:, 1])
        
        return {
            "ratio": round(ratio, 2),
            "bid_wall_price": bids[bid_wall_idx, 0],
            "bid_wall_usdt": bids[bid_wall_idx, 0] * bids[bid_wall_idx, 1],
            "ask_wall_price": asks[ask_wall_idx, 0],
            "ask_wall_usdt": asks[ask_wall_idx, 0] * asks[ask_wall_idx, 1]
        }
    except Exception:
        return {"ratio": 1.0, "bid_wall_price": 0, "bid_wall_usdt": 0, "ask_wall_price": 0, "ask_wall_usdt": 0}

def get_technical_indicators(symbol, interval="15m", period=14):
    try:
        htf_map = {"15m": "1h", "1h": "4h", "4h": "1d", "1d": "1w"}
        htf = htf_map.get(interval, "1h")
        
        url_cur = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit=200"
        res_cur = requests.get(url_cur)
        data_cur = res_cur.json()
        if not isinstance(data_cur, list) or len(data_cur) < period: return {}
        
        df_cur = pd.DataFrame(data_cur, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'q_vol', 'trades', 'taker_base', 'taker_quote', 'ignore'])
        for col in ['open', 'high', 'low', 'close']:
            df_cur[col] = pd.to_numeric(df_cur[col], errors='coerce')
        
        url_htf = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={htf}&limit=200"
        res_htf = requests.get(url_htf)
        data_htf = res_htf.json()
        if not isinstance(data_htf, list): df_htf = df_cur.copy()
        else:
            df_htf = pd.DataFrame(data_htf, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'q_vol', 'trades', 'taker_base', 'taker_quote', 'ignore'])
            for col in ['open', 'high', 'low', 'close']:
                df_htf[col] = pd.to_numeric(df_htf[col], errors='coerce')
        
        closes_cur = df_cur['close']
        closes_htf = df_htf['close']
        
        # RSI
        delta = closes_cur.diff()
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)
        avg_gain = gain.ewm(com=period-1, adjust=False).mean()
        avg_loss = loss.ewm(com=period-1, adjust=False).mean()
        rs = avg_gain / avg_loss
        rsi_cur = 100 - (100 / (1 + rs.replace(0, np.nan))).fillna(100)
        
        # ATR
        high_low = (df_cur['high'] - df_cur['low']).values
        high_close = np.abs(df_cur['high'] - df_cur['close'].shift()).values
        low_close = np.abs(df_cur['low'] - df_cur['close'].shift()).values
        true_range = np.nanmax([high_low, high_close, low_close], axis=0)
        atr_cur = pd.Series(true_range).rolling(period).mean()

        # EMA 200
        ema_200_cur = closes_cur.ewm(span=200, adjust=False).mean()
        ema_200_htf = closes_htf.ewm(span=200, adjust=False).mean()
        
        pattern = detect_candle_patterns(df_cur)
        smc = detect_smart_money_concepts(df_cur)
        
        return {
            "rsi": round(rsi_cur.iloc[-1], 2) if not rsi_cur.empty else 50,
            "atr": round(atr_cur.iloc[-1], 4) if not atr_cur.empty else 0,
            "ema_200": round(ema_200_cur.iloc[-1], 2) if not ema_200_cur.empty else 0,
            "ema_200_htf": round(ema_200_htf.iloc[-1], 2) if not ema_200_htf.empty else 0,
            "candle_pattern": pattern,
            "order_block": smc["ob"],
            "fvg": smc["fvg"],
            "htf": htf
        }
    except Exception as e:
        print(f"Error indicators for {symbol}: {e}")
        return {}

def get_forex_data(timeframe="15m"):
    try:
        pairs = ["EURUSDT", "GBPUSDT", "JPYUSDT", "AUDUSDT", "XAUUSDT"]
        results = []
        for p in pairs:
            url = f"https://data-api.binance.vision/api/v3/ticker/24hr?symbol={p}"
            res = requests.get(url).json()
            if 'lastPrice' in res:
                results.append({
                    "symbol": p.replace("USDT", ""),
                    "lastPrice": float(res['lastPrice']),
                    "priceChangePercent": float(res['priceChangePercent']),
                    "quoteVolume": float(res['quoteVolume'])
                })
        return results
    except Exception:
        return []

def get_idx_data():
    try:
        url = "https://scanner.tradingview.com/indonesia/scanner"
        # Ultra Compatible Payload based on user's browser capture
        payload = {
            "columns": ["ticker-view", "close", "change", "volume", "market_cap_basic"],
            "filter": [{"left": "is_primary", "operation": "equal", "right": True}],
            "ignore_unknown_fields": False,
            "options": {"lang": "id_ID"},
            "range": [0, 15],
            "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"}
        }
        res = requests.post(url, json=payload, timeout=10).json()
        stocks = []
        for item in res.get('data', []):
            d = item['d']
            stocks.append({
                "ticker": item['s'].split(':')[1],
                "close": d[1],
                "change": d[2],
                "volume": d[3],
                "mcap": d[4]
            })
        return stocks
    except Exception as e:
        print(f"IDX Fetch Error: {e}")
        return []

def get_idx_market_status():
    return "OPEN"