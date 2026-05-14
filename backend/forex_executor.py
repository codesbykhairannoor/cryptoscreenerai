"""
FOREX SCALPER v8.0 - GENIUS SCALPER EDITION
=============================================
Perbaikan besar dari v7.0:
- FIX: DXY proxy diganti dari PAXG ke Yahoo Finance DX-Y.NYB (akurat)
- FIX: RR dinaikkan dari 1.5:1 ke 2:1 (take_profit_val 40 poin, stop_loss_val 20 poin)
- FIX: Cache candle 30m dari 300s ke 60s (data lebih fresh)
- FIX: Auto-close threshold konsisten dengan stop_loss_val (bukan $7 flat)
- FIX: Hard block in_demand/in_supply di _determine_side()
- FIX: Multi-trade dihapus — 1 trade fokus, lot bisa dinaikkan
- FIX: Trailing stop_loss_val aktif dari 15 poin (bukan 12), gap minimal 10 poin
- FIX: EMA 200 butuh 200 candle — sekarang pakai EMA 50 dengan label benar
- FIX: Consecutive loss pause (port dari crypto engine)
- FIX: _close_attempted dibersihkan setiap 10 menit
- FIX: Session overlap London+NY (12-16 UTC) dikurangi trades
- NEW: Micro-scalp mode — deteksi momentum 1m untuk entry presisi
- NEW: Spread-adjusted take_profit_val/stop_loss_val — take_profit_val/stop_loss_val otomatis menyesuaikan spread saat ini
- NEW: News impact filter — skip entry 15 menit sebelum/sesudah high-impact news
- NEW: Multi-timeframe confluence — butuh minimal 2 TF aligned sebelum entry
"""
import requests, os, time, datetime
from dotenv import load_dotenv
from notifier import send_telegram_message, format_trade_message
load_dotenv()

# ── KONFIGURASI UTAMA ──────────────────────────────────────────────────────────
MAX_POSITIONS        = 3      # Maksimal 3 trade agar lebih banyak peluang cuan
SCAN_INTERVAL        = 3
COOLDOWN_AFTER_TRADE = 120    # Turun ke 2 menit agar lebih rajin
EQUITY_GUARD_PCT     = 0.93
MAX_SPREAD_POINTS    = 35
MIN_MOMENTUM_SCORE   = 60     # Skor Institusional (Akurasi Tinggi)
CANDLE_LIMIT         = 100

# ── take_profit_val/stop_loss_val — RR 1.6:1 (Hasil Optimasi Backtest Massive v9.0) ───────────────────
# Berdasarkan 3000 candle 1m, stop_loss_val 25 memberikan Win Rate tertinggi (44.1%)
SCALP_TP_POINTS      = 40.0   # Target profit tetap 40 poin
SCALP_SL_POINTS      = 25.0   # Stop Loss dinaikkan ke 25 agar tidak gampang kena noise
MIN_LOT_PER_TRADE    = 0.01
MAX_LOT_PER_TRADE    = 0.02   # Max 0.02 lot per trade

# ── ATH/ATL DETECTION ─────────────────────────────────────────────────────────
ATH_BLOCK_PCT        = 0.80
ATL_BLOCK_PCT        = 0.20

# ── SESSION LOSS LIMIT ────────────────────────────────────────────────────────
SESSION_MAX_LOSS_USD = 15.0

# ── CONSECUTIVE LOSS PROTECTION ───────────────────────────────────────────────
CONSEC_LOSS_LIMIT    = 2      # Pause setelah 2 loss berturut-turut
CONSEC_LOSS_PAUSE    = 1800   # 30 menit pause

# ── DXY THRESHOLDS ────────────────────────────────────────────────────────────
DXY_STRONG_THRESHOLD = 0.15   # DXY naik 0.15% = bullish USD = bearish gold
DXY_WEAK_THRESHOLD   = -0.15  # DXY turun 0.15% = bearish USD = bullish gold

class ForexExecutor:
    def __init__(self):
        self.api_token   = os.getenv("FOREX_META_API_TOKEN")
        self.account_id  = os.getenv("FOREX_ACCOUNT_ID")
        self.base_url    = "https://mt-client-api-v1.london.agiliumtrade.ai"
        self.is_active   = bool(self.api_token and self.account_id)
        self._working_symbol    = None
        self._positions_cache   = []
        self._positions_cache_ts = 0
        self._price_history     = []
        self._last_known_price  = 0
        self._last_known_spread = 999
        self._close_attempted   = {}   # {pos_id: timestamp} — dibersihkan setiap 10 menit
        self._dxy_cache         = {"change": 0.0, "trend": "NEUTRAL", "ts": 0}
        # Session loss tracking
        self._session_loss_usd  = 0.0
        self._session_start_ts  = time.time()
        self._last_session_hour = -1
        # Consecutive loss tracking
        self._consec_losses     = 0
        self._consec_pause_until = 0
        self._last_close_clean  = time.time()
        self._pending_order_ts  = 0  # FIX: Cegah multi-trade saat REST lag

        if self.is_active:
            try:
                self._working_symbol = self._resolve_symbol("XAUUSD")
            except Exception:
                self._working_symbol = "XAUUSDc"
        else:
            print("[FOREX] MetaAPI credentials missing. Forex engine disabled.", flush=True)

    #  ACCOUNT & CONNECTION 

    def get_account_information(self):
        if not self.is_active: return None
        try:
            url = self.base_url + "/users/current/accounts/" + self.account_id + "/account-information"
            res = requests.get(url, headers={"auth-token": self.api_token}, timeout=10)
            if res.status_code == 200: return res.json()
        except Exception as e:
            print("[FOREX ERROR] Account fetch failed: " + str(e))
        return None

    def test_connection(self):
        info = self.get_account_information()
        if info and "balance" in info:
            return True, "Connected to MT5 (Balance: $" + str(info["balance"]) + ")"
        return False, "MT5 Connection Failed."

    #  SYMBOL RESOLUTION 

    def _resolve_symbol(self, base):
        for s in ["", "c", ".m", ".i", "+", "#", "m"]:
            sym = base + s
            try:
                url = self.base_url + "/users/current/accounts/" + self.account_id + "/symbols/" + sym + "/current-price"
                res = requests.get(url, headers={"auth-token": self.api_token}, timeout=5)
                if res.status_code == 200 and float(res.json().get("bid", 0)) > 0:
                    return sym
            except Exception:
                continue
        return base

    #  PRICE FETCHING 

    def get_live_price(self, symbol=None):
        sym = symbol or self._working_symbol or "XAUUSD"
        try:
            url = self.base_url + "/users/current/accounts/" + self.account_id + "/symbols/" + sym + "/current-price"
            res = requests.get(url, headers={"auth-token": self.api_token}, timeout=5)
            if res.status_code == 200:
                d   = res.json()
                bid = float(d.get("bid", 0))
                ask = float(d.get("ask", bid))
                spread = round((ask - bid) * 10, 1)
                return {"bid": bid, "ask": ask, "spread_points": spread, "mid": (bid + ask) / 2}
        except Exception as e:
            print("[FOREX PRICE ERROR] " + str(e))
        return {"bid": 0, "ask": 0, "spread_points": 999, "mid": 0}

    #  CANDLE DATA 

    def get_candles(self, symbol=None, timeframe="30m", limit=CANDLE_LIMIT):
        sym = symbol or self._working_symbol or "XAUUSD"
        
        if not hasattr(self, '_candle_cache'): self._candle_cache = {}
        now = time.time()
        cache_key = f"{sym}_{timeframe}_{limit}"
        
        # Cache TTL disesuaikan — candle pendek lebih sering diupdate
        if timeframe == "1m":              cache_ttl = 10   # 10 detik
        elif timeframe == "5m":            cache_ttl = 30   # 30 detik
        elif timeframe in ("15m", "30m"):  cache_ttl = 60   # 1 menit (sebelumnya 300 = stale!)
        elif timeframe in ("1h",):         cache_ttl = 180  # 3 menit
        else:                              cache_ttl = 600  # 4h, 1D = 10 menit
        
        if cache_key in self._candle_cache and now - self._candle_cache[cache_key]['ts'] < cache_ttl:
            return self._candle_cache[cache_key]['data']
            
        headers = {"auth-token": self.api_token}
        hosts   = [
            "https://mt-market-data-client-api-v1.new-york.agiliumtrade.ai",
            "https://mt-market-data-client-api-v1.london.agiliumtrade.ai",
            "https://mt-market-data-client-api-v1.singapore.agiliumtrade.ai",
        ]
        for host in hosts:
            url = host + "/users/current/accounts/" + self.account_id + "/historical-market-data/symbols/" + sym + "/timeframes/" + timeframe + "/candles?limit=" + str(limit)
            try:
                res = requests.get(url, headers=headers, timeout=15)
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, list) and len(data) > 0:
                        self._candle_cache[cache_key] = {'ts': now, 'data': data}
                        return data
            except Exception:
                continue
        return []

    #  DXY MACRO CONTEXT 

    def _get_dxy_context(self):
        """
        Ambil DXY (US Dollar Index) dari Yahoo Finance — data akurat langsung dari pasar.
        DXY kuat = bearish gold bias. DXY lemah = bullish gold bias.
        Cache 5 menit.

        Sebelumnya pakai PAXG sebagai proxy — tidak akurat karena PAXG adalah
        token emas fisik, bukan DXY. Sekarang pakai DX-Y.NYB langsung.
        """
        now = time.time()
        if now - self._dxy_cache["ts"] < 300:
            return self._dxy_cache

        try:
            # Yahoo Finance — DX-Y.NYB adalah US Dollar Index futures
            url = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=5m&range=1d"
            res = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            if res.status_code == 200:
                data = res.json()
                result = data.get("chart", {}).get("result", [])
                if result:
                    closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
                    closes = [c for c in closes if c is not None]
                    if len(closes) >= 2:
                        prev  = closes[-2]
                        curr  = closes[-1]
                        change = ((curr - prev) / prev * 100) if prev > 0 else 0.0
                        trend = "NEUTRAL"
                        if change > DXY_STRONG_THRESHOLD:  trend = "BULLISH"
                        elif change < DXY_WEAK_THRESHOLD:  trend = "BEARISH"
                        self._dxy_cache = {"change": round(change, 3), "trend": trend, "ts": now, "value": round(curr, 3)}
                        return self._dxy_cache
        except Exception:
            pass

        # Fallback: coba Stooq sebagai alternatif
        try:
            url2 = "https://stooq.com/q/l/?s=dx.f&f=sd2t2ohlcv&h&e=csv"
            res2 = requests.get(url2, timeout=5)
            if res2.status_code == 200:
                lines = res2.text.strip().split("\n")
                if len(lines) >= 2:
                    parts = lines[-1].split(",")
                    if len(parts) >= 5:
                        curr  = float(parts[4])  # close
                        prev  = float(parts[3])  # open
                        change = ((curr - prev) / prev * 100) if prev > 0 else 0.0
                        trend = "NEUTRAL"
                        if change > DXY_STRONG_THRESHOLD:  trend = "BULLISH"
                        elif change < DXY_WEAK_THRESHOLD:  trend = "BEARISH"
                        self._dxy_cache = {"change": round(change, 3), "trend": trend, "ts": now, "value": round(curr, 3)}
                        return self._dxy_cache
        except Exception:
            pass

        self._dxy_cache["ts"] = now
        return self._dxy_cache

    # ?????? ORDER BOOK & WHALE DETECTION (via PAXG proxy) ????????????????????????????????????????????????????????????????????????

    def _calc_adx_forex(self, period: int = 14) -> float:
        """
        Hitung ADX untuk XAUUSD dari candle MetaAPI.
        ADX > 22 = trending, boleh entry.
        ADX < 18 = ranging, skip.
        """
        try:
            candles = self.get_candles(timeframe="30m", limit=period * 3)
            if len(candles) < period + 2:
                return 25.0

            highs  = [float(c.get("high",  0)) for c in candles]
            lows   = [float(c.get("low",   0)) for c in candles]
            closes = [float(c.get("close", 0)) for c in candles]

            trs, plus_dm, minus_dm = [], [], []
            for i in range(1, len(closes)):
                tr   = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
                up   = highs[i]  - highs[i-1]
                down = lows[i-1] - lows[i]
                trs.append(tr)
                plus_dm.append(up   if up > down and up > 0   else 0)
                minus_dm.append(down if down > up and down > 0 else 0)

            def wilder(data, n):
                r = [sum(data[:n]) / n]
                for i in range(n, len(data)):
                    r.append(r[-1] - r[-1]/n + data[i])
                return r

            atr_s  = wilder(trs,      period)
            plus_s = wilder(plus_dm,  period)
            minus_s= wilder(minus_dm, period)

            di_p = [100 * p / a if a > 0 else 0 for p, a in zip(plus_s,  atr_s)]
            di_m = [100 * m / a if a > 0 else 0 for m, a in zip(minus_s, atr_s)]

            dx_list = [100 * abs(p - m) / (p + m) if (p + m) > 0 else 0 for p, m in zip(di_p, di_m)]
            adx = sum(dx_list[-period:]) / period if len(dx_list) >= period else 25.0
            return round(adx, 2)
        except Exception:
            return 25.0

    def _calc_vol_regime_forex(self) -> dict:
        """
        Hitung volatility regime XAUUSD.
        ATR candle terakhir vs ATR baseline 20 periode.
        """
        try:
            candles = self.get_candles(timeframe="30m", limit=30)
            if len(candles) < 22:
                return {"regime": "NORMAL", "atr_ratio": 1.0}

            highs  = [float(c.get("high",  0)) for c in candles]
            lows   = [float(c.get("low",   0)) for c in candles]
            closes = [float(c.get("close", 0)) for c in candles]

            trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
                   for i in range(1, len(closes))]

            atr_current  = trs[-1]
            atr_baseline = sum(trs[-20:]) / 20
            atr_ratio    = atr_current / atr_baseline if atr_baseline > 0 else 1.0

            if atr_ratio > 3.0:   regime = "HIGH_VOL"
            elif atr_ratio < 0.3: regime = "LOW_VOL"
            else:                 regime = "NORMAL"

            return {"regime": regime, "atr_ratio": round(atr_ratio, 2)}
        except Exception:
            return {"regime": "NORMAL", "atr_ratio": 1.0}

    def _calc_ev_forex(self, side: str, ind: dict, score: int) -> float:
        """
        Expected Value untuk XAUUSD trade ??? sudah include spread cost.
        EV = (P_win x TP_pct) - (P_loss x SL_pct) - spread_cost
        take_profit_val = 20 poin, stop_loss_val = 8 poin, spread ~2.8 poin
        Spread cost = 2.8 / entry_price ~ 0.006% per trade
        """
        base_p_win = 0.30 + (score / 100) * 0.35

        adj = 0.0
        whale = ind.get("whale_signal", "NORMAL")
        obi   = ind.get("obi", 0)
        if side == "buy"  and whale == "WHALE_BUY":   adj += 0.08
        if side == "sell" and whale == "WHALE_SELL":  adj += 0.08
        if side == "buy"  and whale == "WHALE_SELL":  adj -= 0.10
        if side == "sell" and whale == "WHALE_BUY":   adj -= 0.10
        if side == "buy"  and obi > 0.15:  adj += 0.05
        if side == "sell" and obi < -0.15: adj += 0.05

        pump = ind.get("pump_signal", "NONE")
        if side == "buy"  and pump in ("PUMP_IMMINENT", "BREAKOUT_UP"):   adj += 0.07
        if side == "sell" and pump in ("DUMP_IMMINENT", "BREAKOUT_DOWN"): adj += 0.07

        # Demand/Supply zone bonus
        if side == "buy"  and ind.get("in_demand", False): adj += 0.06
        if side == "sell" and ind.get("in_supply", False): adj += 0.06

        p_win  = min(0.75, max(0.20, base_p_win + adj))
        p_loss = 1.0 - p_win

        # XAUUSD: take_profit_val 30 poin / entry ~4700 = ~0.64%, stop_loss_val 20 poin = ~0.43%
        # Sesuai konstanta SCALP_TP_POINTS=30 dan SCALP_SL_POINTS=20
        entry_approx = self._last_known_price if self._last_known_price > 0 else 4700
        tp_pct = SCALP_TP_POINTS / entry_approx
        sl_pct = SCALP_SL_POINTS / entry_approx

        # Spread cost: 2.8 poin / entry = biaya masuk + keluar
        spread_cost = 2.8 / entry_approx

        ev_gross = (p_win * tp_pct) - (p_loss * sl_pct)
        ev_net   = ev_gross - spread_cost  # EV setelah spread
        return round(ev_net, 5)

    def _get_gold_orderbook(self):
        """
        Analisis tekanan beli/jual XAUUSD dari tick data MetaAPI.

        Karena MetaAPI tidak expose order book depth langsung,
        gue pakai dua pendekatan dari data yang tersedia:

        1. Bid/Ask spread momentum: kalau ask naik lebih cepat dari bid
           = buyer pressure. Kalau bid turun lebih cepat = seller pressure.

        2. Candle body analysis dari 5 candle terakhir:
           - Candle bullish besar + volume tinggi = buyer dominance
           - Candle bearish besar + volume tinggi = seller dominance
           - Ini proxy yang lebih akurat dari PAXG order book

        Return:
          obi   : -1 to +1 (positif = buyer dominance)
          whale : WHALE_BUY / WHALE_SELL / NORMAL
        """
        try:
            # Ambil 10 candle 1m terakhir dari MetaAPI
            candles = self.get_candles(timeframe="1m", limit=10)
            if len(candles) < 5:
                # Fallback: pakai harga live bid/ask
                price_data = self.get_live_price()
                bid = price_data.get("bid", 0)
                ask = price_data.get("ask", 0)
                if bid > 0 and ask > 0:
                    # Spread kecil = market liquid, tidak ada tekanan kuat
                    spread = ask - bid
                    # Kalau mid lebih dekat ke ask = buyer pressure
                    mid = (bid + ask) / 2
                    obi = round((mid - bid) / spread - 0.5, 4) if spread > 0 else 0.0
                    return {"obi": obi, "whale": "NORMAL"}
                return {"obi": 0.0, "whale": "NORMAL"}

            closes = [float(c.get("close", 0)) for c in candles]
            opens  = [float(c.get("open",  0)) for c in candles]
            highs  = [float(c.get("high",  0)) for c in candles]
            lows   = [float(c.get("low",   0)) for c in candles]
            vols   = [float(c.get("tickVolume", c.get("volume", 1))) for c in candles]

            # Hitung body direction dan size per candle
            bull_vol = 0.0
            bear_vol = 0.0
            for i in range(len(closes)):
                body = abs(closes[i] - opens[i])
                total_range = highs[i] - lows[i] if highs[i] > lows[i] else 0.001
                body_ratio = body / total_range  # 0-1, makin besar makin decisive
                if closes[i] > opens[i]:
                    bull_vol += vols[i] * body_ratio
                else:
                    bear_vol += vols[i] * body_ratio

            total_vol = bull_vol + bear_vol
            obi = round((bull_vol - bear_vol) / total_vol, 4) if total_vol > 0 else 0.0

            # Whale detection: candle dengan body > 3x rata-rata = institutional move
            avg_body = sum(abs(closes[i] - opens[i]) for i in range(len(closes))) / len(closes)
            last_body = abs(closes[-1] - opens[-1])
            whale = "NORMAL"
            if last_body > avg_body * 3.0 and vols[-1] > sum(vols[:-1]) / len(vols[:-1]) * 2:
                whale = "WHALE_BUY" if closes[-1] > opens[-1] else "WHALE_SELL"

            return {"obi": obi, "whale": whale}

        except Exception:
            return {"obi": 0.0, "whale": "NORMAL"}

    def _get_gold_whale_trades(self):
        """
        Deteksi institutional activity dari tick volume MetaAPI.
        Candle dengan volume spike 3x rata-rata = institutional move.
        Lebih relevan dari PAXG fills karena data langsung dari broker.
        Return: WHALE_BUY / WHALE_SELL / NORMAL
        """
        try:
            candles = self.get_candles(timeframe="5m", limit=20)
            if len(candles) < 10:
                return "NORMAL"

            closes = [float(c.get("close", 0)) for c in candles]
            opens  = [float(c.get("open",  0)) for c in candles]
            vols   = [float(c.get("tickVolume", c.get("volume", 1))) for c in candles]

            avg_vol  = sum(vols[:-3]) / len(vols[:-3]) if len(vols) > 3 else 1
            last_vol = vols[-1]

            # Volume spike 3x + candle decisive = institutional
            if last_vol > avg_vol * 3.0:
                last_body = closes[-1] - opens[-1]
                if last_body > 0:
                    return "WHALE_BUY"
                elif last_body < 0:
                    return "WHALE_SELL"

            # Cek 3 candle terakhir: konsisten satu arah dengan volume tinggi
            recent_bull = sum(1 for i in range(-3, 0) if closes[i] > opens[i] and vols[i] > avg_vol * 1.5)
            recent_bear = sum(1 for i in range(-3, 0) if closes[i] < opens[i] and vols[i] > avg_vol * 1.5)
            if recent_bull >= 2: return "WHALE_BUY"
            if recent_bear >= 2: return "WHALE_SELL"

            return "NORMAL"

        except Exception:
            return "NORMAL"

    #  TECHNICAL INDICATORS 

    def _get_htf_trend(self, timeframe="4h"):
        """
        Ambil trend HTF dari candle MetaAPI.
        Pakai EMA 50 (bukan EMA 200 palsu dari 50 candle).
        EMA 200 butuh 200 candle — kalau hanya punya 50, hasilnya tidak akurat.
        EMA 50 dari 50 candle = akurat dan cukup untuk bias filter.
        """
        try:
            candles = self.get_candles(timeframe=timeframe, limit=60)
            if len(candles) < 20:
                return "NEUTRAL"
            closes = [float(c.get("close", 0)) for c in candles]
            # EMA 50 — akurat dengan 60 candle
            span = min(50, len(closes))
            ema = closes[0]
            k = 2 / (span + 1)
            for c in closes:
                ema = c * k + ema * (1 - k)
            last = closes[-1]
            # Slope: bandingkan EMA sekarang vs 5 candle lalu
            ema_old = closes[0]
            for c in closes[:-5]:
                ema_old = c * k + ema_old * (1 - k)
            slope_up   = ema > ema_old * 1.0005
            slope_down = ema < ema_old * 0.9995
            if last > ema * 1.001 and slope_up:   return "BULLISH"
            if last < ema * 0.999 and slope_down: return "BEARISH"
            if last > ema * 1.001: return "BULLISH"
            if last < ema * 0.999: return "BEARISH"
            return "NEUTRAL"
        except Exception:
            return "NEUTRAL"

    def _get_micro_momentum(self) -> dict:
        """
        MICRO-SCALP ENGINE: Deteksi momentum 1m untuk entry presisi.

        Scalper jenius tidak masuk di sembarang waktu — mereka tunggu
        momentum 1m aligned dengan sinyal 30m. Ini yang membedakan
        entry di harga bagus vs entry di tengah noise.

        Return:
          direction : "BUY" / "SELL" / "NEUTRAL"
          strength  : 0-3 (makin tinggi makin kuat)
          entry_ok  : True kalau momentum 1m siap untuk entry
        """
        try:
            candles_1m = self.get_candles(timeframe="1m", limit=5)
            if len(candles_1m) < 4:
                return {"direction": "NEUTRAL", "strength": 0, "entry_ok": False}

            closes = [float(c.get("close", 0)) for c in candles_1m]
            opens  = [float(c.get("open",  0)) for c in candles_1m]
            highs  = [float(c.get("high",  0)) for c in candles_1m]
            lows   = [float(c.get("low",   0)) for c in candles_1m]
            vols   = [float(c.get("tickVolume", c.get("volume", 1))) for c in candles_1m]

            avg_vol = sum(vols[:-1]) / len(vols[:-1]) if len(vols) > 1 else 1

            # Hitung berapa candle bullish/bearish dari 4 candle terakhir
            bull_count = sum(1 for i in range(-4, 0) if closes[i] > opens[i])
            bear_count = sum(1 for i in range(-4, 0) if closes[i] < opens[i])

            # Candle terakhir
            last_bull = closes[-1] > opens[-1]
            last_bear = closes[-1] < opens[-1]
            last_body = abs(closes[-1] - opens[-1])
            last_range = highs[-1] - lows[-1] if highs[-1] > lows[-1] else 0.001
            body_ratio = last_body / last_range

            # Volume konfirmasi
            vol_confirm = vols[-1] > avg_vol * 1.2

            strength = 0
            direction = "NEUTRAL"

            if bull_count >= 3 and last_bull:
                direction = "BUY"
                strength = 1
                if body_ratio > 0.5: strength += 1
                if vol_confirm: strength += 1
            elif bear_count >= 3 and last_bear:
                direction = "SELL"
                strength = 1
                if body_ratio > 0.5: strength += 1
                if vol_confirm: strength += 1

            # Entry OK kalau momentum kuat (strength >= 2)
            entry_ok = strength >= 2

            return {"direction": direction, "strength": strength, "entry_ok": entry_ok}
        except Exception:
            return {"direction": "NEUTRAL", "strength": 0, "entry_ok": False}

    def _get_mtf_confluence(self, side: str) -> dict:
        """
        MULTI-TIMEFRAME CONFLUENCE CHECK.

        Scalper jenius hanya masuk kalau minimal 2 timeframe aligned.
        1 TF aligned = noise. 2 TF aligned = sinyal. 3 TF aligned = high conviction.

        Timeframes yang dicek: 5m, 15m, 30m, 1h
        Metode: EMA 20 slope + price position

        Return:
          aligned_count : berapa TF yang aligned dengan side
          confluence    : "HIGH" (3+) / "MEDIUM" (2) / "LOW" (1) / "NONE" (0)
          details       : dict per TF
        """
        try:
            tfs = ["5m", "15m", "30m", "1h"]
            aligned = 0
            details = {}

            for tf in tfs:
                try:
                    candles = self.get_candles(timeframe=tf, limit=25)
                    if len(candles) < 10:
                        details[tf] = "UNKNOWN"
                        continue
                    closes = [float(c.get("close", 0)) for c in candles]
                    # EMA 20
                    ema = closes[0]
                    k = 2 / 21
                    for c in closes:
                        ema = c * k + ema * (1 - k)
                    last = closes[-1]
                    # Slope EMA
                    ema_old = closes[0]
                    for c in closes[:-3]:
                        ema_old = c * k + ema_old * (1 - k)
                    slope = "UP" if ema > ema_old * 1.0002 else ("DOWN" if ema < ema_old * 0.9998 else "FLAT")
                    tf_trend = "BULLISH" if last > ema and slope == "UP" else \
                               "BEARISH" if last < ema and slope == "DOWN" else "NEUTRAL"
                    details[tf] = tf_trend
                    if side == "buy"  and tf_trend == "BULLISH": aligned += 1
                    if side == "sell" and tf_trend == "BEARISH": aligned += 1
                except Exception:
                    details[tf] = "UNKNOWN"

            confluence = "HIGH" if aligned >= 3 else "MEDIUM" if aligned == 2 else "LOW" if aligned == 1 else "NONE"
            return {"aligned_count": aligned, "confluence": confluence, "details": details}
        except Exception:
            return {"aligned_count": 0, "confluence": "NONE", "details": {}}

    def _get_5m_entry_quality(self) -> dict:
        """
        PRECISION 5M ENTRY ENGINE: Deteksi SMC pada timeframe 5m.
        Mencari FVG, Order Block, dan Liquidity Grab untuk konfirmasi entry.
        """
        try:
            candles = self.get_candles(timeframe="5m", limit=15)
            if len(candles) < 10:
                return {"quality": 0, "signal": "NEUTRAL", "desc": "Insufficient data"}

            closes = [float(c.get("close", 0)) for c in candles]
            highs  = [float(c.get("high",  0)) for c in candles]
            lows   = [float(c.get("low",   0)) for c in candles]
            opens  = [float(c.get("open",  0)) for i, c in enumerate(candles)]
            
            # 1. 5m FVG (Fair Value Gap)
            fvg = "NONE"
            if highs[-3] < lows[-1]: fvg = "BULLISH_FVG"
            elif lows[-3] > highs[-1]: fvg = "BEARISH_FVG"
            
            # 2. 5m Liquidity Grab (Stop Hunt)
            liq_grab = (lows[-1] < min(lows[-5:-1]) and closes[-1] > lows[-1]) or \
                       (highs[-1] > max(highs[-5:-1]) and closes[-1] < highs[-1])
            
            # 3. 5m Candle Momentum
            last_body = closes[-1] - opens[-1]
            is_strong = abs(last_body) > (sum(abs(closes[i]-opens[i]) for i in range(-5, -1))/4) * 1.5

            quality = 0
            signal = "NEUTRAL"
            
            if last_body > 0: # Potential Long
                if fvg == "BULLISH_FVG": quality += 30
                if liq_grab and closes[-1] > opens[-1]: quality += 40
                if is_strong: quality += 30
                if quality >= 40: signal = "BULLISH_CONFIRM"
            else: # Potential Short
                if fvg == "BEARISH_FVG": quality += 30
                if liq_grab and closes[-1] < opens[-1]: quality += 40
                if is_strong: quality += 30
                if quality >= 40: signal = "BEARISH_CONFIRM"
                
            return {
                "quality": quality,
                "signal": signal,
                "fvg_5m": fvg,
                "liq_grab_5m": liq_grab,
                "momentum_5m": is_strong
            }
        except Exception as e:
            return {"quality": 0, "signal": "ERROR", "desc": str(e)}

    def _calc_indicators(self, timeframe="30m"):
        """
        XAUUSD Multi-Timeframe Indicator Engine v6.0.
        Data source: MetaAPI candle (default 30m).
        """
        candles = self.get_candles(timeframe=timeframe, limit=100)
        if len(candles) < 20:
            candles = self.get_candles(timeframe="15m", limit=100)  # fallback ke 15m

        # Fallback: price momentum dari harga live
        if len(candles) < 10:
            price_data = self.get_live_price()
            price = price_data.get("mid", 0)
            if price == 0:
                return {}
            self._price_history.append(price)
            if len(self._price_history) > 20:
                self._price_history.pop(0)

            trend = "NEUTRAL"; rsi_approx = 50.0
            liq_sweep = False; choch_bull = False; choch_bear = False

            if len(self._price_history) >= 5:
                prices = self._price_history
                if prices[-1] > prices[-5] * 1.0005:
                    trend = "BULLISH"; choch_bull = True
                elif prices[-1] < prices[-5] * 0.9995:
                    trend = "BEARISH"; choch_bear = True
                ups   = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i-1])
                downs = sum(1 for i in range(1, len(prices)) if prices[i] < prices[i-1])
                total = ups + downs
                if total > 0:
                    rsi_approx = round((ups / total) * 100, 1)
                if len(prices) >= 3:
                    liq_sweep = (prices[-1] < prices[-2] and prices[-1] > prices[-3]) or \
                                (prices[-1] > prices[-2] and prices[-1] < prices[-3])

            print("[FOREX FALLBACK] Using price momentum. RSI~" + str(rsi_approx) + " Trend:" + trend)
            return {
                "rsi": rsi_approx, "ema200": price, "atr": price * 0.001,
                "vwap": price, "vwap_dist": 0.0, "trend": trend,
                "trend_1h": "NEUTRAL", "trend_4h": "NEUTRAL",
                "mss_bullish": trend == "BULLISH" and liq_sweep,
                "mss_bearish": trend == "BEARISH" and liq_sweep,
                "choch_bullish": choch_bull, "choch_bearish": choch_bear,
                "fvg": "NONE", "is_liquidity_sweep": liq_sweep,
                "last_close": price, "vol_spike": False,
                "rsi_divergence": "NONE", "pump_signal": "NONE",
                "ob": "NONE",
            }

        closes = [float(c.get("close", 0)) for c in candles]
        highs  = [float(c.get("high",  0)) for c in candles]
        lows   = [float(c.get("low",   0)) for c in candles]
        vols   = [float(c.get("tickVolume", c.get("volume", 1))) for c in candles]

        # RSI 14
        period = 14
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i-1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period-1) + gains[i]) / period
            avg_loss = (avg_loss * (period-1) + losses[i]) / period
        rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100.0

        # RSI history untuk divergence
        rsi_history = []
        ag, al = sum(gains[:period]) / period, sum(losses[:period]) / period
        for i in range(period, len(gains)):
            ag = (ag * (period-1) + gains[i]) / period
            al = (al * (period-1) + losses[i]) / period
            rsi_history.append(100 - (100 / (1 + ag / al)) if al > 0 else 100.0)

        # EMA 200
        ema200 = closes[0]
        k = 2 / (200 + 1)
        for c in closes:
            ema200 = c * k + ema200 * (1 - k)

        # ATR 14
        trs = []
        for i in range(1, len(closes)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            trs.append(tr)
        atr = sum(trs[-14:]) / 14 if len(trs) >= 14 else 1.5

        # VWAP
        cum_pv = sum((highs[i]+lows[i]+closes[i])/3 * vols[i] for i in range(len(closes)))
        cum_v  = sum(vols)
        vwap   = cum_pv / cum_v if cum_v > 0 else closes[-1]
        vwap_dist = ((closes[-1] - vwap) / vwap * 100) if vwap > 0 else 0

        # Market Structure
        last_close  = closes[-1]
        recent_high = max(highs[-10:-1])
        recent_low  = min(lows[-10:-1])
        avg_vol     = sum(vols[-20:]) / 20 if len(vols) >= 20 else 1
        last_vol    = vols[-1]

        choch_bull = last_close > recent_high
        choch_bear = last_close < recent_low
        mss_bull   = choch_bull and last_vol > avg_vol * 1.5
        mss_bear   = choch_bear and last_vol > avg_vol * 1.5

        # Order Block: candle besar berlawanan sebelum move kuat
        ob = "NONE"
        if len(candles) >= 5:
            bodies = [abs(closes[i] - float(candles[i].get("open", closes[i]))) for i in range(len(closes))]
            avg_body = sum(bodies[-10:]) / 10 if len(bodies) >= 10 else 1
            last_body = bodies[-1]
            last_open = float(candles[-1].get("open", closes[-1]))
            if last_body > avg_body * 1.8:
                ob = "BULLISH_OB" if closes[-1] > last_open else "BEARISH_OB"

        # FVG
        fvg = "NONE"
        if len(candles) >= 3:
            if highs[-3] < lows[-1]:   fvg = "BULLISH_FVG"
            elif lows[-3] > highs[-1]: fvg = "BEARISH_FVG"

        # Liquidity Sweep
        liq_sweep = (lows[-1] < lows[-2] and closes[-1] > lows[-2]) or \
                    (highs[-1] > highs[-2] and closes[-1] < highs[-2])

        # Trend 30m
        trend = "NEUTRAL"
        if last_close > ema200: trend = "BULLISH"
        elif last_close < ema200: trend = "BEARISH"

        # Volume Spike
        vol_spike = last_vol > avg_vol * 2.0

        # ?????? ATH/ATL DETECTION ???????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        # Posisi harga dalam range 30m terakhir (0-100%)
        # 80%+ = dekat ATH = risky BUY (harga sudah tinggi, butuh effort untuk tembus)
        # 20%- = dekat ATL = risky SELL
        range_high = max(highs[-20:]) if len(highs) >= 20 else max(highs)
        range_low  = min(lows[-20:])  if len(lows)  >= 20 else min(lows)
        range_size = range_high - range_low
        price_position_pct = ((last_close - range_low) / range_size * 100) if range_size > 0 else 50
        near_ath = price_position_pct >= ATH_BLOCK_PCT * 100  # harga di 80%+ dari range
        near_atl = price_position_pct <= ATL_BLOCK_PCT * 100  # harga di 20%- dari range

        # ?????? PRICE VELOCITY (momentum detection) ??????????????????????????????????????????????????????????????????????????????????????????
        # Seberapa cepat harga bergerak dalam 5 candle terakhir
        # Velocity tinggi = momentum kuat = sinyal lebih reliable
        if len(closes) >= 6:
            price_change_5c = (closes[-1] - closes[-6]) / closes[-6] * 100 if closes[-6] > 0 else 0
            velocity = abs(price_change_5c)
            velocity_direction = "UP" if price_change_5c > 0 else "DOWN"
        else:
            velocity = 0
            velocity_direction = "FLAT"

        # RSI Divergence
        rsi_divergence = "NONE"
        if len(rsi_history) >= 5 and len(closes) >= 5:
            if closes[-1] < min(closes[-5:-1]) and rsi > min(rsi_history[-5:]):
                rsi_divergence = "BULLISH_DIVERGENCE"
            elif closes[-1] > max(closes[-5:-1]) and rsi < max(rsi_history[-5:]):
                rsi_divergence = "BEARISH_DIVERGENCE"

        # Pump Signal
        pump_signal = "NONE"
        if rsi_divergence == "BULLISH_DIVERGENCE" or (liq_sweep and fvg == "BULLISH_FVG"):
            pump_signal = "PUMP_IMMINENT"
        elif rsi_divergence == "BEARISH_DIVERGENCE" or (liq_sweep and fvg == "BEARISH_FVG"):
            pump_signal = "DUMP_IMMINENT"
        elif mss_bull and vol_spike:
            pump_signal = "BREAKOUT_UP"
        elif mss_bear and vol_spike:
            pump_signal = "BREAKOUT_DOWN"

        # SANITY CHECK: pump_signal harus konsisten dengan HTF trend
        # Kalau semua trend bullish tapi pump_signal = DUMP_IMMINENT = kontradiksi
        # Ini bisa terjadi karena candle cache stale atau RSI divergence noise
        # Dalam kasus ini, reset pump_signal ke NONE agar tidak mislead scoring
        trend_1h_pre = self._get_htf_trend("1h")
        trend_4h_pre = self._get_htf_trend("4h")
        if pump_signal == "DUMP_IMMINENT" and trend == "BULLISH" and trend_1h_pre == "BULLISH" and trend_4h_pre == "BULLISH":
            pump_signal = "NONE"  # Triple bullish + DUMP_IMMINENT = noise, abaikan
        if pump_signal == "PUMP_IMMINENT" and trend == "BEARISH" and trend_1h_pre == "BEARISH" and trend_4h_pre == "BEARISH":
            pump_signal = "NONE"  # Triple bearish + PUMP_IMMINENT = noise, abaikan

        # ?????? EXHAUSTION (FOMO) DETECTION ??????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        # Jangan buy hijau panjang di pucuk, jangan sell merah panjang di dasar
        last_body_pct = abs(closes[-1] - float(candles[-1].get("open", closes[-1]))) / (highs[-1] - lows[-1]) if (highs[-1] - lows[-1]) > 0 else 0
        # Exhaustion Pump: Candle hijau panjang, close dekat high, harga tertinggi dari 5 candle terakhir
        is_exhaustion_pump = (closes[-1] > float(candles[-1].get("open", closes[-1]))) and (last_body_pct > 0.6) and (highs[-1] >= max(highs[-5:]))
        # Exhaustion Dump: Candle merah panjang, close dekat low, harga terendah dari 5 candle terakhir
        is_exhaustion_dump = (closes[-1] < float(candles[-1].get("open", closes[-1]))) and (last_body_pct > 0.6) and (lows[-1] <= min(lows[-5:]))

        # HTF trends (1h dan 4h)  bias filter — pakai hasil yang sudah dihitung di atas
        trend_1h = trend_1h_pre
        trend_4h = trend_4h_pre

        # Order Book & Whale (via MetaAPI tick/volume)
        ob_data      = self._get_gold_orderbook()
        whale_trades = self._get_gold_whale_trades()
        obi          = ob_data.get("obi", 0.0)
        whale_ob     = ob_data.get("whale", "NORMAL")
        # Gabungkan sinyal whale dari order book dan recent trades
        if whale_ob == "WHALE_BUY" or whale_trades == "WHALE_BUY":
            whale_signal = "WHALE_BUY"
        elif whale_ob == "WHALE_SELL" or whale_trades == "WHALE_SELL":
            whale_signal = "WHALE_SELL"
        else:
            whale_signal = "NORMAL"

        # ?????? DEMAND/SUPPLY ZONE DETECTION ???????????????????????????????????????????????????????????????????????????????????????????????????????????????
        try:
            import pandas as _pd
            from data_fetcher import detect_demand_supply_zones as _dsz_func
            df_dsz = _pd.DataFrame({
                'open':  [float(c.get("open",  closes[i])) for i, c in enumerate(candles)],
                'high':  highs, 'low': lows, 'close': closes, 'vol': vols,
            })
            dsz = _dsz_func(df_dsz)
        except Exception:
            dsz = {"demand_zone": {"active": False, "top": 0, "bottom": 0, "strength": 0},
                   "supply_zone": {"active": False, "top": 0, "bottom": 0, "strength": 0},
                   "in_demand": False, "in_supply": False}

        # ?????? FIBONACCI, STOP HUNT, VOLUME PROFILE, HTF LEVELS ???????????????????????????????????????????????????
        # Semua dihitung dari candle MetaAPI yang sudah ada
        try:
            import pandas as _pd
            from data_fetcher import (
                get_fibonacci_levels as _fib_func,
                detect_stop_hunt as _hunt_func,
            )
            df_for_fib = _pd.DataFrame({
                'open': [float(c.get("open", closes[i])) for i, c in enumerate(candles)],
                'high': highs, 'low': lows, 'close': closes, 'vol': vols,
            })

            # Fibonacci dari candle 1h (lebih representatif untuk XAUUSD)
            candles_1h_fib = self.get_candles(timeframe="1h", limit=50)
            if len(candles_1h_fib) >= 20:
                highs_1h  = [float(c.get("high",  0)) for c in candles_1h_fib]
                lows_1h   = [float(c.get("low",   0)) for c in candles_1h_fib]
                closes_1h = [float(c.get("close", 0)) for c in candles_1h_fib]
                opens_1h  = [float(c.get("open",  closes_1h[i])) for i, c in enumerate(candles_1h_fib)]
                vols_1h   = [float(c.get("tickVolume", 1)) for c in candles_1h_fib]
                df_1h = _pd.DataFrame({'open': opens_1h, 'high': highs_1h,
                                       'low': lows_1h, 'close': closes_1h, 'vol': vols_1h})
                swing_high = max(highs_1h)
                swing_low  = min(lows_1h)
                diff = swing_high - swing_low
                current = closes[-1]
                if diff > 0:
                    fib_382 = round(swing_high - diff * 0.382, 3)
                    fib_500 = round(swing_high - diff * 0.500, 3)
                    fib_618 = round(swing_high - diff * 0.618, 3)
                    fib_786 = round(swing_high - diff * 0.786, 3)
                    tol = current * 0.003
                    levels = {"0.382": fib_382, "0.500": fib_500, "0.618": fib_618, "0.786": fib_786}
                    closest = min(levels.items(), key=lambda x: abs(current - x[1]))
                    at_level = abs(current - closest[1]) < tol
                    fib_data = {
                        "fib_382": fib_382, "fib_500": fib_500,
                        "fib_618": fib_618, "fib_786": fib_786,
                        "current_fib_level": closest[0] if at_level else "NONE",
                        "at_fib_support":    at_level and current < swing_high * 0.99,
                        "at_fib_resistance": at_level and current > swing_low  * 1.01,
                    }
                else:
                    fib_data = {}
            else:
                fib_data = {}

            # Stop Hunt dari candle 1m MetaAPI
            candles_1m = self.get_candles(timeframe="1m", limit=10)
            hunt_data = {"bull_stop_hunt": False, "bear_stop_hunt": False, "hunt_strength": 0}
            if len(candles_1m) >= 5:
                o1m = [float(c.get("open",  0)) for c in candles_1m]
                h1m = [float(c.get("high",  0)) for c in candles_1m]
                l1m = [float(c.get("low",   0)) for c in candles_1m]
                cl1m= [float(c.get("close", 0)) for c in candles_1m]
                v1m = [float(c.get("tickVolume", 1)) for c in candles_1m]
                avg_v = sum(v1m[:-1]) / len(v1m[:-1]) if len(v1m) > 1 else 1
                bull_h = bear_h = False
                strength = 0
                for i in range(-3, 0):
                    rng = h1m[i] - l1m[i]
                    if rng == 0: continue
                    wd = min(o1m[i], cl1m[i]) - l1m[i]
                    wu = h1m[i] - max(o1m[i], cl1m[i])
                    if wd > rng * 0.6 and cl1m[i] > (h1m[i]+l1m[i])/2 and v1m[i] > avg_v * 1.5:
                        bull_h = True; strength += 1
                    if wu > rng * 0.6 and cl1m[i] < (h1m[i]+l1m[i])/2 and v1m[i] > avg_v * 1.5:
                        bear_h = True; strength += 1
                hunt_data = {"bull_stop_hunt": bull_h, "bear_stop_hunt": bear_h,
                             "hunt_strength": min(strength, 3)}

            # Volume Profile dari candle 30m
            n_b = 30
            p_min, p_max = min(lows), max(highs)
            bsz = (p_max - p_min) / n_b if p_max > p_min else 1
            buckets = [0.0] * n_b
            for i in range(len(closes)):
                take_profit_val = (highs[i] + lows[i] + closes[i]) / 3
                bi = min(int((take_profit_val - p_min) / bsz), n_b - 1)
                buckets[bi] += vols[i]
            poc_idx = buckets.index(max(buckets))
            poc = round(p_min + (poc_idx + 0.5) * bsz, 3)
            poc_dist = ((closes[-1] - poc) / poc * 100) if poc > 0 else 0
            price_vs_poc = "AT" if abs(poc_dist) < 0.1 else ("ABOVE" if closes[-1] > poc else "BELOW")
            vp_data = {"poc": poc, "price_vs_poc": price_vs_poc, "poc_distance_pct": round(poc_dist, 3)}

            # HTF Key Levels dari candle 1D MetaAPI
            candles_1d = self.get_candles(timeframe="1D", limit=2)
            htf_data = {"daily_high": 0, "daily_low": 0, "near_daily_level": False,
                        "near_weekly_level": False, "htf_level_bias": "NEUTRAL"}
            if candles_1d:
                dh = float(candles_1d[0].get("high", 0))
                dl = float(candles_1d[0].get("low",  0))
                htf_data["daily_high"] = dh
                htf_data["daily_low"]  = dl
                cur = closes[-1]
                near_dh = dh > 0 and abs(cur - dh) / dh < 0.005
                near_dl = dl > 0 and abs(cur - dl) / dl < 0.005
                htf_data["near_daily_level"] = near_dh or near_dl
                if near_dh: htf_data["htf_level_bias"] = "RESISTANCE"
                elif near_dl: htf_data["htf_level_bias"] = "SUPPORT"

        except Exception as _e:
            fib_data  = {}
            hunt_data = {"bull_stop_hunt": False, "bear_stop_hunt": False, "hunt_strength": 0}
            vp_data   = {"poc": 0, "price_vs_poc": "UNKNOWN", "poc_distance_pct": 0}
            htf_data  = {"daily_high": 0, "daily_low": 0, "near_daily_level": False,
                         "near_weekly_level": False, "htf_level_bias": "NEUTRAL"}

        return {
            "rsi":              round(rsi, 2),
            "ema200":           round(ema200, 3),
            "atr":              round(atr, 3),
            "vwap":             round(vwap, 3),
            "vwap_dist":        round(vwap_dist, 4),
            "trend":            trend,
            "trend_1h":         trend_1h,
            "trend_4h":         trend_4h,
            "mss_bullish":      mss_bull,
            "mss_bearish":      mss_bear,
            "choch_bullish":    choch_bull,
            "choch_bearish":    choch_bear,
            "fvg":              fvg,
            "ob":               ob,
            "is_liquidity_sweep": liq_sweep,
            "last_close":       last_close,
            "vol_spike":        vol_spike,
            "rsi_divergence":   rsi_divergence,
            "pump_signal":      pump_signal,
            "obi":              round(obi, 4),
            "whale_signal":     whale_signal,
            "demand_zone":      dsz["demand_zone"],
            "supply_zone":      dsz["supply_zone"],
            "in_demand":        dsz["in_demand"],
            "in_supply":        dsz["in_supply"],
            # ATH/ATL Detection
            "price_position_pct": round(price_position_pct, 1),
            "near_ath":           near_ath,
            "near_atl":           near_atl,
            "range_high":         round(range_high, 3),
            "range_low":          round(range_low, 3),
            # Price Velocity
            "velocity":           round(velocity, 3),
            "velocity_direction": velocity_direction,
            # Fibonacci
            "fib_382":            fib_data.get("fib_382", 0),
            "fib_500":            fib_data.get("fib_500", 0),
            "fib_618":            fib_data.get("fib_618", 0),
            "at_fib_support":     fib_data.get("at_fib_support", False),
            "at_fib_resistance":  fib_data.get("at_fib_resistance", False),
            "current_fib_level":  fib_data.get("current_fib_level", "NONE"),
            # Stop Hunt
            "bull_stop_hunt":     hunt_data.get("bull_stop_hunt", False),
            "bear_stop_hunt":     hunt_data.get("bear_stop_hunt", False),
            "hunt_strength":      hunt_data.get("hunt_strength", 0),
            # Volume Profile
            "poc":                vp_data.get("poc", 0),
            "price_vs_poc":       vp_data.get("price_vs_poc", "UNKNOWN"),
            "poc_distance_pct":   vp_data.get("poc_distance_pct", 0),
            # HTF Key Levels
            "daily_high":         htf_data.get("daily_high", 0),
            "daily_low":          htf_data.get("daily_low", 0),
            "near_daily_level":   htf_data.get("near_daily_level", False),
            "near_weekly_level":  htf_data.get("near_weekly_level", False),
            "htf_level_bias":     htf_data.get("htf_level_bias", "NEUTRAL"),
            # Exhaustion
            "is_exhaustion_pump": is_exhaustion_pump,
            "is_exhaustion_dump": is_exhaustion_dump,
        }

    #  MOMENTUM SCORING 

    def _score_setup(self, ind, side, spread_points):
        """
        XAUUSD Genius Score v6.0  0 to 100.
        Tambahan v6.0: 4h trend bias, DXY macro, Order Block.
        Prioritas: pump_signal > divergence > MSS > FVG/OB > RSI > VWAP > HTF
        """
        score     = 0
        rsi       = ind.get("rsi", 50)
        vwap_dist = ind.get("vwap_dist", 0)
        fvg       = ind.get("fvg", "NONE")
        ob        = ind.get("ob", "NONE")
        mss_b     = ind.get("mss_bullish", False)
        mss_s     = ind.get("mss_bearish", False)
        choch_b   = ind.get("choch_bullish", False)
        choch_s   = ind.get("choch_bearish", False)
        liq       = ind.get("is_liquidity_sweep", False)
        trend     = ind.get("trend", "NEUTRAL")
        trend_1h  = ind.get("trend_1h", "NEUTRAL")
        trend_4h  = ind.get("trend_4h", "NEUTRAL")
        vol_spike = ind.get("vol_spike", False)
        rsi_div   = ind.get("rsi_divergence", "NONE")
        pump_sig  = ind.get("pump_signal", "NONE")

        #  1. PUMP SIGNAL (max 45 poin) 
        if side == "buy":
            if pump_sig == "PUMP_IMMINENT":  score += 45
            elif pump_sig == "BREAKOUT_UP":  score += 30
            if rsi_div == "BULLISH_DIVERGENCE": score += 20
        else:
            if pump_sig == "DUMP_IMMINENT":   score += 45
            elif pump_sig == "BREAKOUT_DOWN": score += 30
            if rsi_div == "BEARISH_DIVERGENCE": score += 20

        #  2. Volume Spike (max 15 poin) 
        if vol_spike: score += 15

        #  3. RSI Zone (max 15 poin) 
        # RSI threshold diturunkan: max 65 untuk BUY (bukan 72)
        # Data: RSI 76+ masih masuk BUY = salah
        if side == "buy":
            if 28 <= rsi <= 48:   score += 15   # Oversold recovery
            elif 48 < rsi <= 58:  score += 8
            elif rsi > 65:        score -= 15   # Overbought ??? penalti lebih besar
        else:
            if 52 <= rsi <= 72:   score += 15   # Overbought rejection
            elif 42 <= rsi < 52:  score += 8
            elif rsi < 35:        score -= 15   # Oversold ??? penalti lebih besar

        #  4. FVG (max 10 poin) 
        if side == "buy"  and fvg == "BULLISH_FVG": score += 10
        if side == "sell" and fvg == "BEARISH_FVG": score += 10

        #  5. Order Block (max 8 poin) 
        if side == "buy"  and ob == "BULLISH_OB": score += 8
        if side == "sell" and ob == "BEARISH_OB": score += 8

        #  6. MSS / CHoCH (max 20 poin) 
        if side == "buy"  and (mss_b or choch_b): score += 20
        if side == "sell" and (mss_s or choch_s): score += 20

        #  7. Liquidity Sweep (max 5 poin) 
        if liq: score += 5

        #  7b. DEMAND/SUPPLY ZONE (max 20 poin) 
        # Zona ini lebih kuat dari Order Block karena terbentuk dari konsolidasi institusi
        in_demand   = ind.get("in_demand", False)
        in_supply   = ind.get("in_supply", False)
        dz_strength = ind.get("demand_zone", {}).get("strength", 0)
        sz_strength = ind.get("supply_zone", {}).get("strength", 0)
        if side == "buy" and in_demand:
            score += 15 + min(5, dz_strength)  # max 20 poin
        if side == "sell" and in_supply:
            score += 15 + min(5, sz_strength)

        #  7c. FIBONACCI RETRACEMENT (max 15 poin)
        if side == "buy"  and ind.get("at_fib_support", False):
            fib_lvl = ind.get("current_fib_level", "NONE")
            score += 15 if fib_lvl in ("0.618", "0.786") else 10
        if side == "sell" and ind.get("at_fib_resistance", False):
            fib_lvl = ind.get("current_fib_level", "NONE")
            score += 15 if fib_lvl in ("0.618", "0.786") else 10

        #  7d. STOP HUNT SIGNAL (max 15 poin)
        hunt_strength = ind.get("hunt_strength", 0)
        if side == "buy"  and ind.get("bull_stop_hunt", False):
            score += 10 + min(5, hunt_strength * 2)
        if side == "sell" and ind.get("bear_stop_hunt", False):
            score += 10 + min(5, hunt_strength * 2)

        #  7f. 5M PRECISION QUALITY (max 15 poin)
        e5m = self._get_5m_entry_quality()
        if side == "buy" and e5m["signal"] == "BULLISH_CONFIRM":
            score += min(15, e5m["quality"] * 0.2)
        if side == "sell" and e5m["signal"] == "BEARISH_CONFIRM":
            score += min(15, e5m["quality"] * 0.2)

        #  7e. VOLUME PROFILE / POC (max 10 poin, penalti -8)
        price_vs_poc = ind.get("price_vs_poc", "UNKNOWN")
        poc_dist     = abs(ind.get("poc_distance_pct", 0))
        if side == "buy"  and price_vs_poc == "BELOW": score += min(10, poc_dist * 3)
        if side == "sell" and price_vs_poc == "ABOVE": score += min(10, poc_dist * 3)
        if side == "buy"  and price_vs_poc == "ABOVE" and poc_dist > 2: score -= 8
        if side == "sell" and price_vs_poc == "BELOW" and poc_dist > 2: score -= 8

        #  7f. HTF KEY LEVELS (penalti -15 kalau melawan level kritis)
        htf_bias    = ind.get("htf_level_bias", "NEUTRAL")
        near_weekly = ind.get("near_weekly_level", False)
        if side == "buy"  and htf_bias == "RESISTANCE":
            score -= 15 if near_weekly else 8
        if side == "sell" and htf_bias == "SUPPORT":
            score -= 15 if near_weekly else 8

        #  8. Whale Signal via PAXG Order Book (max 15 poin) 
        #  8. Whale Signal via PAXG Order Book (max 25 poin) 
        # Ini sinyal paling kuat ??? whale di gold market = institutional money
        whale = ind.get("whale_signal", "NORMAL")
        obi   = ind.get("obi", 0.0)
        if side == "buy":
            if whale == "WHALE_BUY":   score += 25
            elif whale == "WHALE_SELL": score -= 20
            if rsi_div == "BULLISH_DIVERGENCE": score += 20
            if obi > 0.20:             score += 25
            elif obi > 0.10:           score += 15
        else:
            if whale == "WHALE_SELL":  score += 25
            elif whale == "WHALE_BUY": score -= 20
            if rsi_div == "BEARISH_DIVERGENCE": score += 20
            if obi < -0.20:            score += 25
            elif obi < -0.10:          score += 15

        #  8. Trend 30m (max 3 poin)
        if side == "buy"  and trend == "BULLISH": score += 3
        if side == "sell" and trend == "BEARISH": score += 3
        
        #  9. Trend 1h (max 3 poin)
        if side == "buy"  and trend_1h == "BULLISH": score += 3
        if side == "sell" and trend_1h == "BEARISH": score += 3
        
        #  10. Trend 4h (max 3 poin)
        if side == "buy"  and trend_4h == "BULLISH": score += 3
        if side == "sell" and trend_4h == "BEARISH": score += 3

        #  Penalti Trend (reversed logic handled by reversal_signal check)
        reversal_signal = pump_sig in ("PUMP_IMMINENT", "DUMP_IMMINENT", "BREAKOUT_UP", "BREAKOUT_DOWN")
        
        #  10b. Trend Penalty logic
        trend_penalty_1h = 0 if reversal_signal else 12
        if side == "buy"  and trend_1h == "BEARISH": score -= trend_penalty_1h
        if side == "sell" and trend_1h == "BULLISH": score -= trend_penalty_1h

        # Karena reversal sering terjadi melawan trend 4h
        trend_penalty_4h = 0 if reversal_signal else 15
        if side == "buy"  and trend_4h == "BULLISH": score += 8
        if side == "sell" and trend_4h == "BEARISH": score += 8
        if side == "buy"  and trend_4h == "BEARISH": score -= trend_penalty_4h
        if side == "sell" and trend_4h == "BULLISH": score -= trend_penalty_4h

        #  11. DXY Macro Context (max 10 poin, penalti -10) 
        dxy = self._get_dxy_context()
        dxy_trend = dxy.get("trend", "NEUTRAL")
        if side == "buy"  and dxy_trend == "BEARISH":  score += 10  # DXY lemah = bullish gold
        if side == "sell" and dxy_trend == "BULLISH":  score += 10  # DXY kuat = bearish gold
        if side == "buy"  and dxy_trend == "BULLISH":  score -= 10  # DXY kuat = headwind untuk long gold
        if side == "sell" and dxy_trend == "BEARISH":  score -= 10  # DXY lemah = headwind untuk short gold

        #  12. Spread penalty 
        if spread_points > 100: score -= 10
        if spread_points > 150: score -= 20

        #  13. Session bonus 
        now_utc = datetime.datetime.utcnow()
        hour = now_utc.hour
        # London open (07-09) dan NY open (13-15) = paling volatile
        if (7 <= hour <= 9) or (13 <= hour <= 15):
            score += 10
        # Asia open (02-04)  gold juga volatile saat Tokyo open
        elif 2 <= hour <= 4:
            score += 5

        #  14. ATH/ATL DETECTION (penalti besar) 
        # Jangan BUY di puncak range ??? harga butuh effort untuk tembus ATH
        # Jangan SELL di dasar range ??? harga butuh effort untuk tembus ATL
        near_ath = ind.get("near_ath", False)
        near_atl = ind.get("near_atl", False)
        price_pos = ind.get("price_position_pct", 50)
        if side == "buy" and near_ath:
            score -= 20  # Harga di 80%+ range = risky BUY
            # Kalau di 90%+ = sangat risky
            if price_pos >= 90:
                score -= 10
        if side == "sell" and near_atl:
            score -= 20  # Harga di 20%- range = risky SELL
            if price_pos <= 10:
                score -= 10

        # Bonus kalau harga di zona ideal untuk entry
        if side == "buy"  and 20 <= price_pos <= 45:  score += 8  # Dekat bottom range
        if side == "sell" and 55 <= price_pos <= 80:  score += 8  # Dekat top range

        #  15. PRICE VELOCITY BONUS 
        # Momentum kuat = sinyal lebih reliable
        velocity = ind.get("velocity", 0)
        vel_dir  = ind.get("velocity_direction", "FLAT")
        if side == "buy"  and vel_dir == "UP"   and velocity > 0.3: score += 8
        if side == "sell" and vel_dir == "DOWN" and velocity > 0.3: score += 8
        # Velocity berlawanan = momentum melawan = penalti
        if side == "buy"  and vel_dir == "DOWN" and velocity > 0.5: score -= 8
        if side == "sell" and vel_dir == "UP"   and velocity > 0.5: score -= 8

        return max(0, min(100, score))

    def _determine_side(self, ind, spread_points):
        """
        Return (side, score, trades_to_open) atau (None, 0, 0).
        v8.0: Hard block in_demand/in_supply, 1 trade fokus.
        """
        buy_score  = self._score_setup(ind, "buy",  spread_points)
        sell_score = self._score_setup(ind, "sell", spread_points)

        trend    = ind.get("trend", "NEUTRAL")
        pump_sig = ind.get("pump_signal", "NONE")
        rsi      = ind.get("rsi", 50)
        choch_b  = ind.get("choch_bullish", False)
        choch_s  = ind.get("choch_bearish", False)

        best_side  = None
        best_score = 0

        falling_knife      = ind.get("falling_knife", False)
        flying_rocket      = ind.get("flying_rocket", False)
        is_exhaustion_pump = ind.get("is_exhaustion_pump", False)
        is_exhaustion_dump = ind.get("is_exhaustion_dump", False)

        # HARD BLOCK: jangan SELL di demand zone, jangan BUY di supply zone
        # Ini fix kasus SAHARA — harga di demand tapi bot SHORT
        in_demand = ind.get("in_demand", False)
        in_supply = ind.get("in_supply", False)

        if buy_score >= sell_score and buy_score >= MIN_MOMENTUM_SCORE:
            if in_supply:
                print(f"[GUARD] XAUUSD BUY diblokir: Harga di Supply Zone. Tunggu breakout!")
            elif falling_knife or is_exhaustion_dump:
                print(f"[GUARD] XAUUSD BUY diblokir: Pisau Jatuh. Tunggu pantulan!")
            elif is_exhaustion_pump:
                print(f"[GUARD] XAUUSD BUY diblokir: FOMO di pucuk.")
            else:
                best_side, best_score = "buy", buy_score
        elif sell_score > buy_score and sell_score >= MIN_MOMENTUM_SCORE:
            if in_demand:
                print(f"[GUARD] XAUUSD SELL diblokir: Harga di Demand Zone. Tunggu breakdown!")
            elif flying_rocket or is_exhaustion_pump:
                print(f"[GUARD] XAUUSD SELL diblokir: Roket Terbang. Tunggu rejection!")
            elif is_exhaustion_dump:
                print(f"[GUARD] XAUUSD SELL diblokir: FOMO di dasar.")
            else:
                best_side, best_score = "sell", sell_score

        if best_side is None:
            return None, 0, 0

        # Skip pure neutral
        if rsi == 50.0 and trend == "NEUTRAL" and pump_sig == "NONE" and not choch_b and not choch_s:
            return None, 0, 0

        # 1 trade fokus — lebih baik 1 trade bagus dari 2 trade biasa
        # Spread cost 2x, margin 2x, tapi tidak ada diversifikasi
        return best_side, best_score, 1

    #  take_profit_val/stop_loss_val & LOT SIZING 

    def _calc_tp_sl(self, price, side, atr, spread_pts=0):
        """
        take_profit_val/stop_loss_val GENIUS SCALPER v8.0 — RR 2:1 dengan spread adjustment.

        RR 2:1 = take_profit_val 40 poin, stop_loss_val 20 poin.
        Kenapa RR 2:1 lebih baik dari 1.5:1?
        - RR 1.5:1 butuh win rate 40% untuk break even
        - RR 2:1 butuh win rate 33% untuk break even
        - Dengan spread ~3 poin, RR efektif 2:1 = take_profit_val 37 poin, stop_loss_val 23 poin
        - Masih lebih baik dari RR 1.5:1 sebelumnya

        Spread adjustment: take_profit_val diperlebar sedikit untuk cover spread cost.
        """
        # Spread adjustment — take_profit_val harus cover spread cost
        spread_adj = max(0, spread_pts * 0.1)  # 10% dari spread ditambah ke take_profit_val

        if atr and 1.0 <= atr <= 25:
            # ATR-based dengan floor minimum
            sl_dist = max(atr * 1.5, SCALP_SL_POINTS)
            tp_dist = max(atr * 3.0, SCALP_TP_POINTS + spread_adj)
        else:
            sl_dist = SCALP_SL_POINTS
            tp_dist = SCALP_TP_POINTS + spread_adj

        # Hard limits — RR harus tetap >= 1.8:1
        sl_dist = max(sl_dist, 18.0)
        sl_dist = min(sl_dist, 25.0)
        tp_dist = max(tp_dist, sl_dist * 1.8)  # Minimum RR 1.8:1
        tp_dist = min(tp_dist, 50.0)

        if side == "buy":
            return round(price + tp_dist, 3), round(price - sl_dist, 3)
        else:
            return round(price - tp_dist, 3), round(price + sl_dist, 3)

    def _calc_lot_size(self, balance):
        """Lot sizing FIXED: selalu 0.01 lot per trade."""
        return MIN_LOT_PER_TRADE

    def _is_trading_session(self):
        """
        Hanya London (07-16 UTC) dan NY (12-21 UTC).
        HAPUS Asia session ??? terlalu banyak false signal, volume rendah.
        Data menunjukkan Asia session win rate buruk kecuali sample sangat kecil.
        """
        now_utc = datetime.datetime.utcnow()
        weekday = now_utc.weekday()
        if weekday == 6: return False
        if weekday == 5 and now_utc.hour >= 21: return False
        hour = now_utc.hour
        # London: 07-16 UTC (14:00-23:00 WIB)
        # NY: 12-21 UTC (19:00-04:00 WIB)
        return (7 <= hour < 16) or (12 <= hour < 21)

    #  POSITIONS 

    def _get_positions(self):
        if not self.is_active: return []
        try:
            url = self.base_url + "/users/current/accounts/" + self.account_id + "/positions"
            res = requests.get(url, headers={"auth-token": self.api_token}, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    self._positions_cache    = data
                    self._positions_cache_ts = time.time()
                    return data
        except Exception:
            pass

        # Fallback ke cache (max 60 detik)
        if self._positions_cache and time.time() - self._positions_cache_ts < 60:
            print("[FOREX POSITIONS] MetaAPI timeout, pakai cache (" + str(len(self._positions_cache)) + " posisi)")
            return self._positions_cache
        return []

    #  ORDER EXECUTION 

    def place_forex_order(self, symbol, side, amount, take_profit_val=None, stop_loss_val=None, reason_data=None):
        if not self.is_active: return False, "Forex not active"
        
        # ── POSITION GUARD (v26.64) ──
        # Mencegah duplikasi posisi XAUUSD saat API lag
        try:
            from shared_state import state
            existing = self.get_open_positions() # Fetch fresh from MetaAPI
            if existing:
                for pos in existing:
                    if pos.get('symbol') == symbol:
                        print(f"[FOREX GUARD] Posisi {symbol} sudah ada. Skip order baru.")
                        return False, "POSITION_EXISTS"
        except Exception as e:
            print(f"[FOREX GUARD ERROR] {e}")

        try:
            url = self.base_url + "/users/current/accounts/" + self.account_id + "/trade"
            headers = {"auth-token": self.api_token, "Content-Type": "application/json"}

            # Validasi stop_loss_val sebelum kirim ??? stop_loss_val BUY harus < harga saat ini
            # Ini mencegah stop_loss_val yang salah arah (misal breakeven dari posisi lain)
            if stop_loss_val and stop_loss_val > 0:
                live = self.get_live_price(symbol)
                mid  = live.get("mid", 0)
                if mid > 0:
                    if side.lower() == "buy" and stop_loss_val >= mid:
                        # stop_loss_val di atas harga ??? salah arah, recalculate
                        stop_loss_val = round(mid - SCALP_SL_POINTS, 3)
                        print("[stop_loss_val GUARD] BUY stop_loss_val salah arah, reset ke " + str(stop_loss_val))
                    elif side.lower() == "sell" and stop_loss_val <= mid:
                        stop_loss_val = round(mid + SCALP_SL_POINTS, 3)
                        print("[stop_loss_val GUARD] SELL stop_loss_val salah arah, reset ke " + str(stop_loss_val))

            payload = {
                "symbol":     symbol,
                "actionType": "ORDER_TYPE_BUY" if side.lower() == "buy" else "ORDER_TYPE_SELL",
                "volume":     amount,
                "comment":    "GeniusForex v8.0",
            }
            if stop_loss_val: payload["stopLoss"]   = stop_loss_val
            if take_profit_val: payload["takeProfit"] = take_profit_val
            res    = requests.post(url, headers=headers, json=payload, timeout=10)
            result = res.json()
            if res.status_code == 200:
                self._pending_order_ts = time.time() # FIX: Lock entry
                self._positions_cache  = []         # FIX: Invalidate cache
                print("[FOREX SUCCESS] " + side.upper() + " " + symbol + " lot=" + str(amount) + " take_profit_val=" + str(take_profit_val) + " stop_loss_val=" + str(stop_loss_val))
                
                # KIRIM NOTIF TELEGRAM
                if reason_data:
                    from notifier import send_telegram_message, format_trade_message
                    tg_data = {
                        'symbol': symbol, 'side': side, 'price': mid, 'amount': amount,
                        'score': reason_data.get('score', 0), 'reason': reason_data.get('reason', 'N/A'),
                        'take_profit_val': take_profit_val, 'stop_loss_val': stop_loss_val,
                        'tp_pct': round(abs(take_profit_val-mid)/mid*100, 2) if mid else 0,
                        'sl_pct': round(abs(stop_loss_val-mid)/mid*100, 2) if mid else 0,
                        'rsi': reason_data.get('rsi', 0), 'vwap': reason_data.get('vwap', 0),
                        'obi_rest': reason_data.get('obi', 0),
                        'trend_1h': reason_data.get('trend_1h', '?'),
                        'rt_wbv': 0, 'rt_wsv': 0, 'rt_obi': reason_data.get('obi', 0), 'rt_spread': reason_data.get('spread', 0),
                        'e5m': reason_data.get('e5m_sig', '?'),
                        'q5m': reason_data.get('e5m_q', 0),
                        'f5m': 'XAUUSD_PRECISION'
                    }
                    send_telegram_message(format_trade_message(tg_data))
                
                return True, result
            else:
                msg = result.get("message", str(result))
                print("[FOREX FAILED] " + symbol + ": " + msg)
                return False, msg
        except Exception as e:
            print("[FOREX API CRASH] " + str(e))
            return False, str(e)

    def place_xauusd_scalp_batch(self, side, trades_count=3, volume=0.01, take_profit_val=None, stop_loss_val=None):
        """Dipakai oleh news_sniper.py untuk eksekusi cepat."""
        sym = self._working_symbol or self._resolve_symbol("XAUUSD")
        price_data = self.get_live_price(sym)
        price = price_data["bid"] if side == "sell" else price_data["ask"]
        if price == 0:
            print("[SCALP BATCH] Cannot get price, aborting.")
            return False
        if take_profit_val is None or stop_loss_val is None or take_profit_val == 0 or stop_loss_val == 0:
            take_profit_val, stop_loss_val = self._calc_tp_sl(price, side, 1.5)
        print("[SCALP BATCH] Firing " + str(trades_count) + "x " + side.upper() + " " + sym + " @ " + str(price) + " take_profit_val=" + str(take_profit_val) + " stop_loss_val=" + str(stop_loss_val))
        any_success = False
        for i in range(trades_count):
            success, _ = self.place_forex_order(sym, side, volume, take_profit_val=take_profit_val, stop_loss_val=stop_loss_val)
            if success:
                from database import log_trade
                log_trade(sym, price, take_profit_val, stop_loss_val, market="forex", side=side, lot_size=volume)
                any_success = True
            time.sleep(0.1)
        return any_success

    def update_forex_sl(self, position_id, new_sl, current_tp=None):
        """
        Update stop_loss_val posisi via POSITION_MODIFY.
        WAJIB kirim takeProfit bersamaan ??? kalau tidak, beberapa broker MT5
        akan reset take_profit_val ke 0 (hilang) saat stop_loss_val diupdate.
        current_tp harus diambil dari data posisi sebelum memanggil fungsi ini.
        """
        if not self.is_active: return False
        try:
            url = self.base_url + "/users/current/accounts/" + self.account_id + "/trade"
            headers = {"auth-token": self.api_token, "Content-Type": "application/json"}
            payload = {
                "actionType": "POSITION_MODIFY",
                "positionId": str(position_id),
                "stopLoss":   new_sl,
            }
            # Selalu sertakan take_profit_val kalau ada ??? mencegah broker reset take_profit_val ke 0
            if current_tp and float(current_tp) > 0:
                payload["takeProfit"] = float(current_tp)
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code == 200:
                return True
            try:
                err = res.json().get("message", res.text[:100])
            except Exception:
                err = res.text[:100]
            print("[UPDATE stop_loss_val FAIL] pos=" + str(position_id) + " stop_loss_val=" + str(new_sl) + " status=" + str(res.status_code) + ": " + err)
            return False
        except Exception as e:
            print("[UPDATE stop_loss_val ERROR] pos=" + str(position_id) + ": " + str(e))
            return False

    #  TRAILING STOP 

    def _trail_positions(self, positions):
        """
        Trailing stop_loss_val v8.0 — Genius Scalper Edition.

        Perubahan dari v7.0:
        - Trailing aktif dari 15 poin (bukan 12) — kurangi noise exit
        - Gap trailing minimal 10 poin dari current price (bukan dari entry)
        - Selalu kirim take_profit_val bersamaan agar take_profit_val tidak hilang
        - Auto-close threshold konsisten dengan stop_loss_val (bukan $7 flat)
        - _close_attempted dibersihkan setiap 10 menit

        Tabel trailing baru:
        profit < 15 poin  : DIAM — noise XAUUSD bisa 8-12 poin
        profit 15-19 poin : LOCK-5 (stop_loss_val ke entry+5)
        profit 20-24 poin : LOCK-10 (stop_loss_val ke entry+10)
        profit 25-29 poin : LOCK-15 (stop_loss_val ke entry+15)
        profit >= 30 poin : LOCK-20 (stop_loss_val ke entry+20) — hampir di take_profit_val
        """
        now = time.time()

        # Bersihkan _close_attempted setiap 10 menit
        if now - self._last_close_clean > 600:
            self._close_attempted = {k: v for k, v in self._close_attempted.items()
                                     if now - v < 600}
            self._last_close_clean = now

        for p in positions:
            if "XAU" not in p.get("symbol", "").upper(): continue
            open_price  = float(p.get("openPrice", 0))
            pos_id      = p.get("id")
            pos_type    = p.get("type", "")
            profit      = round(float(p.get("profit", 0)), 2)
            current_sl  = float(p.get("stopLoss", 0))
            current_tp  = float(p.get("takeProfit", 0))
            current_price_raw = p.get("currentPrice", open_price)
            cp          = round(float(current_price_raw), 3)
            sym         = p.get("symbol", self._working_symbol or "XAUUSDc")
            if open_price == 0: continue

            is_buy    = pos_type == "POSITION_TYPE_BUY"
            profit_pt = (cp - open_price) if is_buy else (open_price - cp)

            direction = "BUY" if is_buy else "SELL"
            if int(now) % 10 < 3:
                print(f"[TRAIL] {sym} {direction} open={open_price} cur={cp} "
                      f"profit=${profit} pt={round(profit_pt,2)} stop_loss_val={current_sl}", flush=True)

            # AUTO-CLOSE: rugi melebihi stop_loss_val + buffer (stop_loss_val harusnya sudah kena, ini safety net)
            # v8.1: Threshold dinamis — 1.5x dari stop_loss_val dalam poin dikali lot
            # stop_loss_val 20 poin = $0.2 per 0.01 lot. Auto-close di 30 poin ($0.3)
            # Ini mencegah bot "mencuri" trade yang harusnya masih bernapas.
            sl_points_val = abs(open_price - current_sl) if current_sl > 0 else SCALP_SL_POINTS
            auto_close_threshold = -(sl_points_val * 1.5) * 0.1 * (float(p.get("volume", 0)) / 0.01)
            
            if profit < auto_close_threshold and pos_id not in self._close_attempted:
                self._close_attempted[pos_id] = now
                print(f"[FOREX AUTO-CLOSE] {pos_id} loss ${profit} exceeded threshold. Closing.")
                try:
                    url = self.base_url + "/users/current/accounts/" + self.account_id + "/trade"
                    headers = {"auth-token": self.api_token, "Content-Type": "application/json"}
                    res = requests.post(url, headers=headers,
                        json={"actionType": "POSITION_CLOSE_ID", "positionId": pos_id}, timeout=8)
                    if res.status_code == 200:
                        print(f"[FOREX AUTO-CLOSE] {pos_id} closed OK")
                        send_telegram_message(f"<b>🛑 FOREX POSITION CLOSED</b>\n\nSymbol: <code>{sym}</code>\nID: <code>{pos_id}</code>\nProfit: <b>${profit}</b>\nReason: <b>Auto-Close (stop_loss_val Hit/Buffer)</b>")
                    else:
                        del self._close_attempted[pos_id]  # Retry next time
                except Exception as e:
                    if pos_id in self._close_attempted:
                        del self._close_attempted[pos_id]
                continue

            # TRAILING stop_loss_val — aktif dari 15 poin
            stage = "NONE"
            if is_buy:
                if profit_pt >= 30.0:
                    target_sl = round(open_price + 20.0, 3)
                    stage     = "LOCK-20"
                elif profit_pt >= 20.0:
                    target_sl = round(open_price + 10.0, 3)
                    stage     = "LOCK-10"
                elif profit_pt >= 15.0:
                    target_sl = round(open_price + 7.0, 3)
                    stage     = "LOCK-7"
                elif profit_pt >= 10.0:
                    target_sl = round(open_price + 3.0, 3)
                    stage     = "LOCK-3"
                else:
                    target_sl = 0
            else:
                if profit_pt >= 30.0:
                    target_sl = round(open_price - 20.0, 3)
                    stage     = "LOCK-20"
                elif profit_pt >= 20.0:
                    target_sl = round(open_price - 10.0, 3)
                    stage     = "LOCK-10"
                elif profit_pt >= 15.0:
                    target_sl = round(open_price - 7.0, 3)
                    stage     = "LOCK-7"
                elif profit_pt >= 10.0:
                    target_sl = round(open_price - 3.0, 3)
                    stage     = "LOCK-3"
                else:
                    target_sl = 0

            # stop_loss_val hanya bergerak ke arah profit, tidak pernah mundur
            if is_buy:
                should_update = (current_sl == 0 or target_sl > current_sl + 0.5)
            else:
                should_update = (current_sl == 0 or target_sl < current_sl - 0.5)

            if should_update:
                ok = self.update_forex_sl(pos_id, target_sl, current_tp=current_tp)
                if ok:
                    print(f"OK [{stage}] {sym} stop_loss_val {current_sl} -> {target_sl} "
                          f"| take_profit_val={current_tp} | profit_pt={round(profit_pt,1)}pt")
                else:
                    print(f"FAIL [{stage}] {sym} -> {target_sl}")

    #  MAIN ENGINE LOOP

    def monitor_forex_market(self):
        """
        FOREX ENGINE v8.0 - Genius Scalper Edition.
        Upgrade: consecutive loss pause, MTF confluence, micro momentum,
        session overlap handling, spread-adjusted take_profit_val/stop_loss_val, DXY dari Yahoo Finance.
        """
        try:
            info = self.get_account_information()
            if info:
                print(f"[FOREX] MT5 Ready | Bal: ${info.get('balance',0)} | Eq: ${info.get('equity',0)} | Sym: {self._working_symbol}", flush=True)
        except Exception as e:
            print(f"[FOREX STARTUP ERROR] {e}", flush=True)

        print(f"[FOREX ENGINE v8.0] XAUUSD Genius Scalper AKTIF! take_profit_val:{SCALP_TP_POINTS} stop_loss_val:{SCALP_SL_POINTS} RR:2:1", flush=True)
        last_auto_trade = 0
        last_scan_log   = 0

        while True:
            try:
                if not self.is_active:
                    time.sleep(60)
                    continue

                price_data   = self.get_live_price()
                broker_price = price_data["mid"]
                spread_pts   = price_data["spread_points"]
                if broker_price > 0:
                    self._last_known_price  = broker_price
                    self._last_known_spread = spread_pts
                else:
                    broker_price = self._last_known_price
                    spread_pts   = self._last_known_spread

                positions    = self._get_positions()
                active_count = len(positions)
                total_lots   = sum(float(p.get("volume", 0)) for p in positions)
                now_t = time.time()
                if broker_price > 0 and now_t - last_scan_log >= 15:
                    pending_str = " (Pending...)" if now_t - self._pending_order_ts < 10 else ""
                    print(f"[FOREX] Price: {broker_price} | Trades: {active_count} | Lots: {round(total_lots,2)} | Spread: {spread_pts}pts{pending_str}", flush=True)

                # ── GHOST TRADE GUARD (MetaAPI Sync Lag) ──
                # FIX v8.1: Guard aktif meskipun ada posisi (cegah multi-trade lag)
                # Lock ditingkatkan ke 15 detik agar sinkronisasi broker lebih aman
                if now_t - self._pending_order_ts < 15:
                    if now_t - last_scan_log >= 15:
                        print(f"[FOREX GUARD] Sinkronisasi MT5 ({round(15 - (now_t-self._pending_order_ts))}s remaining...)")
                    time.sleep(SCAN_INTERVAL)
                    continue

                if broker_price > 0 and positions:
                    for p in positions:
                        if "XAU" in p.get("symbol", "").upper():
                            p["currentPrice"] = broker_price
                    self._trail_positions(positions)

                if not self._is_trading_session():
                    print("[FOREX SESSION] Outside trading session. Waiting 5 min...")
                    time.sleep(300)
                    continue

                now = time.time()

                # CONSECUTIVE LOSS PAUSE
                if now < self._consec_pause_until:
                    remaining = round((self._consec_pause_until - now) / 60, 1)
                    if int(now) % 60 < 3:
                        print(f"[FOREX CONSEC LOSS] Pause aktif. {remaining} menit lagi.")
                    time.sleep(SCAN_INTERVAL)
                    continue

                info = self.get_account_information()
                if not info:
                    time.sleep(10)
                    continue
                balance = float(info.get("balance", 0))
                equity  = float(info.get("equity", 0))
                if balance > 0 and equity < balance * EQUITY_GUARD_PCT:
                    print(f"[EQUITY GUARD] Drawdown! Equity: ${equity} / Balance: ${balance}. Halting.")
                    time.sleep(60)
                    continue

                take_profit_val, stop_loss_val = 0.0, 0.0 # SCOPE LOCK
                now_h = datetime.datetime.utcnow().hour
                current_session = ("ASIA" if 2 <= now_h < 5 else "LONDON" if 7 <= now_h < 16 else "NY" if 12 <= now_h < 21 else "OFF")
                if not hasattr(self, "_last_session"): self._last_session = current_session
                if current_session != self._last_session:
                    print(f"[SESSION] Sesi baru: {current_session}. Reset loss counter.")
                    self._session_loss_usd = 0.0
                    self._last_session = current_session
                    self._consec_losses = 0

                if balance > 0:
                    session_pnl = equity - balance
                    if session_pnl < -SESSION_MAX_LOSS_USD:
                        print(f"[SESSION LOSS] Rugi ${round(abs(session_pnl),2)} sesi {current_session}. Stop.")
                        time.sleep(300)
                        continue

                # Deteksi loss dari posisi yang baru ditutup
                if not hasattr(self, "_prev_pos_count"): self._prev_pos_count = active_count
                if not hasattr(self, "_prev_equity"): self._prev_equity = equity
                if active_count < self._prev_pos_count:
                    if equity < self._prev_equity - 0.5:
                        self._consec_losses += 1
                        print(f"[FOREX CONSEC LOSS] Loss ke-{self._consec_losses}. Equity turun ${round(self._prev_equity-equity,2)}")
                        if self._consec_losses >= CONSEC_LOSS_LIMIT:
                            pause_min = (CONSEC_LOSS_PAUSE // 60) * (2 ** (self._consec_losses - CONSEC_LOSS_LIMIT))
                            pause_min = min(pause_min, 120)
                            self._consec_pause_until = now + pause_min * 60
                            print(f"[FOREX CONSEC LOSS] {self._consec_losses}x loss! Pause {pause_min} menit.")
                            self._consec_losses = CONSEC_LOSS_LIMIT
                    else:
                        print(f"[FOREX WIN] Trade closed with profit! Reset consec loss.")
                        self._consec_losses = 0
                self._prev_pos_count = active_count
                self._prev_equity = equity

                if broker_price == 0:
                    time.sleep(5)
                    continue

                if spread_pts > MAX_SPREAD_POINTS:
                    print(f"[SPREAD GUARD] Spread {spread_pts}pts too wide (max {MAX_SPREAD_POINTS}). Skipping.")
                    time.sleep(SCAN_INTERVAL)
                    continue

                cooldown_remaining = COOLDOWN_AFTER_TRADE - (now - last_auto_trade)
                if cooldown_remaining > 0:
                    if int(now) % 30 < 3:
                        print(f"[FOREX COOLDOWN] {round(cooldown_remaining)}s remaining")
                    time.sleep(SCAN_INTERVAL)
                    continue

                do_log = (now - last_scan_log >= 30)
                if do_log:
                    print(f"[FOREX SCAN] {self._working_symbol} | RSI calculating (1m)...", flush=True)
                ind = self._calc_indicators(timeframe="1m")
                if not ind:
                    time.sleep(5)
                    continue

                rsi_val  = ind.get("rsi", 0)
                trend    = ind.get("trend", "NEUTRAL")
                trend_1h = ind.get("trend_1h", "NEUTRAL")
                trend_4h = ind.get("trend_4h", "NEUTRAL")
                pump_sig = ind.get("pump_signal", "NONE")

                if do_log:
                    print(f"[FOREX SCAN] RSI:{rsi_val:.1f} 1m:{trend} 1h:{trend_1h} 4h:{trend_4h} Pump:{pump_sig}", flush=True)
                    last_scan_log = now

                side, score, trades_to_open = self._determine_side(ind, spread_pts)
                if side is None:
                    buy_sc  = self._score_setup(ind, "buy",  spread_pts)
                    sell_sc = self._score_setup(ind, "sell", spread_pts)
                    if do_log:
                        print(f"[FOREX SCAN] No setup. Buy:{buy_sc} Sell:{sell_sc} (need {MIN_MOMENTUM_SCORE}+)", flush=True)
                    time.sleep(SCAN_INTERVAL)
                    continue

                try:
                    from news_sniper import get_upcoming_high_impact_events
                    cal = get_upcoming_high_impact_events()
                    if cal.get("recommendation") == "AVOID_NEW_TRADES":
                        print("[NEWS CALENDAR] Event high-impact dalam 30 menit! Skip entry.")
                        time.sleep(SCAN_INTERVAL)
                        continue
                except Exception:
                    pass

                adx = self._calc_adx_forex()
                if adx < 18:
                    if do_log: print(f"[REGIME] XAUUSD ADX={adx} RANGING. Skip.", flush=True)
                    time.sleep(SCAN_INTERVAL)
                    continue
                regime = "TRENDING" if adx >= 22 else "WEAK_TREND"

                vol_data   = self._calc_vol_regime_forex()
                vol_regime = vol_data.get("regime", "NORMAL")
                # BYPASS Volatility Guard if PUMP/DUMP is imminent
                if vol_regime in ("HIGH_VOL", "LOW_VOL") and pump_sig not in ("PUMP_IMMINENT", "DUMP_IMMINENT"):
                    print(f"[VOL] XAUUSD {vol_regime} ratio={vol_data.get('atr_ratio',0)}. Skip.")
                    time.sleep(SCAN_INTERVAL)
                    continue

                ev = self._calc_ev_forex(side, ind, score)
                if ev < 0.0003:
                    print(f"[EV] XAUUSD EV={ev} terlalu kecil. Skip.")
                    time.sleep(SCAN_INTERVAL)
                    continue

                # MTF CONFLUENCE — butuh minimal 2 TF aligned (Atau 1 TF + 5M Precision Tinggi)
                mtf = self._get_mtf_confluence(side)
                e5m = self._get_5m_entry_quality()
                
                mtf_pass = (mtf["aligned_count"] >= 2) or (mtf["aligned_count"] >= 1 and e5m["quality"] >= 50)
                
                if not mtf_pass:
                    if do_log:
                        print(f"[MTF] Confluence rendah: {mtf['aligned_count']}/4 TF. 5M Quality: {e5m['quality']}. Skip.")
                    time.sleep(SCAN_INTERVAL)
                    continue

                # MICRO MOMENTUM 1m — entry presisi
                micro = self._get_micro_momentum()
                if micro["direction"] != "NEUTRAL" and micro["direction"] != side.upper():
                    if do_log:
                        print(f"[MICRO] 1m momentum {micro['direction']} berlawanan {side.upper()}. Tunggu.")
                    time.sleep(SCAN_INTERVAL)
                    continue

                # 5M PRECISION CHECK (SMC FVG/Liq)
                if e5m["quality"] < 25 and mtf["aligned_count"] < 3:
                     if do_log:
                         print(f"[5M PRECISION] Entry {side.upper()} kurang tajam (Quality: {e5m['quality']}). Skip.")
                     time.sleep(SCAN_INTERVAL)
                     continue

                # SESSION OVERLAP (London+NY 12-16 UTC) — butuh score lebih tinggi
                is_overlap = 12 <= datetime.datetime.utcnow().hour < 16
                if is_overlap and score < MIN_MOMENTUM_SCORE + 5:
                    if do_log:
                        print(f"[OVERLAP] London+NY overlap. Score {score} < {MIN_MOMENTUM_SCORE+5}. Skip.")
                    time.sleep(SCAN_INTERVAL)
                    continue

                near_ath        = ind.get("near_ath", False)
                near_atl        = ind.get("near_atl", False)
                exhaustion_pump = ind.get("is_exhaustion_pump", False)
                exhaustion_dump = ind.get("is_exhaustion_dump", False)
                # BYPASS Smart Block if PUMP_IMMINENT (This is a momentum play, not exhaustion)
                if side == "buy" and (near_ath or exhaustion_pump) and pump_sig != "PUMP_IMMINENT":
                    print(f"[SMART BLOCK] ATH/Exhaustion — skip BUY.")
                    time.sleep(SCAN_INTERVAL)
                    continue
                if side == "sell" and (near_atl or exhaustion_dump) and pump_sig != "DUMP_IMMINENT":
                    print(f"[SMART BLOCK] ATL/Exhaustion — skip SELL.")
                    time.sleep(SCAN_INTERVAL)
                    continue

                xau_positions = [p for p in positions if "XAU" in p.get("symbol", "").upper()]
                if xau_positions:
                    if len(xau_positions) >= MAX_POSITIONS:
                        if int(now) % 60 < 3: print(f"[FOREX QUALITY] Max posisi. Skip.")
                        time.sleep(SCAN_INTERVAL)
                        continue
                    active_types = set(p.get("type", "") for p in xau_positions)
                    if "POSITION_TYPE_BUY" in active_types and side == "sell":
                        if int(now) % 60 < 3: print("[FOREX COMMIT] Ada BUY aktif. Skip SELL.")
                        time.sleep(SCAN_INTERVAL)
                        continue
                    if "POSITION_TYPE_SELL" in active_types and side == "buy":
                        if int(now) % 60 < 3: print("[FOREX COMMIT] Ada SELL aktif. Skip BUY.")
                        time.sleep(SCAN_INTERVAL)
                        continue
                    losing = [p for p in xau_positions if float(p.get("profit", 0)) < -0.5]
                    if losing:
                        if int(now) % 30 < 3: print(f"[FOREX QUALITY] {len(losing)} posisi rugi. Tunggu.")
                        time.sleep(SCAN_INTERVAL)
                        continue

                entry_price = price_data["ask"] if side == "buy" else price_data["bid"]
                atr         = ind.get("atr", 1.5)
                take_profit_val, stop_loss_val      = self._calc_tp_sl(entry_price, side, atr, spread_pts=spread_pts)
                lot         = self._calc_lot_size(balance)
                sym         = self._working_symbol or "XAUUSD"
                dxy_ctx     = self._get_dxy_context()

                print("")
                print("=" * 65)
                print(f"[FOREX v8.0] XAUUSD {side.upper()} | Score: {score}/100")
                print(f"  Pump: {pump_sig} | RSI: {rsi_val} | VWAP: {ind.get('vwap_dist',0)}%")
                print(f"  30m: {trend} | 1h: {trend_1h} | 4h: {trend_4h}")
                print(f"  MTF: {mtf['confluence']} ({mtf['aligned_count']}/4) | Micro: {micro['direction']} str:{micro['strength']}")
                print(f"  DXY: {dxy_ctx.get('trend','?')} ({dxy_ctx.get('change',0)}%) val:{dxy_ctx.get('value','?')}")
                print(f"  Whale: {ind.get('whale_signal','NORMAL')} | OBI: {ind.get('obi',0)}")
                print(f"  take_profit_val: {take_profit_val} | stop_loss_val: {stop_loss_val} | Lot: {lot}")
                print("=" * 65)

                fresh_price = self.get_live_price()
                fresh_entry = fresh_price["ask"] if side == "buy" else fresh_price["bid"]
                if fresh_entry == 0: fresh_entry = entry_price
                fresh_tp, fresh_sl = self._calc_tp_sl(fresh_entry, side, atr, spread_pts=spread_pts)

                if side == "buy" and fresh_sl >= fresh_entry:
                    print(f"[stop_loss_val GUARD] BUY stop_loss_val {fresh_sl} >= entry {fresh_entry} — skip")
                    time.sleep(SCAN_INTERVAL)
                    continue
                if side == "sell" and fresh_sl <= fresh_entry:
                    print(f"[stop_loss_val GUARD] SELL stop_loss_val {fresh_sl} <= entry {fresh_entry} — skip")
                    time.sleep(SCAN_INTERVAL)
                    continue

                # DATA UNTUK NOTIF TELEGRAM
                reason_data = {
                    'score': score, 'reason': f"Pump:{pump_sig} RSI:{rsi_val} MTF:{mtf['confluence']} 30m:{trend} 1h:{trend_1h}",
                    'rsi': rsi_val, 'vwap': ind.get('vwap_dist', 0), 'obi': ind.get('obi', 0),
                    'trend_1h': trend_1h, 'spread': spread_pts,
                    'e5m_sig': e5m.get('signal', '?'), 'e5m_q': e5m.get('quality', 0)
                }

                print(f"[EXECUTOR] Mengirim order {side.upper()} {sym} ke MT5...", flush=True)
                success, _ = self.place_forex_order(sym, side, lot, take_profit_val=fresh_tp, stop_loss_val=fresh_sl, reason_data=reason_data)
                if success:
                    from database import log_trade
                    log_trade(sym, fresh_entry, fresh_tp, fresh_sl, market="forex",
                              side=side, lot_size=lot, score=score,
                              reason=f"Pump:{pump_sig} RSI:{rsi_val} MTF:{mtf['confluence']} 30m:{trend} 1h:{trend_1h} 4h:{trend_4h}")
                    last_auto_trade = time.time()
                    print(f"[FOREX] Trade opened OK — take_profit_val:{fresh_tp} stop_loss_val:{fresh_sl}")

                time.sleep(SCAN_INTERVAL)

            except Exception as e:
                print(f"[FOREX ENGINE ERROR] {e}")
                time.sleep(5)
