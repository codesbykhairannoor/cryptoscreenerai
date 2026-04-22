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
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit=250"
        res = requests.get(url)
        data = res.json()
        
        df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'q_vol', 'trades', 'taker_base', 'taker_quote', 'ignore'])
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        
        closes = df['close']
        
        # RSI
        delta = closes.diff()
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)
        
        avg_gain = gain.ewm(com=period-1, adjust=False).mean()
        avg_loss = loss.ewm(com=period-1, adjust=False).mean()
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        # ATR
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        atr = true_range.rolling(period).mean()

        # EMA 50 & EMA 200
        ema_50 = closes.ewm(span=50, adjust=False).mean()
        ema_200 = closes.ewm(span=200, adjust=False).mean()
        
        return {
            "rsi": round(rsi.iloc[-1], 2),
            "atr": atr.iloc[-1],
            "ema_50": ema_50.iloc[-1],
            "ema_200": ema_200.iloc[-1]
        }
    except Exception as e:
        print(f"Error indicators: {e}")
        return {"rsi": 50.0, "atr": 0.0, "ema_50": 0.0, "ema_200": 0.0}

def get_forex_data(symbol="XAUUSD"):
    try:
        # Use PAXGUSDT for calculating identical momentum/indicators
        url = f"https://data-api.binance.vision/api/v3/klines?symbol=PAXGUSDT&interval=15m&limit=250"
        res = requests.get(url)
        data = res.json()
        
        df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'q_vol', 'trades', 'taker_base', 'taker_quote', 'ignore'])
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        
        closes = df['close']
        
        # RSI
        delta = closes.diff()
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)
        avg_gain = gain.ewm(com=13, adjust=False).mean()
        avg_loss = loss.ewm(com=13, adjust=False).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        rsi_val = round(rsi.iloc[-1], 2)
        
        # ATR
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        atr = true_range.rolling(14).mean()
        atr_val = atr.iloc[-1]
        
        # EMAs for Trend
        ema_200 = closes.ewm(span=200, adjust=False).mean()
        
        # Fetch EXACT MT4 Spot Price from TradingView (OANDA)
        exact_price = closes.iloc[-1] # default fallback
        try:
            tv_url = 'https://scanner.tradingview.com/cfd/scan'
            tv_payload = {'symbols': {'tickers': ['OANDA:XAUUSD']}, 'columns': ['close']}
            tv_res = requests.post(tv_url, json=tv_payload, timeout=5)
            tv_data = tv_res.json()
            if tv_data.get('data') and len(tv_data['data']) > 0:
                exact_price = float(tv_data['data'][0]['d'][0])
        except Exception as e:
            print("Failed to fetch exact TV price, using fallback:", e)
        
        return {
            "symbol": "XAUUSD",
            "lastPrice": exact_price,
            "rsi_15m": rsi_val,
            "atr": atr_val,
            "ema_200": ema_200.iloc[-1]
        }
    except Exception as e:
        print(f"Error fetching forex data for {symbol}: {e}")
        return None