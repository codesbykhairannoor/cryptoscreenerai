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
        r = requests.get(url, timeout=3, verify=False)
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
    """Fetch Macro On-Chain metrics from Dune Analytics"""
    try:
        api_key = os.getenv("DUNE_API_KEY")
        if not api_key: return {"macro_sentiment": "NEUTRAL"}
        query_id = 3403
        url = f"https://api.dune.com/api/v1/query/{query_id}/results/latest"
        headers = {"X-Dune-API-Key": api_key}
        r = requests.get(url, headers=headers, timeout=3)
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
