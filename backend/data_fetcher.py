import requests
import pandas as pd
import numpy as np
import time
import os
from dotenv import load_dotenv

load_dotenv()

import requests
import pandas as pd
import numpy as np
import time
import os
from dotenv import load_dotenv

load_dotenv()


# ─── 1. VOLUME PROFILE / POINT OF CONTROL ────────────────────────────────────

def get_volume_profile(symbol: str, interval: str = "15m", limit: int = 96) -> dict:
    """
    Hitung Volume Profile dan Point of Control (POC) dari candle Bitget.

    POC = harga dengan volume terbanyak diperdagangkan.
    Harga selalu gravitasi ke POC — institusi tahu ini.

    Return:
      poc          : harga POC
      value_area_high : batas atas Value Area (70% volume)
      value_area_low  : batas bawah Value Area (70% volume)
      price_vs_poc : "ABOVE" / "BELOW" / "AT" (posisi harga vs POC)
      poc_distance_pct: jarak harga dari POC dalam %
    """
    try:
        url = (f"https://api.bitget.com/api/v2/mix/market/history-candles"
               f"?symbol={symbol}&granularity={interval}&limit={limit}&productType=USDT-FUTURES")
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code != 200:
            return {"poc": 0, "value_area_high": 0, "value_area_low": 0,
                    "price_vs_poc": "UNKNOWN", "poc_distance_pct": 0}

        data = r.json().get('data', [])
        if len(data) < 10:
            return {"poc": 0, "value_area_high": 0, "value_area_low": 0,
                    "price_vs_poc": "UNKNOWN", "poc_distance_pct": 0}

        highs  = [float(c[2]) for c in data]
        lows   = [float(c[3]) for c in data]
        closes = [float(c[4]) for c in data]
        vols   = [float(c[5]) for c in data]

        # Buat price buckets (50 level antara low dan high)
        price_min = min(lows)
        price_max = max(highs)
        if price_max <= price_min:
            return {"poc": closes[-1], "value_area_high": price_max,
                    "value_area_low": price_min, "price_vs_poc": "AT", "poc_distance_pct": 0}

        n_buckets = 50
        bucket_size = (price_max - price_min) / n_buckets
        buckets = [0.0] * n_buckets

        # Distribusikan volume ke bucket berdasarkan typical price
        for i in range(len(data)):
            typical = (highs[i] + lows[i] + closes[i]) / 3
            bucket_idx = min(int((typical - price_min) / bucket_size), n_buckets - 1)
            buckets[bucket_idx] += vols[i]

        # POC = bucket dengan volume terbanyak
        poc_idx = buckets.index(max(buckets))
        poc = round(price_min + (poc_idx + 0.5) * bucket_size, 6)

        # Value Area = 70% total volume di sekitar POC
        total_vol = sum(buckets)
        target_vol = total_vol * 0.70
        va_vol = buckets[poc_idx]
        lo, hi = poc_idx, poc_idx

        while va_vol < target_vol and (lo > 0 or hi < n_buckets - 1):
            add_lo = buckets[lo - 1] if lo > 0 else 0
            add_hi = buckets[hi + 1] if hi < n_buckets - 1 else 0
            if add_hi >= add_lo:
                hi = min(hi + 1, n_buckets - 1)
                va_vol += add_hi
            else:
                lo = max(lo - 1, 0)
                va_vol += add_lo

        value_area_high = round(price_min + (hi + 1) * bucket_size, 6)
        value_area_low  = round(price_min + lo * bucket_size, 6)
        current_price   = closes[-1]

        poc_dist = ((current_price - poc) / poc * 100) if poc > 0 else 0
        if abs(poc_dist) < 0.1:
            price_vs_poc = "AT"
        elif current_price > poc:
            price_vs_poc = "ABOVE"
        else:
            price_vs_poc = "BELOW"

        return {
            "poc":              round(poc, 6),
            "value_area_high":  value_area_high,
            "value_area_low":   value_area_low,
            "price_vs_poc":     price_vs_poc,
            "poc_distance_pct": round(poc_dist, 3),
        }
    except Exception:
        return {"poc": 0, "value_area_high": 0, "value_area_low": 0,
                "price_vs_poc": "UNKNOWN", "poc_distance_pct": 0}


# ─── 2. HIGHER TIMEFRAME KEY LEVELS (Daily/Weekly) ───────────────────────────

def get_htf_key_levels(symbol: str) -> dict:
    """
    Ambil level kritis dari Daily dan Weekly candle.
    Institusi selalu tahu level ini — sering jadi reversal point.

    Return:
      daily_high, daily_low   : high/low candle hari ini
      weekly_high, weekly_low : high/low candle minggu ini
      near_daily_level        : True kalau harga dalam 0.5% dari daily high/low
      near_weekly_level       : True kalau harga dalam 1% dari weekly high/low
      level_bias              : "RESISTANCE" / "SUPPORT" / "NEUTRAL"
    """
    try:
        result = {
            "daily_high": 0, "daily_low": 0,
            "weekly_high": 0, "weekly_low": 0,
            "near_daily_level": False, "near_weekly_level": False,
            "level_bias": "NEUTRAL",
        }

        # Daily candle (ambil 2 candle: hari ini + kemarin)
        url_d = (f"https://api.bitget.com/api/v2/mix/market/history-candles"
                 f"?symbol={symbol}&granularity=1D&limit=2&productType=USDT-FUTURES")
        r_d = requests.get(url_d, timeout=5, verify=False)
        if r_d.status_code == 200:
            data_d = r_d.json().get('data', [])
            if data_d:
                result["daily_high"] = float(data_d[0][2])
                result["daily_low"]  = float(data_d[0][3])

        # Weekly candle
        url_w = (f"https://api.bitget.com/api/v2/mix/market/history-candles"
                 f"?symbol={symbol}&granularity=1W&limit=2&productType=USDT-FUTURES")
        r_w = requests.get(url_w, timeout=5, verify=False)
        if r_w.status_code == 200:
            data_w = r_w.json().get('data', [])
            if data_w:
                result["weekly_high"] = float(data_w[0][2])
                result["weekly_low"]  = float(data_w[0][3])

        # Ambil harga sekarang
        url_t = (f"https://api.bitget.com/api/v2/mix/market/tickers"
                 f"?symbol={symbol}&productType=USDT-FUTURES")
        r_t = requests.get(url_t, timeout=5, verify=False)
        if r_t.status_code != 200:
            return result

        tickers = r_t.json().get('data', [])
        current = float(tickers[0].get('lastPr', 0)) if tickers else 0
        if current == 0:
            return result

        # Cek proximity ke level
        dh, dl = result["daily_high"], result["daily_low"]
        wh, wl = result["weekly_high"], result["weekly_low"]

        near_dh = dh > 0 and abs(current - dh) / dh < 0.005  # dalam 0.5%
        near_dl = dl > 0 and abs(current - dl) / dl < 0.005
        near_wh = wh > 0 and abs(current - wh) / wh < 0.010  # dalam 1%
        near_wl = wl > 0 and abs(current - wl) / wl < 0.010

        result["near_daily_level"]  = near_dh or near_dl
        result["near_weekly_level"] = near_wh or near_wl

        # Bias: dekat high = resistance, dekat low = support
        if near_dh or near_wh:
            result["level_bias"] = "RESISTANCE"
        elif near_dl or near_wl:
            result["level_bias"] = "SUPPORT"

        return result
    except Exception:
        return {"daily_high": 0, "daily_low": 0, "weekly_high": 0, "weekly_low": 0,
                "near_daily_level": False, "near_weekly_level": False, "level_bias": "NEUTRAL"}


# ─── 5. FIBONACCI RETRACEMENT LEVELS ─────────────────────────────────────────

def get_fibonacci_levels(symbol: str, interval: str = "1h", limit: int = 50) -> dict:
    """
    Hitung Fibonacci Retracement dari swing high/low terbaru.
    Level 0.382, 0.5, 0.618 adalah yang paling sering dipakai institusi.

    Return:
      swing_high, swing_low : titik referensi
      fib_382, fib_500, fib_618 : level retracement
      fib_786 : level retracement dalam (sering jadi demand zone)
      current_fib_level : level fib terdekat dengan harga sekarang
      at_fib_support : True kalau harga di level fib support (untuk BUY)
      at_fib_resistance : True kalau harga di level fib resistance (untuk SELL)
    """
    try:
        url = (f"https://api.bitget.com/api/v2/mix/market/history-candles"
               f"?symbol={symbol}&granularity={interval}&limit={limit}&productType=USDT-FUTURES")
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code != 200:
            return {}

        data = r.json().get('data', [])
        if len(data) < 20:
            return {}

        highs  = [float(c[2]) for c in data]
        lows   = [float(c[3]) for c in data]
        closes = [float(c[4]) for c in data]

        # Cari swing high dan swing low dari 50 candle terakhir
        swing_high = max(highs)
        swing_low  = min(lows)
        current    = closes[-1]
        diff       = swing_high - swing_low

        if diff <= 0:
            return {}

        # Fibonacci retracement levels (dari swing high ke swing low)
        fib_236 = round(swing_high - diff * 0.236, 6)
        fib_382 = round(swing_high - diff * 0.382, 6)
        fib_500 = round(swing_high - diff * 0.500, 6)
        fib_618 = round(swing_high - diff * 0.618, 6)
        fib_786 = round(swing_high - diff * 0.786, 6)

        # Tolerance: dalam 0.3% dari level = "at level"
        tolerance = current * 0.003
        levels = {
            "0.236": fib_236, "0.382": fib_382, "0.500": fib_500,
            "0.618": fib_618, "0.786": fib_786,
        }

        # Cari level terdekat
        closest_level = min(levels.items(), key=lambda x: abs(current - x[1]))
        at_level = abs(current - closest_level[1]) < tolerance

        # Support = harga di bawah swing high, mendekati fib level dari atas
        # Resistance = harga di atas swing low, mendekati fib level dari bawah
        at_fib_support    = at_level and current < swing_high * 0.99
        at_fib_resistance = at_level and current > swing_low  * 1.01

        return {
            "swing_high":       round(swing_high, 6),
            "swing_low":        round(swing_low, 6),
            "fib_236":          fib_236,
            "fib_382":          fib_382,
            "fib_500":          fib_500,
            "fib_618":          fib_618,
            "fib_786":          fib_786,
            "current_fib_level": closest_level[0] if at_level else "NONE",
            "at_fib_support":    at_fib_support,
            "at_fib_resistance": at_fib_resistance,
        }
    except Exception:
        return {}


# ─── 6. TICK DATA / STOP HUNT DETECTION ──────────────────────────────────────

def detect_stop_hunt(symbol: str) -> dict:
    """
    Deteksi "stop hunt" — momen ketika institusi sengaja push harga
    ke level stop loss retail sebelum reversal.

    Ciri-ciri stop hunt:
    1. Harga spike melewati level support/resistance dengan wick panjang
    2. Langsung balik ke dalam range (close kembali di atas/bawah level)
    3. Volume spike saat wick terjadi

    Return:
      bull_stop_hunt : True = stop hunt ke bawah (sweep low, lalu naik) → BUY signal
      bear_stop_hunt : True = stop hunt ke atas (sweep high, lalu turun) → SELL signal
      hunt_strength  : 0-3 (berapa banyak konfirmasi)
    """
    try:
        # Ambil candle 1m untuk deteksi wick
        url_1m = (f"https://api.bitget.com/api/v2/mix/market/history-candles"
                  f"?symbol={symbol}&granularity=1m&limit=10&productType=USDT-FUTURES")
        r = requests.get(url_1m, timeout=5, verify=False)
        if r.status_code != 200:
            return {"bull_stop_hunt": False, "bear_stop_hunt": False, "hunt_strength": 0}
# halo
        data = r.json().get('data', [])
        if len(data) < 5:
            return {"bull_stop_hunt": False, "bear_stop_hunt": False, "hunt_strength": 0}

        opens  = [float(c[1]) for c in data]
        highs  = [float(c[2]) for c in data]
        lows   = [float(c[3]) for c in data]
        closes = [float(c[4]) for c in data]
        vols   = [float(c[5]) for c in data]

        avg_vol = sum(vols[:-1]) / len(vols[:-1]) if len(vols) > 1 else 1

        bull_hunt = False
        bear_hunt = False
        strength  = 0

        # Cek 3 candle terakhir untuk stop hunt pattern
        for i in range(-3, 0):
            body      = abs(closes[i] - opens[i])
            wick_down = min(opens[i], closes[i]) - lows[i]
            wick_up   = highs[i] - max(opens[i], closes[i])
            candle_range = highs[i] - lows[i]

            if candle_range == 0:
                continue

            # Bull stop hunt: wick bawah > 60% range + close di atas tengah + volume spike
            if (wick_down > candle_range * 0.6 and
                closes[i] > (highs[i] + lows[i]) / 2 and
                vols[i] > avg_vol * 1.5):
                bull_hunt = True
                strength += 1

            # Bear stop hunt: wick atas > 60% range + close di bawah tengah + volume spike
            if (wick_up > candle_range * 0.6 and
                closes[i] < (highs[i] + lows[i]) / 2 and
                vols[i] > avg_vol * 1.5):
                bear_hunt = True
                strength += 1

        return {
            "bull_stop_hunt": bull_hunt,
            "bear_stop_hunt": bear_hunt,
            "hunt_strength":  min(strength, 3),
        }
    except Exception:
        return {"bull_stop_hunt": False, "bear_stop_hunt": False, "hunt_strength": 0}


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

def get_binance_ls_ratio(symbol):
    """
    Nyontek data Long/Short Ratio dari Binance (Volume terbesar)
    Berguna untuk melihat apakah retail sedang dominan Long atau Short.
    Jika LS Ratio > 2.5, artinya retail terlalu banyak Long = Rawan Dump (Stop Hunt).
    Jika LS Ratio < 0.5, artinya retail terlalu banyak Short = Rawan Pump (Short Squeeze).
    """
    try:
        clean_symbol = symbol.replace("USDT_UMCBL", "USDT").replace("_UMCBL", "")
        # Fallback to USDT if perp or something else is attached
        if not clean_symbol.endswith("USDT"):
            clean_symbol = clean_symbol.split("_")[0] + "USDT"
            
        url = f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={clean_symbol}&period=15m&limit=1"
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code == 200:
            data = r.json()
            if data and isinstance(data, list):
                return float(data[0].get('longShortRatio', 1.0))
    except: pass
    return 1.0

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

        # 4H TREND — penting untuk filter falling knife
        url_4h = f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&granularity=4h&limit=50&productType=USDT-FUTURES"
        r_4h = requests.get(url_4h, timeout=5, verify=False)
        trend_4h = "NEUTRAL"
        ema_50_4h = 0
        if r_4h.status_code == 200:
            data_4h = r_4h.json().get('data', [])
            if len(data_4h) >= 10:
                closes_4h = [float(c[4]) for c in data_4h]
                # EMA 50 pada 4h = trend medium term
                ema_4h = closes_4h[0]
                k_4h = 2 / (50 + 1)
                for c in closes_4h:
                    ema_4h = c * k_4h + ema_4h * (1 - k_4h)
                ema_50_4h = ema_4h
                last_4h = closes_4h[-1]
                trend_4h = "BULLISH" if last_4h > ema_4h * 1.001 else \
                           "BEARISH" if last_4h < ema_4h * 0.999 else "NEUTRAL"

                # Slope 4h: apakah trend sedang naik atau turun?
                # Bandingkan EMA 10 candle lalu vs sekarang
                if len(closes_4h) >= 20:
                    ema_old = closes_4h[0]
                    for c in closes_4h[:-10]:
                        ema_old = c * k_4h + ema_old * (1 - k_4h)
                    # Kalau EMA sekarang < EMA 10 candle lalu = downtrend
                    if ema_4h < ema_old * 0.998:
                        trend_4h = "BEARISH"  # Override: EMA turun = bearish

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

        # 7. ATR 14 (True Range)
        trs = []
        for i in range(1, len(df_cur)):
            high_i  = df_cur['high'].iloc[i]
            low_i   = df_cur['low'].iloc[i]
            close_p = df_cur['close'].iloc[i - 1]
            tr = max(high_i - low_i, abs(high_i - close_p), abs(low_i - close_p))
            trs.append(tr)
        atr_val = round(sum(trs[-14:]) / 14, 6) if len(trs) >= 14 else round(mark_price * 0.015, 6)

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
            "flying_rocket": flying_rocket
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
