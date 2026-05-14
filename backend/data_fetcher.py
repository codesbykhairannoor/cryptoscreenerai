import requests
import pandas as pd
import numpy as np
import time
import os
import threading

# Global cache for HTF indicators to reduce API load
_htf_cache = {}
_htf_lock = threading.Lock()
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
#  WS CACHE HELPERS
#  Semua fungsi REST di bawah ini akan cek shared_state (WS cache) dulu.
#  Kalau data WS fresh (< TTL), pakai itu. Kalau stale/kosong, fallback REST.
#  Ini setara CoinAPI real-time feed tapi gratis via Bitget WS.
# ─────────────────────────────────────────────────────────────────────────────
WS_TICKER_TTL = 10   # detik — ticker update setiap ~100ms via WS
WS_DEPTH_TTL  = 5    # detik — order book update setiap ~200ms via WS


def _ws_state():
    """Lazy import shared_state untuk hindari circular import."""
    try:
        from shared_state import state
        return state
    except Exception:
        return None


def _ws_price(symbol: str) -> float:
    """Ambil harga real-time dari WS cache. Return 0 kalau tidak ada."""
    s = _ws_state()
    if s and symbol in s.rt_price:
        ts = s.rt_ticker_ts.get(symbol, 0)
        if time.time() - ts < WS_TICKER_TTL:
            return s.rt_price[symbol]
    return 0.0


def _ws_obi(symbol: str) -> float:
    """Ambil OBI dari WS cache. Return None kalau tidak ada/stale."""
    s = _ws_state()
    if s and symbol in s.rt_obi:
        ts = s.rt_depth_ts.get(symbol, 0)
        if time.time() - ts < WS_DEPTH_TTL:
            return s.rt_obi[symbol]
    return None


def _ws_whale(symbol: str) -> str:
    """Ambil whale signal dari WS cache."""
    s = _ws_state()
    if s and symbol in s.rt_whale:
        return s.rt_whale[symbol]
    return None


def _ws_oi(symbol: str) -> float:
    """Ambil open interest dari WS cache."""
    s = _ws_state()
    if s and symbol in s.rt_oi:
        return s.rt_oi[symbol]
    return None


def _ws_funding(symbol: str) -> float:
    """Ambil funding rate dari WS cache."""
    s = _ws_state()
    if s and symbol in s.rt_funding:
        return s.rt_funding[symbol]
    return None


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
    # Impulse threshold: minimal 1.5x ATR ATAU 0.3% dari harga (untuk micro-cap)
    # Tanpa floor 0.3%, koin harga $0.0001 dengan ATR $0.000001 tidak pernah punya impulse
    impulse_threshold = max(atr * 1.5, current_price * 0.003)

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
    """
    Calculates real-time Bid/Ask pressure.
    WS-FIRST: pakai shared_state.rt_obi kalau fresh, fallback REST.
    """
    # 1. WS Cache (update setiap ~200ms via BitgetMarketWS)
    ws_obi = _ws_obi(symbol)
    if ws_obi is not None:
        return ws_obi

    # 2. REST Fallback
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
    """
    Scans recent trade stream for institutional-sized fills.
    WS-FIRST: pakai shared_state.rt_whale (rolling 5min) kalau ada, fallback REST.
    """
    # 1. WS Cache (rolling 5 menit dari BitgetMarketWS trade stream)
    ws_whale = _ws_whale(symbol)
    if ws_whale is not None:
        return ws_whale

    # 2. REST Fallback
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
    """
    WS-FIRST: pakai shared_state.rt_oi kalau ada, fallback REST.
    Bitget ticker field OI = holdingAmount (bukan openInterest).
    REST endpoint return field 'size' (jumlah kontrak).
    """
    # 1. WS Cache (dari BitgetMarketWS ticker stream, field holdingAmount)
    ws_oi = _ws_oi(symbol)
    if ws_oi is not None and ws_oi > 0:
        return ws_oi

    # 2. REST Fallback — dedicated OI endpoint
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/open-interest?symbol={symbol}&productType=USDT-FUTURES"
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code == 200:
            data = r.json().get('data', {})
            # Response: {"openInterestList": [{"symbol": "BTCUSDT", "size": "30728.0304"}]}
            oi_list = data.get('openInterestList', [])
            if oi_list:
                return float(oi_list[0].get('size', 0))
            # Fallback ke field lama kalau format berbeda
            return float(data.get('openInterest', data.get('size', 0)))
    except: pass
    return 0

def get_funding_rate(symbol):
    """
    WS-FIRST: pakai shared_state.rt_funding (refresh setiap 60s via BitgetMarketWS), fallback REST.
    """
    # 1. WS Cache
    ws_fr = _ws_funding(symbol)
    if ws_fr is not None:
        return ws_fr

    # 2. REST Fallback
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/current-funding-rate?symbol={symbol}&productType=USDT-FUTURES"
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code == 200:
            data = r.json().get('data', [{}])[0]
            return float(data.get('fundingRate', 0))
    except: pass
    return 0

def get_binance_ls_ratio(symbol):
    """
    Nyontek data Long/Short Ratio dari Binance (Volume terbesar).
    Return None kalau API gagal — beda dengan ratio 1.0 yang valid.
    Berguna untuk melihat apakah retail sedang dominan Long atau Short.
    Jika LS Ratio > 2.5, artinya retail terlalu banyak Long = Rawan Dump (Stop Hunt).
    Jika LS Ratio < 0.5, artinya retail terlalu banyak Short = Rawan Pump (Short Squeeze).
    """
    try:
        clean_symbol = symbol.replace("USDT_UMCBL", "USDT").replace("_UMCBL", "")
        if not clean_symbol.endswith("USDT"):
            clean_symbol = clean_symbol.split("_")[0] + "USDT"
            
        url = f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={clean_symbol}&period=15m&limit=1"
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code == 200:
            data = r.json()
            if data and isinstance(data, list):
                return float(data[0].get('longShortRatio', None))
    except Exception:
        pass
    return None  # None = API gagal, beda dengan 1.0 yang berarti balanced

def get_volume_profile(symbol):
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&granularity=1h&limit=24&productType=USDT-FUTURES"
        r = requests.get(url, timeout=3, verify=False)
        if r.status_code != 200: return {}
        data = r.json().get('data', [])
        if not data: return {}
        prices = {}
        for c in data:
            p = round(float(c[4]), 4)
            v = float(c[5])
            prices[p] = prices.get(p, 0) + v
        poc = max(prices, key=prices.get)
        last_p = float(data[-1][4])
        return {
            "poc": poc,
            "price_vs_poc": "ABOVE" if last_p > poc else "BELOW",
            "poc_distance_pct": round(abs(last_p - poc) / (poc or 1) * 100, 2)
        }
    except: return {}

def get_htf_key_levels(symbol):
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&granularity=4h&limit=42&productType=USDT-FUTURES"
        r = requests.get(url, timeout=3, verify=False)
        if r.status_code != 200: return {}
        data = r.json().get('data', [])
        if not data: return {}
        highs = [float(c[2]) for c in data]
        lows = [float(c[3]) for c in data]
        d_high = max(highs[-6:]) 
        d_low = min(lows[-6:])
        w_high = max(highs)
        w_low = min(lows)
        last_p = float(data[-1][4])
        return {
            "daily_high": d_high,
            "daily_low": d_low,
            "weekly_high": w_high,
            "weekly_low": w_low,
            "near_daily_level": abs(last_p - d_high)/(d_high or 1) < 0.005 or abs(last_p - d_low)/(d_low or 1) < 0.005,
            "level_bias": "RESISTANCE" if abs(last_p - d_high)/(d_high or 1) < 0.01 else ("SUPPORT" if abs(last_p - d_low)/(d_low or 1) < 0.01 else "NEUTRAL")
        }
    except: return {}

def get_fibonacci_levels(symbol):
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&granularity=1h&limit=100&productType=USDT-FUTURES"
        r = requests.get(url, timeout=3, verify=False)
        if r.status_code != 200: return {}
        data = r.json().get('data', [])
        if not data: return {}
        high = max(float(c[2]) for c in data)
        low = min(float(c[3]) for c in data)
        last_p = float(data[-1][4])
        diff = high - low
        fib618 = high - (diff * 0.618)
        return {
            "fib_618": fib618,
            "at_fib_support": abs(last_p - fib618)/(fib618 or 1) < 0.005,
            "current_fib_level": "0.618" if abs(last_p - fib618)/(fib618 or 1) < 0.01 else "NONE"
        }
    except: return {}

def detect_stop_hunt(symbol):
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&granularity=15m&limit=10&productType=USDT-FUTURES"
        r = requests.get(url, timeout=3, verify=False)
        if r.status_code != 200: return {}
        data = r.json().get('data', [])
        if len(data) < 3: return {}
        last = data[-1]
        prev = data[-2]
        bull_hunt = float(last[3]) < float(prev[3]) and float(last[4]) > float(prev[3])
        return {"bull_stop_hunt": bull_hunt, "hunt_strength": 1.0 if bull_hunt else 0}
    except: return {}

def get_technical_indicators(symbol, interval="15m"):
    """
    ULTIMATE INDICATOR ENGINE v5.1: SMC + Order Flow + Predictive Structure
    """
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&granularity={interval}&limit=100&productType=USDT-FUTURES"
        r = requests.get(url, timeout=15, verify=False)
        if r.status_code != 200: return {}
        
        data = r.json().get('data', [])
        df_cur = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'vol_usd'])
        df_cur[['open', 'high', 'low', 'close', 'vol']] = df_cur[['open', 'high', 'low', 'close', 'vol']].astype(float)
        
        # --- THREAD-SAFE CACHE FOR HTF ---
        now = time.time()
        cache_key = f"{symbol}_{interval}"
        
        with _htf_lock:
            cached = _htf_cache.get(cache_key)
            
        if cached and (now - cached['ts'] < 300):
            htf_data = cached['data']
            trend_1h = htf_data['trend_1h']
            trend_4h = htf_data['trend_4h']
            ema_200_htf_val = htf_data['ema_200_htf']
            ema_50_4h = htf_data['ema_50_4h']
        else:
            # 2. HTF CONTEXT (1H + 4H)
            url_htf = f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&granularity=1h&limit=100&productType=USDT-FUTURES"
            r_htf = requests.get(url_htf, timeout=5, verify=False)
            ema_200_htf_val = 0
            trend_1h = "NEUTRAL"
            if r_htf.status_code == 200:
                data_htf = r_htf.json().get('data', [])
                df_htf = pd.DataFrame(data_htf, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'vol_usd'])
                df_htf['close'] = df_htf['close'].astype(float)
                ema_htf = df_htf['close'].ewm(span=200, adjust=False).mean()
                ema_200_htf_val = ema_htf.iloc[-1] if len(ema_htf) > 0 else 0
                last_1h = df_htf['close'].iloc[-1]
                if ema_200_htf_val > 0:
                    trend_1h = "BULLISH" if last_1h > ema_200_htf_val * 1.001 else \
                               "BEARISH" if last_1h < ema_200_htf_val * 0.999 else "NEUTRAL"

            # 4H TREND
            url_4h = f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&granularity=4h&limit=50&productType=USDT-FUTURES"
            r_4h = requests.get(url_4h, timeout=5, verify=False)
            trend_4h = "NEUTRAL"
            ema_50_4h = 0
            if r_4h.status_code == 200:
                data_4h = r_4h.json().get('data', [])
                if len(data_4h) >= 10:
                    closes_4h = [float(c[4]) for c in data_4h]
                    ema_4h = closes_4h[0]
                    k_4h = 2 / (50 + 1)
                    for c in closes_4h:
                        ema_4h = c * k_4h + ema_4h * (1 - k_4h)
                    ema_50_4h = ema_4h
                    last_4h = closes_4h[-1]
                    trend_4h = "BULLISH" if last_4h > ema_4h * 1.001 else \
                               "BEARISH" if last_4h < ema_4h * 0.999 else "NEUTRAL"
                    if len(closes_4h) >= 20:
                        ema_old = closes_4h[0]
                        for c in closes_4h[:-10]:
                            ema_old = c * k_4h + ema_old * (1 - k_4h)
                        if ema_4h < ema_old * 0.998: trend_4h = "BEARISH"

            with _htf_lock:
                _htf_cache[cache_key] = {
                    'ts': now,
                    'data': {
                        'trend_1h': trend_1h,
                        'trend_4h': trend_4h,
                        'ema_200_htf': ema_200_htf_val,
                        'ema_50_4h': ema_50_4h
                    }
                }

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
        liq_grab = detect_institutional_liquidity_grab(df_cur) # BlackRock Liquidity Hunter

        # 5m Precision Entry (hanya fetch kalau interval bukan 5m untuk hindari redundant call)
        entry_5m = get_5m_precision_entry(symbol) if interval != "5m" else {
            "in_5m_demand": False, "in_5m_supply": False,
            "demand_5m": {}, "supply_5m": {},
            "entry_quality": 0, "entry_signal": "NEUTRAL",
            "proximity_pct": 999, "zone_freshness": "UNKNOWN"
        }

        # Volume Profile, HTF Key Levels, Fibonacci, Stop Hunt
        # CATATAN: Fungsi-fungsi ini dipanggil hanya saat entry (bukan saat scan)
        # untuk menghindari terlalu banyak API call per koin
        # Gunakan get_volume_profile(), get_htf_key_levels(), dll secara terpisah
        vp   = {"poc": 0, "value_area_high": 0, "value_area_low": 0,
                "price_vs_poc": "UNKNOWN", "poc_distance_pct": 0}
        htf  = {"daily_high": 0, "daily_low": 0, "weekly_high": 0, "weekly_low": 0,
                "near_daily_level": False, "near_weekly_level": False, "level_bias": "NEUTRAL"}
        fib  = {}
        hunt = {"bull_stop_hunt": False, "bear_stop_hunt": False, "hunt_strength": 0}

        vp   = {"poc": 0, "value_area_high": 0, "value_area_low": 0,
                "price_vs_poc": "UNKNOWN", "poc_distance_pct": 0}
        htf  = {"daily_high": 0, "daily_low": 0, "weekly_high": 0, "weekly_low": 0,
                "near_daily_level": False, "near_weekly_level": False, "level_bias": "NEUTRAL"}
        fib  = {}
        hunt = {"bull_stop_hunt": False, "bear_stop_hunt": False, "hunt_strength": 0}

        # 7. ATR 14 (True Range) & EMA
        # WS-FIRST: pakai harga real-time dari WS kalau tersedia (lebih akurat dari candle close)
        candle_close = df_cur['close'].iloc[-1]
        ws_live_price = _ws_price(symbol)
        mark_price = ws_live_price if ws_live_price > 0 else candle_close
        ema_200_cur = df_cur['close'].ewm(span=200, adjust=False).mean()
        trs = []
        for i in range(1, len(df_cur)):
            h, l, cp = df_cur['high'].iloc[i], df_cur['low'].iloc[i], df_cur['close'].iloc[i-1]
            trs.append(max(h-l, abs(h-cp), abs(l-cp)))
        atr_val = round(sum(trs[-14:]) / 14, 6) if len(trs) >= 14 else round(mark_price * 0.015, 6)


        # 7c. INTRADAY VWAP (last 32 candles)
        cum_pv = 0.0
        cum_v = 0.0
        vwap_candles = df_cur.tail(32)
        for _, row in vwap_candles.iterrows():
            typical = (row['high'] + row['low'] + row['close']) / 3
            cum_pv += typical * row['vol']
            cum_v += row['vol']
        vwap = cum_pv / cum_v if cum_v > 0 else mark_price
        vwap_dist = round((mark_price - vwap) / vwap * 100, 4) if vwap > 0 else 0.0

        # 7b. FALLING KNIFE / FLYING ROCKET (Anti-Premature Entry)
        # Deteksi apakah candle saat ini masih bergerak kuat melawan arah pantulan
        last_open = df_cur['open'].iloc[-1]
        last_close = df_cur['close'].iloc[-1]
        prev_low = df_cur['low'].iloc[-2] if len(df_cur) >= 2 else last_close
        prev_high = df_cur['high'].iloc[-2] if len(df_cur) >= 2 else last_close
        body_size = abs(last_close - last_open)
        
        # Pisau jatuh: Candle merah membesar (body > 50% ATR) dan menjebol low candle sebelumnya
        falling_knife = (last_close < last_open) and (body_size > atr_val * 0.5) and (last_close < prev_low)
        # Roket terbang: Candle hijau membesar (body > 50% ATR) dan menjebol high candle sebelumnya
        flying_rocket = (last_close > last_open) and (body_size > atr_val * 0.5) and (last_close > prev_high)

        # ── 7c. MOMENTUM EXHAUSTION DETECTION ─────────────────────────────────
        # Pertanyaan kunci: "Apakah momentum turun/naik sudah HABIS?"
        # Bot tidak boleh BUY kalau harga masih dalam tren turun yang aktif.
        # Bot tidak boleh SELL kalau harga masih dalam tren naik yang aktif.
        #
        # Cara deteksi exhaustion:
        # 1. LOWER HIGH / LOWER LOW sequence (bearish structure masih aktif)
        #    → Selama harga masih bikin lower high, jangan BUY
        # 2. Candle merah berturut-turut (momentum turun belum berhenti)
        #    → 3+ candle merah berturut-turut = masih turun, tunggu reversal
        # 3. Volume turun saat harga turun (exhaustion = volume mengecil)
        #    → Volume spike turun = masih ada seller kuat
        # 4. Candle terakhir close di bawah open DAN di bawah low candle sebelumnya
        #    → Ini "continuation" bukan "reversal"

        closes_arr = df_cur['close'].tolist()
        opens_arr  = df_cur['open'].tolist()
        highs_arr  = df_cur['high'].tolist()
        lows_arr   = df_cur['low'].tolist()
        vols_arr   = df_cur['vol'].tolist()

        # Hitung berapa candle merah/hijau berturut-turut dari belakang
        consec_red   = 0
        consec_green = 0
        for i in range(len(closes_arr) - 1, max(len(closes_arr) - 6, -1), -1):
            if closes_arr[i] < opens_arr[i]:
                if consec_green > 0: break
                consec_red += 1
            else:
                if consec_red > 0: break
                consec_green += 1

        # Lower High / Lower Low detection (3 candle terakhir)
        # Bearish structure: setiap high lebih rendah dari high sebelumnya
        # Bullish structure: setiap low lebih tinggi dari low sebelumnya
        bearish_structure = False
        bullish_structure = False
        if len(highs_arr) >= 4:
            # Cek 3 candle terakhir apakah bikin lower high
            lh1 = highs_arr[-2] < highs_arr[-3]  # high[-2] < high[-3]
            lh2 = highs_arr[-1] < highs_arr[-2]  # high[-1] < high[-2]
            ll1 = lows_arr[-2]  < lows_arr[-3]   # low[-2] < low[-3]
            ll2 = lows_arr[-1]  < lows_arr[-2]   # low[-1] < low[-2]
            bearish_structure = (lh1 and lh2) or (ll1 and ll2)  # Lower highs ATAU lower lows

            # Cek 3 candle terakhir apakah bikin higher low
            hl1 = lows_arr[-2]  > lows_arr[-3]
            hl2 = lows_arr[-1]  > lows_arr[-2]
            hh1 = highs_arr[-2] > highs_arr[-3]
            hh2 = highs_arr[-1] > highs_arr[-2]
            bullish_structure = (hl1 and hl2) or (hh1 and hh2)  # Higher lows ATAU higher highs

        # Volume exhaustion: volume candle terakhir < 50% rata-rata = momentum habis
        avg_vol_5 = sum(vols_arr[-6:-1]) / 5 if len(vols_arr) >= 6 else (sum(vols_arr) / len(vols_arr) if vols_arr else 1)
        last_vol  = vols_arr[-1] if vols_arr else 0
        vol_exhaustion = last_vol < avg_vol_5 * 0.5  # Volume sangat kecil = momentum habis

        # Reversal confirmation: candle terakhir harus BERLAWANAN dengan tren sebelumnya
        # Untuk BUY: candle terakhir harus hijau (close > open) setelah serangkaian merah
        # Untuk SELL: candle terakhir harus merah (close < open) setelah serangkaian hijau
        last_candle_bullish = last_close > last_open
        last_candle_bearish = last_close < last_open

        # Gabungkan: apakah momentum turun sudah habis? (aman untuk BUY)
        # Kondisi: candle terakhir hijau ATAU volume exhaustion ATAU tidak ada bearish structure
        bearish_momentum_exhausted = (
            last_candle_bullish or          # Candle terakhir sudah hijau (reversal dimulai)
            (vol_exhaustion and consec_red <= 2) or  # Volume habis dan tidak terlalu banyak merah
            (consec_red == 0)               # Tidak ada candle merah berturut-turut
        ) and not bearish_structure         # Tapi struktur bearish belum aktif

        # Gabungkan: apakah momentum naik sudah habis? (aman untuk SELL)
        bullish_momentum_exhausted = (
            last_candle_bearish or
            (vol_exhaustion and consec_green <= 2) or
            (consec_green == 0)
        ) and not bullish_structure

        # Flag untuk dipakai di _determine_trade_side:
        # still_falling = harga masih turun, JANGAN BUY
        # still_rising  = harga masih naik, JANGAN SELL
        still_falling = (consec_red >= 3) or (bearish_structure and not last_candle_bullish)
        still_rising  = (consec_green >= 3) or (bullish_structure and not last_candle_bearish)

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
            "rvol": round(last_candle['vol'] / avg_vol, 2) if avg_vol > 0 else 1.0,
            "atr": atr_val,
            "candle_pattern": pattern,
            "is_liquidity_sweep": is_bull_sweep or is_bear_sweep,
            "mss_bullish": mss_bullish,
            "mss_bearish": mss_bearish,
            "choch_bullish": choch_bullish,
            "choch_bearish": choch_bearish,
            "fib_ext": round(fib_ext, 4),
            "vwap_dist": vwap_dist,
            "obi": obi,
            "whale_signal": whale_sig,
            "order_block": smc["ob"],
            "fvg": smc["fvg"],
            "inst_flow": inst_flow,
            "demand_zone":  dsz["demand_zone"],
            "supply_zone":  dsz["supply_zone"],
            "in_demand":    dsz["in_demand"],
            "in_supply":    dsz["in_supply"],
            # Volume Profile
            "poc":              vp.get("poc", 0),
            "value_area_high":  vp.get("value_area_high", 0),
            "value_area_low":   vp.get("value_area_low", 0),
            "price_vs_poc":     vp.get("price_vs_poc", "UNKNOWN"),
            "poc_distance_pct": vp.get("poc_distance_pct", 0),
            # HTF Key Levels
            "daily_high":         htf.get("daily_high", 0),
            "daily_low":          htf.get("daily_low", 0),
            "weekly_high":        htf.get("weekly_high", 0),
            "weekly_low":         htf.get("weekly_low", 0),
            "near_daily_level":   htf.get("near_daily_level", False),
            "near_weekly_level":  htf.get("near_weekly_level", False),
            "htf_level_bias":     htf.get("level_bias", "NEUTRAL"),
            # Fibonacci
            "fib_382":            fib.get("fib_382", 0),
            "fib_500":            fib.get("fib_500", 0),
            "fib_618":            fib.get("fib_618", 0),
            "at_fib_support":     fib.get("at_fib_support", False),
            "at_fib_resistance":  fib.get("at_fib_resistance", False),
            "current_fib_level":  fib.get("current_fib_level", "NONE"),
            # Stop Hunt
            "bull_stop_hunt":     hunt.get("bull_stop_hunt", False),
            "bear_stop_hunt":     hunt.get("bear_stop_hunt", False),
            "hunt_strength":      hunt.get("hunt_strength", 0),
            "ema_200": round(ema_200_cur.iloc[-1], 2) if len(ema_200_cur) > 0 else 0,
            "ema_200_htf": round(ema_200_htf_val, 2),
            "trend_1h": trend_1h,
            "trend_4h": trend_4h,
            "liquidity_grab": liq_grab,
            "ema_50_4h": round(ema_50_4h, 6),
            "open_interest": get_open_interest(symbol),
            "funding_rate": get_funding_rate(symbol),
            "ls_ratio": get_binance_ls_ratio(symbol),
            "htf": "1h",
            "falling_knife": falling_knife,
            "flying_rocket": flying_rocket,
            # Momentum exhaustion signals
            "still_falling":              still_falling,
            "still_rising":               still_rising,
            "bearish_momentum_exhausted": bearish_momentum_exhausted,
            "bullish_momentum_exhausted": bullish_momentum_exhausted,
            "consec_red":                 consec_red,
            "consec_green":               consec_green,
            "bearish_structure":          bearish_structure,
            "bullish_structure":          bullish_structure,
            "vol_exhaustion":             vol_exhaustion,
            # WS Real-time enrichment (setara CoinAPI live feed)
            "ws_live_price":    ws_live_price if ws_live_price > 0 else candle_close,
            "ws_bid":           _ws_state().rt_bid.get(symbol, 0) if _ws_state() else 0,
            "ws_ask":           _ws_state().rt_ask.get(symbol, 0) if _ws_state() else 0,
            "ws_spread_pct":    _ws_state().rt_spread.get(symbol, 0) if _ws_state() else 0,
            "ws_change_24h":    _ws_state().rt_change.get(symbol, 0) if _ws_state() else 0,
            "ws_volume_24h":    _ws_state().rt_volume.get(symbol, 0) if _ws_state() else 0,
            "ws_whale_buy_vol": _ws_state().rt_whale_buy_vol.get(symbol, 0) if _ws_state() else 0,
            "ws_whale_sell_vol":_ws_state().rt_whale_sell_vol.get(symbol, 0) if _ws_state() else 0,
            "ws_connected":     _ws_state().market_ws_connected if _ws_state() else False,
            # 5m Precision Entry
            "in_5m_demand":     entry_5m.get("in_5m_demand", False),
            "in_5m_supply":     entry_5m.get("in_5m_supply", False),
            "entry_quality_5m": entry_5m.get("entry_quality", 0),
            "entry_signal_5m":  entry_5m.get("entry_signal", "NEUTRAL"),
            "demand_5m":        entry_5m.get("demand_5m", {}),
            "supply_5m":        entry_5m.get("supply_5m", {}),
            "zone_freshness_5m":entry_5m.get("zone_freshness", "UNKNOWN"),
            "proximity_5m_pct": entry_5m.get("proximity_pct", 999),
        }
    except Exception as e:
        print(f"Error indicators for {symbol}: {e}")
        return {}

def fetch_all_tickers():
    """
    Fetches all USDT-FUTURES tickers from Bitget.
    Setelah fetch, update BitgetMarketWS symbol list supaya WS coverage selalu fresh.
    """
    try:
        url = "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
        r = requests.get(url, timeout=10, verify=False)
        if r.status_code == 200:
            data = r.json().get('data', [])
            # Update WS symbol list dengan top 60 by volume
            try:
                from websocket_sniper import get_market_ws
                sorted_data = sorted(data, key=lambda x: float(x.get('baseVolume', 0) or 0), reverse=True)
                top_syms = [t['symbol'] for t in sorted_data if t.get('symbol')]  # Semua koin, tidak dibatasi
                get_market_ws().update_symbols(top_syms)
            except Exception:
                pass
            return data
    except: pass
    return []

def get_order_book_details(symbol):
    """
    Real order book bid/ask ratio untuk konfirmasi entry.
    Positif = buyer dominance, negatif = seller dominance.
    Threshold: > +0.1 = valid BUY, < -0.1 = valid SELL.
    """
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/depth?symbol={symbol}&limit=20&productType=USDT-FUTURES"
        r = requests.get(url, timeout=3, verify=False)
        if r.status_code == 200:
            data = r.json().get('data', {})
            bids = sum(float(b[1]) for b in data.get('bids', []))
            asks = sum(float(a[1]) for a in data.get('asks', []))
            total = bids + asks
            if total == 0:
                return {'ratio': 0, 'bids': 0, 'asks': 0}
            ratio = round((bids - asks) / total, 4)
            return {'ratio': ratio, 'bids': round(bids, 2), 'asks': round(asks, 2)}
    except Exception:
        pass
    return {'ratio': 0, 'bids': 0, 'asks': 0}

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
    """
    DUNE ANALYTICS — Full On-Chain Macro Intelligence Engine
    =========================================================
    Menggunakan Dune API v1 dengan flow: create query → execute → poll → result.
    Cache 30 menit — data on-chain update per block (~12 detik) tapi kita tidak
    perlu refresh sesering itu untuk macro signal.

    Data yang dihasilkan:
    1. Stablecoin supply (USDT+USDC+DAI) — proxy untuk "dry powder" di market
       Naik = lebih banyak uang siap masuk crypto = bullish
       Turun = capital keluar dari crypto = bearish

    2. DEX volume 24h — on-chain trading activity
       Tinggi = market aktif, sinyal lebih reliable
       Rendah = market sepi, sinyal lebih banyak false

    3. ETH gas price — proxy untuk network congestion & market activity
       Gas tinggi = banyak transaksi = market aktif/bullish
       Gas rendah = sepi = market lesu

    4. Whale ETH transfers (>100 ETH) — institutional movement
       Banyak = whale aktif bergerak = potensi volatilitas tinggi

    Return dict:
      stablecoin_supply_b  : float  — total stablecoin supply dalam Miliar USD
      stablecoin_change_pct: float  — perubahan supply vs kemarin (%)
      dex_volume_24h_b     : float  — DEX volume 24h dalam Miliar USD
      eth_gas_gwei         : float  — ETH gas price rata-rata (Gwei)
      whale_transfers_1h   : int    — jumlah transfer >100 ETH dalam 1 jam
      whale_eth_volume_1h  : float  — total ETH dari whale transfers
      macro_trend          : str    — "BULLISH" / "BEARISH" / "NEUTRAL"
      onchain_activity     : str    — "HIGH" / "NORMAL" / "LOW"
      summary              : str    — ringkasan 1 baris untuk log
    """
    # Cache 30 menit
    now = time.time()
    if hasattr(get_dune_macro_metrics, '_cache'):
        cached = get_dune_macro_metrics._cache
        if now - cached.get('ts', 0) < 1800:
            return cached['data']

    api_key = os.getenv("DUNE_API_KEY")
    if not api_key:
        return _dune_neutral("DUNE_API_KEY tidak ditemukan")

    BASE    = "https://api.dune.com/api/v1"
    HEADERS = {"X-DUNE-API-KEY": api_key, "Content-Type": "application/json"}

    def _dune_run(sql: str, name: str, max_wait: int = 60) -> list:
        """Create → Execute → Poll → Return rows."""
        try:
            # 1. Create query
            r = requests.post(f"{BASE}/query", headers=HEADERS,
                              json={"name": name, "query_sql": sql, "is_private": False},
                              timeout=15)
            if r.status_code not in (200, 201):
                return []
            qid = r.json().get("query_id")

            # 2. Execute (tanpa performance param — free tier)
            r2 = requests.post(f"{BASE}/query/{qid}/execute",
                               headers=HEADERS, json={}, timeout=15)
            if r2.status_code not in (200, 201):
                return []
            exec_id = r2.json().get("execution_id")

            # 3. Poll (max max_wait detik)
            for _ in range(max_wait // 5):
                time.sleep(5)
                r3 = requests.get(f"{BASE}/execution/{exec_id}/results",
                                  headers=HEADERS, timeout=15)
                if r3.status_code == 200:
                    data = r3.json()
                    state = data.get("state", "")
                    if state == "QUERY_STATE_COMPLETED":
                        return data.get("result", {}).get("rows", [])
                    elif "FAILED" in state or "CANCELLED" in state:
                        return []
            return []
        except Exception as e:
            print(f"[DUNE] Error running {name}: {e}", flush=True)
            return []

    result = {}

    # ── 1. Stablecoin Supply ─────────────────────────────────────────────────
    print("[DUNE] Fetching stablecoin supply...", flush=True)
    stable_rows = _dune_run("""
        SELECT
            symbol,
            SUM(amount / 1e6) as supply_millions,
            COUNT(*) as tx_count
        FROM tokens_ethereum.transfers
        WHERE symbol IN ('USDT', 'USDC', 'DAI', 'BUSD')
          AND block_time >= NOW() - INTERVAL '1' day
        GROUP BY symbol
        ORDER BY supply_millions DESC
        LIMIT 5
    """, "CryptoScreener_StablecoinSupply", max_wait=60)

    total_stable_m = sum(r.get("supply_millions", 0) for r in stable_rows)
    total_stable_b = round(total_stable_m / 1000, 2)

    # Sanity check: stablecoin supply harusnya $200B-$500B
    # Kalau di luar range ini, data Dune corrupt — pakai 0 (neutral)
    if total_stable_b > 500 or total_stable_b < 0:
        print(f"[DUNE] Stablecoin data invalid ({total_stable_b}B), using neutral", flush=True)
        total_stable_b = 0.0

    result["stablecoin_supply_b"] = total_stable_b
    result["stablecoin_breakdown"] = {
        r["symbol"]: round(r.get("supply_millions", 0) / 1000, 2)
        for r in stable_rows
        if r.get("supply_millions", 0) / 1000 < 500  # Filter baris corrupt
    }

    # ── 2. DEX Volume 24h ────────────────────────────────────────────────────
    print("[DUNE] Fetching DEX volume...", flush=True)
    dex_rows = _dune_run("""
        SELECT
            project,
            SUM(amount_usd) as volume_usd,
            COUNT(*) as trades
        FROM dex.trades
        WHERE block_time >= NOW() - INTERVAL '24' hour
          AND blockchain = 'ethereum'
        GROUP BY project
        ORDER BY volume_usd DESC
        LIMIT 8
    """, "CryptoScreener_DEXVolume24h", max_wait=60)

    total_dex_usd = sum((r.get("volume_usd") or 0) for r in dex_rows)
    dex_volume_b = round(total_dex_usd / 1e9, 2)
    # Sanity check: DEX volume harusnya $0.1B-$20B per hari
    if dex_volume_b > 20 or dex_volume_b < 0:
        print(f"[DUNE] DEX volume invalid ({dex_volume_b}B), using neutral", flush=True)
        dex_volume_b = 0.0
    result["dex_volume_24h_b"] = dex_volume_b
    result["dex_top_protocol"]  = dex_rows[0].get("project", "unknown") if dex_rows else "unknown"

    # ── 3. ETH Gas (market activity proxy) ───────────────────────────────────
    print("[DUNE] Fetching ETH gas...", flush=True)
    gas_rows = _dune_run("""
        SELECT
            AVG(gas_price / 1e9) as avg_gwei,
            COUNT(*) as tx_count
        FROM ethereum.transactions
        WHERE block_time >= NOW() - INTERVAL '1' hour
    """, "CryptoScreener_ETHGas1h", max_wait=60)

    eth_gas = round(gas_rows[0].get("avg_gwei") or 0, 2) if gas_rows else 0
    # Sanity check: ETH gas harusnya 0.1-500 Gwei
    if eth_gas > 500 or eth_gas < 0:
        eth_gas = 0.0
    eth_tx_count = gas_rows[0].get("tx_count") or 0 if gas_rows else 0
    result["eth_gas_gwei"]    = eth_gas
    result["eth_tx_count_1h"] = eth_tx_count

    # ── 4. Whale ETH Transfers ───────────────────────────────────────────────
    print("[DUNE] Fetching whale transfers...", flush=True)
    whale_rows = _dune_run("""
        SELECT
            COUNT(*) as large_transfers,
            SUM(value / 1e18) as total_eth,
            AVG(value / 1e18) as avg_eth
        FROM ethereum.transactions
        WHERE block_time >= NOW() - INTERVAL '1' hour
          AND value / 1e18 > 100
    """, "CryptoScreener_WhaleTransfers1h", max_wait=60)

    whale_count = whale_rows[0].get("large_transfers") or 0 if whale_rows else 0
    whale_eth   = round(whale_rows[0].get("total_eth") or 0, 0) if whale_rows else 0
    result["whale_transfers_1h"]  = whale_count
    result["whale_eth_volume_1h"] = whale_eth

    # ── 5. Macro Trend Scoring ───────────────────────────────────────────────
    bull_score = 0
    bear_score = 0

    # Stablecoin supply: > $200B = banyak dry powder = bullish
    if total_stable_b > 200:   bull_score += 2
    elif total_stable_b < 100: bear_score += 1

    # DEX volume: > $1B/day = market aktif = bullish
    if result["dex_volume_24h_b"] > 1.0:   bull_score += 2
    elif result["dex_volume_24h_b"] < 0.3: bear_score += 1

    # ETH gas: > 20 Gwei = market sangat aktif
    if eth_gas > 20:    bull_score += 1
    elif eth_gas < 2:   bear_score += 1  # Market sepi

    # Whale activity: > 50 transfers/jam = whale aktif
    if whale_count > 50:  bull_score += 1
    elif whale_count < 5: bear_score += 1

    if bull_score > bear_score + 1:
        macro_trend = "BULLISH"
    elif bear_score > bull_score + 1:
        macro_trend = "BEARISH"
    else:
        macro_trend = "NEUTRAL"

    result["macro_trend"] = macro_trend

    # On-chain activity level
    if result["dex_volume_24h_b"] > 2.0 or eth_gas > 30:
        onchain_activity = "HIGH"
    elif result["dex_volume_24h_b"] < 0.5 and eth_gas < 5:
        onchain_activity = "LOW"
    else:
        onchain_activity = "NORMAL"

    result["onchain_activity"] = onchain_activity

    # ── Summary ──────────────────────────────────────────────────────────────
    result["summary"] = (
        f"[DUNE] Stable:{total_stable_b}B | "
        f"DEX:{result['dex_volume_24h_b']}B/24h | "
        f"Gas:{eth_gas}gwei | "
        f"Whales:{whale_count}tx/{whale_eth:.0f}ETH | "
        f"Trend:{macro_trend} | Activity:{onchain_activity}"
    )
    print(result["summary"], flush=True)

    # Cache
    get_dune_macro_metrics._cache = {"ts": now, "data": result}
    return result


def _dune_neutral(reason: str = "") -> dict:
    """Return neutral Dune context kalau API gagal."""
    return {
        "stablecoin_supply_b":  0.0,
        "stablecoin_breakdown": {},
        "dex_volume_24h_b":     0.0,
        "dex_top_protocol":     "unknown",
        "eth_gas_gwei":         0.0,
        "eth_tx_count_1h":      0,
        "whale_transfers_1h":   0,
        "whale_eth_volume_1h":  0.0,
        "macro_trend":          "NEUTRAL",
        "onchain_activity":     "NORMAL",
        "summary":              f"[DUNE] Data tidak tersedia: {reason}",
    }

def get_5m_precision_entry(symbol: str) -> dict:
    """
    5M PRECISION ENTRY ENGINE
    ==========================
    Cari zona demand/supply di TF 5m untuk precision entry di dalam zona HTF.

    Kenapa 5m?
    - HTF (15m/1h/4h) menentukan ARAH dan ZONA BESAR
    - 5m menentukan TITIK ENTRY PRESISI di dalam zona tersebut
    - Entry di 5m demand zone = risiko lebih kecil, reward lebih besar
    - Ini yang dipakai trader institusi: "snipe entry" di lower TF

    Return dict:
      in_5m_demand      : bool   — harga di dalam demand zone 5m
      in_5m_supply      : bool   — harga di dalam supply zone 5m
      demand_5m         : dict   — {top, bottom, strength, fresh, volume_ratio}
      supply_5m         : dict   — {top, bottom, strength, fresh, volume_ratio}
      entry_quality     : int    — 0-100, seberapa bagus entry sekarang
      entry_signal      : str    — "STRONG_BUY" / "BUY" / "NEUTRAL" / "SELL" / "STRONG_SELL"
      proximity_pct     : float  — % jarak harga ke zona terdekat
      zone_freshness    : str    — "FRESH" / "TESTED_ONCE" / "TESTED_MULTIPLE"
    """
    empty = {
        "in_5m_demand": False, "in_5m_supply": False,
        "demand_5m": {}, "supply_5m": {},
        "entry_quality": 0, "entry_signal": "NEUTRAL",
        "proximity_pct": 999, "zone_freshness": "UNKNOWN"
    }

    try:
        url = (f"https://api.bitget.com/api/v2/mix/market/history-candles"
               f"?symbol={symbol}&granularity=5m&limit=80&productType=USDT-FUTURES")
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code != 200:
            return empty

        data = r.json().get('data', [])
        if len(data) < 20:
            return empty

        highs  = [float(c[2]) for c in data]
        lows   = [float(c[3]) for c in data]
        closes = [float(c[4]) for c in data]
        opens  = [float(c[1]) for c in data]
        vols   = [float(c[5]) for c in data]
        n      = len(closes)

        current_price = closes[-1]

        # ATR 14
        trs = []
        for i in range(1, n):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i]  - closes[i-1]))
            trs.append(tr)
        atr = sum(trs[-14:]) / 14 if len(trs) >= 14 else current_price * 0.003

        avg_vol = sum(vols) / len(vols) if vols else 1
        consol_threshold  = atr * 0.5
        impulse_threshold = max(atr * 1.2, current_price * 0.002)

        best_demand = {"active": False, "top": 0, "bottom": 0, "strength": 0,
                       "fresh": True, "volume_ratio": 1.0, "candle_idx": 0}
        best_supply = {"active": False, "top": 0, "bottom": 0, "strength": 0,
                       "fresh": True, "volume_ratio": 1.0, "candle_idx": 0}

        for i in range(3, n - 2):
            body_i = abs(closes[i] - opens[i])
            if body_i < impulse_threshold:
                continue

            consol_start = max(0, i - 6)
            consol_candles = []
            for j in range(consol_start, i):
                if (highs[j] - lows[j]) <= consol_threshold:
                    consol_candles.append(j)

            if len(consol_candles) < 2:
                continue

            zone_top    = max(highs[j] for j in consol_candles)
            zone_bottom = min(lows[j]  for j in consol_candles)
            strength    = len(consol_candles)
            vol_ratio   = vols[i] / avg_vol if avg_vol > 0 else 1.0

            # Freshness: berapa kali harga sudah masuk zona ini setelah terbentuk
            touch_count = sum(1 for k in range(i + 1, n)
                              if zone_bottom <= closes[k] <= zone_top)
            is_fresh = touch_count == 0
            freshness_label = ("FRESH" if touch_count == 0 else
                               "TESTED_ONCE" if touch_count <= 2 else "TESTED_MULTIPLE")

            if closes[i] > opens[i]:  # Demand zone
                dist = abs(current_price - zone_top)
                if not best_demand["active"] or dist < abs(current_price - best_demand["top"]):
                    best_demand = {
                        "active": True, "top": round(zone_top, 8),
                        "bottom": round(zone_bottom, 8), "strength": strength,
                        "fresh": is_fresh, "freshness": freshness_label,
                        "volume_ratio": round(vol_ratio, 2),
                        "candle_idx": i, "touch_count": touch_count,
                    }
            else:  # Supply zone
                dist = abs(current_price - zone_bottom)
                if not best_supply["active"] or dist < abs(current_price - best_supply["bottom"]):
                    best_supply = {
                        "active": True, "top": round(zone_top, 8),
                        "bottom": round(zone_bottom, 8), "strength": strength,
                        "fresh": is_fresh, "freshness": freshness_label,
                        "volume_ratio": round(vol_ratio, 2),
                        "candle_idx": i, "touch_count": touch_count,
                    }

        in_demand = False
        in_supply = False
        proximity_pct = 999.0

        if best_demand["active"]:
            dz_top, dz_bottom = best_demand["top"], best_demand["bottom"]
            if dz_bottom - atr * 0.5 <= current_price <= dz_top + atr * 0.3:
                in_demand = True
            proximity_pct = min(proximity_pct, abs(current_price - dz_top) / current_price * 100)

        if best_supply["active"]:
            sz_top, sz_bottom = best_supply["top"], best_supply["bottom"]
            if sz_bottom - atr * 0.3 <= current_price <= sz_top + atr * 0.5:
                in_supply = True
            proximity_pct = min(proximity_pct, abs(current_price - sz_bottom) / current_price * 100)

        # Entry Quality Score (0-100)
        quality = 0
        active_zone = best_demand if in_demand else (best_supply if in_supply else None)
        if active_zone:
            quality += 40
            if active_zone.get("fresh"):                    quality += 25
            elif active_zone.get("touch_count", 0) <= 1:   quality += 10
            vol_r = active_zone.get("volume_ratio", 1.0)
            if vol_r >= 2.0:   quality += 20
            elif vol_r >= 1.5: quality += 12
            elif vol_r >= 1.2: quality += 6
            if active_zone.get("strength", 0) >= 4:        quality += 15
        elif proximity_pct < 0.5:
            quality = 20
        quality = min(100, quality)

        if in_demand and quality >= 70:   entry_signal = "STRONG_BUY"
        elif in_demand and quality >= 40: entry_signal = "BUY"
        elif in_supply and quality >= 70: entry_signal = "STRONG_SELL"
        elif in_supply and quality >= 40: entry_signal = "SELL"
        else:                             entry_signal = "NEUTRAL"

        return {
            "in_5m_demand":   in_demand,
            "in_5m_supply":   in_supply,
            "demand_5m":      best_demand if best_demand["active"] else {},
            "supply_5m":      best_supply if best_supply["active"] else {},
            "entry_quality":  quality,
            "entry_signal":   entry_signal,
            "proximity_pct":  round(proximity_pct, 4),
            "zone_freshness": (best_demand.get("freshness") if in_demand else
                               best_supply.get("freshness", "UNKNOWN")),
        }

    except Exception as e:
        print(f"[5M ENTRY] Error {symbol}: {e}")
        return empty


def detect_institutional_liquidity_grab(df):
    """
    BLACKROCK SMART LIQUIDITY HUNTER
    Detects long-wick rejections (pin bars) at key levels.
    These often indicate institutional liquidity sweeps.
    """
    if len(df) < 5: return {"bullish_grab": False, "bearish_grab": False}
    
    last = df.iloc[-1]
    body = abs(last['close'] - last['open'])
    wick_top = last['high'] - max(last['close'], last['open'])
    wick_bottom = min(last['close'], last['open']) - last['low']
    total_range = last['high'] - last['low']
    
    if total_range == 0: return {"bullish_grab": False, "bearish_grab": False}
    
    # 1. Bullish Grab: Long lower wick, small body (Stop hunt below)
    bullish_grab = (wick_bottom > body * 2) and (wick_bottom > total_range * 0.6)
    
    # 2. Bearish Grab: Long upper wick, small body (Liquidity sweep above)
    bearish_grab = (wick_top > body * 2) and (wick_top > total_range * 0.6)
    
    return {
        "bullish_grab": bullish_grab,
        "bearish_grab": bearish_grab,
        "grab_strength": round(total_range, 4)
    }

if __name__ == "__main__":
    print(get_technical_indicators("BTCUSDT"))
    print(get_defillama_metrics("aave"))
    print(get_dune_macro_metrics())
