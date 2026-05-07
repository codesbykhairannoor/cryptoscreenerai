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

def detect_demand_supply_zones(df):
    """
    Deteksi Demand Zone (untuk BUY) dan Supply Zone (untuk SELL).

    Algoritma:
    1. Cari area konsolidasi: 3+ candle berturut-turut dengan range < 40% ATR
    2. Setelah konsolidasi, cek apakah ada impulse candle > 1.5x ATR
       - Impulse naik setelah konsolidasi = DEMAND ZONE (institusi akumulasi)
       - Impulse turun setelah konsolidasi = SUPPLY ZONE (institusi distribusi)
    3. Kalau harga sekarang kembali ke zona tersebut = sinyal entry

    Return:
      demand_zone : {"active": bool, "top": float, "bottom": float, "strength": int}
      supply_zone : {"active": bool, "top": float, "bottom": float, "strength": int}
      in_demand   : True kalau harga sekarang di dalam demand zone
      in_supply   : True kalau harga sekarang di dalam supply zone
    """
    result = {
        "demand_zone": {"active": False, "top": 0, "bottom": 0, "strength": 0},
        "supply_zone": {"active": False, "top": 0, "bottom": 0, "strength": 0},
        "in_demand":   False,
        "in_supply":   False,
    }

    if len(df) < 15:
        return result

    highs  = df['high'].tolist()
    lows   = df['low'].tolist()
    closes = df['close'].tolist()
    opens  = df['open'].tolist()
    n      = len(closes)

    # Hitung ATR untuk threshold konsolidasi
    trs = []
    for i in range(1, n):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i]  - closes[i-1]))
        trs.append(tr)
    atr = sum(trs[-14:]) / 14 if len(trs) >= 14 else (sum(trs) / len(trs) if trs else 0.001)

    current_price = closes[-1]
    consolidation_threshold = atr * 0.4   # Range candle < 40% ATR = konsolidasi
    impulse_threshold       = atr * 1.5   # Body candle > 150% ATR = impulse

    # Scan dari candle ke-3 sampai ke-2 dari belakang (bukan candle terakhir)
    # Cari pola: konsolidasi (3+ candle) → impulse
    for i in range(3, n - 1):
        # Cek apakah candle i adalah impulse
        body_i = abs(closes[i] - opens[i])
        if body_i < impulse_threshold:
            continue

        # Cek apakah 3 candle sebelumnya adalah konsolidasi
        consol_start = max(0, i - 5)
        consol_candles = []
        for j in range(consol_start, i):
            candle_range = highs[j] - lows[j]
            if candle_range <= consolidation_threshold:
                consol_candles.append(j)

        if len(consol_candles) < 2:
            continue

        # Ada konsolidasi sebelum impulse — tentukan zona
        zone_top    = max(highs[j] for j in consol_candles)
        zone_bottom = min(lows[j]  for j in consol_candles)
        strength    = len(consol_candles)  # Lebih banyak candle = zona lebih kuat

        if closes[i] > opens[i]:
            # Impulse naik = DEMAND ZONE
            # Simpan zona yang paling dekat dengan harga sekarang
            if not result["demand_zone"]["active"] or \
               abs(current_price - zone_top) < abs(current_price - result["demand_zone"]["top"]):
                result["demand_zone"] = {
                    "active":   True,
                    "top":      round(zone_top, 6),
                    "bottom":   round(zone_bottom, 6),
                    "strength": strength,
                }
        else:
            # Impulse turun = SUPPLY ZONE
            if not result["supply_zone"]["active"] or \
               abs(current_price - zone_bottom) < abs(current_price - result["supply_zone"]["bottom"]):
                result["supply_zone"] = {
                    "active":   True,
                    "top":      round(zone_top, 6),
                    "bottom":   round(zone_bottom, 6),
                    "strength": strength,
                }

    # Cek apakah harga sekarang di dalam zona
    dz = result["demand_zone"]
    sz = result["supply_zone"]

    # Harga di demand zone: dalam range zona atau sedikit di bawah (max 0.5 ATR)
    if dz["active"] and dz["bottom"] - atr * 0.5 <= current_price <= dz["top"] + atr * 0.3:
        result["in_demand"] = True

    # Harga di supply zone: dalam range zona atau sedikit di atas (max 0.5 ATR)
    if sz["active"] and sz["bottom"] - atr * 0.3 <= current_price <= sz["top"] + atr * 0.5:
        result["in_supply"] = True

    return result


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
    if len(df) < 20: return "NORMAL"
    avg_vol = df['vol'].rolling(20).mean().iloc[-1]
    last_vol = df['vol'].iloc[-1]
    last_close = df['close'].iloc[-1]
    last_open = df['open'].iloc[-1]
    
    if last_vol > avg_vol * 2.5:
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
                if size_usd > 50000:
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
    ULTIMATE INDICATOR ENGINE v5.1: SMC + Order Flow + Predictive Structure
    """
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&granularity={interval}&limit=100&productType=USDT-FUTURES"
        r = requests.get(url, timeout=10, verify=False)
        if r.status_code != 200: return {}
        
        data = r.json().get('data', [])
        df_cur = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'vol_usd'])
        df_cur[['open', 'high', 'low', 'close', 'vol']] = df_cur[['open', 'high', 'low', 'close', 'vol']].astype(float)
        
        # 1. EMA & TREND
        mark_price = df_cur['close'].iloc[-1]
        ema_200_cur = df_cur['close'].ewm(span=200, adjust=False).mean()
        
        # 2. HTF CONTEXT (1H)
        url_htf = f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&granularity=1h&limit=100&productType=USDT-FUTURES"
        r_htf = requests.get(url_htf, timeout=5, verify=False)
        ema_200_htf_val = 0
        if r_htf.status_code == 200:
            data_htf = r_htf.json().get('data', [])
            df_htf = pd.DataFrame(data_htf, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'vol_usd'])
            df_htf['close'] = df_htf['close'].astype(float)
            ema_htf = df_htf['close'].ewm(span=200, adjust=False).mean()
            ema_200_htf_val = ema_htf.iloc[-1] if len(ema_htf) > 0 else 0

        # 3. LIQUIDITY SWEEPS
        last_candle = df_cur.iloc[-1]
        prev_candle = df_cur.iloc[-2]
        avg_vol = df_cur['vol'].rolling(20).mean().iloc[-1]
        is_bull_sweep = last_candle['low'] < prev_candle['low'] and last_candle['close'] > prev_candle['low']
        is_bear_sweep = last_candle['high'] > prev_candle['high'] and last_candle['close'] < prev_candle['high']
        
        # 4. MARKET STRUCTURE SHIFT (MSS)
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

        # 5. PREDICTIVE FIB
        high_p = df_cur['high'].max()
        low_p = df_cur['low'].min()
        diff = high_p - low_p
        fib_ext = high_p + (diff * 0.618) if mss_bullish else low_p - (diff * 0.618)

        # 6. WHALE & OBI
        obi = get_orderbook_imbalance(symbol)
        whale_sig = detect_whale_activity(symbol) # Smart detection
        pattern = detect_candle_patterns(df_cur)
        smc = detect_smart_money_concepts(df_cur)
        inst_flow = detect_institutional_flow(df_cur)
        dsz = detect_demand_supply_zones(df_cur)  # Demand/Supply Zones

        # 7. ATR 14 (True Range)
        trs = []
        for i in range(1, len(df_cur)):
            high_i  = df_cur['high'].iloc[i]
            low_i   = df_cur['low'].iloc[i]
            close_p = df_cur['close'].iloc[i - 1]
            tr = max(high_i - low_i, abs(high_i - close_p), abs(low_i - close_p))
            trs.append(tr)
        atr_val = round(sum(trs[-14:]) / 14, 6) if len(trs) >= 14 else round(mark_price * 0.015, 6)

        # 8. RSI 14
        closes_list = df_cur['close'].tolist()
        rsi_gains, rsi_losses = [], []
        for i in range(1, len(closes_list)):
            diff = closes_list[i] - closes_list[i - 1]
            rsi_gains.append(max(diff, 0))
            rsi_losses.append(max(-diff, 0))
        rsi_period = 14
        rsi_avg_gain = sum(rsi_gains[:rsi_period]) / rsi_period
        rsi_avg_loss = sum(rsi_losses[:rsi_period]) / rsi_period
        for i in range(rsi_period, len(rsi_gains)):
            rsi_avg_gain = (rsi_avg_gain * (rsi_period - 1) + rsi_gains[i]) / rsi_period
            rsi_avg_loss = (rsi_avg_loss * (rsi_period - 1) + rsi_losses[i]) / rsi_period
        rsi_val = round(100 - (100 / (1 + rsi_avg_gain / rsi_avg_loss)), 2) if rsi_avg_loss > 0 else 100.0

        return {
            "mark_price": mark_price,
            "rsi": rsi_val,
            "atr": atr_val,
            "candle_pattern": pattern,
            "is_liquidity_sweep": is_bull_sweep or is_bear_sweep,
            "mss_bullish": mss_bullish,
            "mss_bearish": mss_bearish,
            "choch_bullish": choch_bullish,
            "choch_bearish": choch_bearish,
            "fib_ext": round(fib_ext, 4),
            "obi": obi,
            "whale_signal": whale_sig,
            "order_block": smc["ob"],
            "fvg": smc["fvg"],
            "inst_flow": inst_flow,
            "demand_zone":  dsz["demand_zone"],
            "supply_zone":  dsz["supply_zone"],
            "in_demand":    dsz["in_demand"],
            "in_supply":    dsz["in_supply"],
            "ema_200": round(ema_200_cur.iloc[-1], 2) if len(ema_200_cur) > 0 else 0,
            "ema_200_htf": round(ema_200_htf_val, 2),
            "open_interest": get_open_interest(symbol),
            "funding_rate": get_funding_rate(symbol),
            "htf": "1h"
        }
    except Exception as e:
        print(f"Error indicators for {symbol}: {e}")
        return {}

def fetch_all_tickers():
    """Fetches all USDT-FUTURES tickers from Bitget"""
    try:
        url = "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
        r = requests.get(url, timeout=10, verify=False)
        if r.status_code == 200:
            return r.json().get('data', [])
    except: pass
    return []

def get_order_book_details(symbol):
    """Alias for OBI calculation needed by main.py"""
    ratio = get_orderbook_imbalance(symbol)
    return {"ratio": ratio}

def get_retail_sentiment(symbol):
    """Placeholder for retail sentiment analysis"""
    return {"sentiment": "Neutral", "score": 0.5}

def get_idx_data():
    """Placeholder for IDX market data"""
    return []

def get_idx_market_status():
    """Placeholder for IDX market status"""
    return {"status": "CLOSED", "message": "IDX Market is currently closed"}

def get_defillama_metrics(protocol="aave"):
    """Fetch On-Chain metrics from DefiLlama (FREE API)"""
    try:
        url = f"https://api.llama.fi/protocol/{protocol}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            tvl_list = data.get('tvl', [])
            if not tvl_list: return {"tvl": 0, "tvl_change_24h": 0}
            current_tvl = tvl_list[-1].get('totalLiquidityUSD', 0)
            tvl_change_pct = 0
            if len(tvl_list) >= 2:
                prev_tvl = tvl_list[-2].get('totalLiquidityUSD', 0)
                tvl_change_pct = ((current_tvl - prev_tvl) / prev_tvl * 100) if prev_tvl > 0 else 0
            return {"tvl": current_tvl, "tvl_change_24h": round(tvl_change_pct, 2)}
    except: pass
    return {"tvl": 0, "tvl_change_24h": 0}

def get_forex_data(symbol="XAUUSD", interval="15m"):
    """ULTIMATE FOREX ENGINE: MetaAPI Price + PAXG Proxy Indicators"""
    try:
        token = os.getenv("FOREX_META_API_TOKEN")
        account_id = os.getenv("FOREX_ACCOUNT_ID")
        headers_meta = {"auth-token": token}
        base_url = "https://mt-client-api-v1.london.agiliumtrade.ai"
        
        exact_price = 0
        working_symbol = symbol
        for suffix in ["", "c", ".m"]:
            try:
                sym_try = f"{symbol}{suffix}"
                r = requests.get(f"{base_url}/users/current/accounts/{account_id}/symbols/{sym_try}/current-price", headers=headers_meta, timeout=5)
                if r.status_code == 200:
                    d = r.json()
                    if float(d.get('bid', 0)) > 0:
                        exact_price = float(d.get('bid', 0))
                        working_symbol = sym_try
                        break
            except: continue

        indicators = get_technical_indicators("PAXGUSDT", interval=interval)
        
        # Calculate Trend based on EMA 200
        last_price = exact_price if exact_price > 0 else indicators.get("mark_price", 0)
        ema_200 = indicators.get("ema_200", 0)
        trend = "NEUTRAL"
        if last_price > ema_200 and ema_200 > 0: trend = "BULLISH"
        elif last_price < ema_200 and ema_200 > 0: trend = "BEARISH"
        
        # Spread calculation (simplified if not available from MetaAPI)
        spread = 50 # Default safe spread
        
        return {
            "symbol": symbol,
            "lastPrice": last_price,
            "rsi": indicators.get("rsi", 50),
            "order_block": indicators.get("order_block", "NONE"),
            "fvg": indicators.get("fvg", "NONE"),
            "inst_flow": indicators.get("inst_flow", "NORMAL"),
            "obi": indicators.get("obi", 0),
            "whale_signal": indicators.get("whale_signal", "NORMAL"),
            "is_liquidity_sweep": indicators.get("is_liquidity_sweep", False),
            "mss_bullish": indicators.get("mss_bullish", False),
            "mss_bearish": indicators.get("mss_bearish", False),
            "choch_bullish": indicators.get("choch_bullish", False),
            "choch_bearish": indicators.get("choch_bearish", False),
            "fib_ext": indicators.get("fib_ext", 0),
            "trend": trend,
            "dxy_trend": trend if symbol == "DXY" else "NEUTRAL",
            "spread": spread,
            "working_symbol": working_symbol
        }
    except Exception as e:
        print(f"Error Forex indicators: {e}")
        return {}

def get_dune_macro_metrics():
    """Fetch Macro On-Chain metrics from Dune Analytics"""
    try:
        api_key = os.getenv("DUNE_API_KEY")
        if not api_key: return {"macro_sentiment": "NEUTRAL"}
        query_id = 3403
        url = f"https://api.dune.com/api/v1/query/{query_id}/results/latest"
        headers = {"X-Dune-API-Key": api_key}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            rows = data.get('result', {}).get('rows', [])
            if rows:
                latest = rows[0]
                return {
                    "stablecoin_supply": latest.get('total_supply', 0),
                    "macro_trend": "BULLISH" if latest.get('change_7d', 0) > 0 else "BEARISH"
                }
    except: pass
    return {"macro_sentiment": "NEUTRAL"}

if __name__ == "__main__":
    print(get_technical_indicators("BTCUSDT"))
    print(get_defillama_metrics("aave"))
    print(get_dune_macro_metrics())
