"""
FOREX SCALPER v6.0 - AGGRESSIVE GENIUS EDITION
"""
import requests, os, time, datetime
from dotenv import load_dotenv
load_dotenv()

MAX_POSITIONS        = 5
SCAN_INTERVAL        = 3
COOLDOWN_AFTER_TRADE = 45
EQUITY_GUARD_PCT     = 0.92
MAX_SPREAD_POINTS    = 250
MIN_MOMENTUM_SCORE   = 50
CANDLE_LIMIT         = 100
MAX_TRADES_PER_SIGNAL = 3
SCALP_TP_POINTS      = 20.0
SCALP_SL_POINTS      = 8.0
TRAIL_BUFFER_POINTS     = 3.0    # Buffer poin saat trailing (SL = entry + profit_pt - buffer)
TRAIL_ACTIVATION_POINTS = 8.0    # Trailing mulai aktif setelah profit >= 8 poin (tunggu profit solid dulu)
BASE_LOT_PER_100     = 0.01
MAX_LOT_PER_TRADE    = 0.05
MIN_LOT_PER_TRADE    = 0.01
DXY_STRONG_THRESHOLD = 0.3
DXY_WEAK_THRESHOLD   = -0.3

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
        self._close_attempted   = set()
        self._dxy_cache         = {"change": 0.0, "trend": "NEUTRAL", "ts": 0}

        if self.is_active:
            try:
                info = self.get_account_information()
                if info:
                    print("[FOREX STARTUP] MT5 Balance: $" + str(info.get("balance",0)) + " Equity: $" + str(info.get("equity",0)))
                pos = self._get_positions()
                if pos:
                    print("[FOREX STARTUP] Active Trades: " + str(len(pos)))
                    for p in pos[:5]:
                        print("   > " + str(p.get("symbol")) + " | Vol: " + str(p.get("volume")) + " | Profit: " + str(p.get("profit")))
                else:
                    print("[FOREX STARTUP] No active trades.")
                self._working_symbol = self._resolve_symbol("XAUUSD")
                print("[FOREX STARTUP] Working symbol: " + str(self._working_symbol))
            except Exception as e:
                print("[FOREX STARTUP ERROR] " + str(e))
        else:
            print("[FOREX] MetaAPI credentials missing. Forex engine disabled.")

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

    def get_candles(self, symbol=None, timeframe="15m", limit=CANDLE_LIMIT):
        sym     = symbol or self._working_symbol or "XAUUSD"
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
                        return data
            except Exception:
                continue
        return []

    #  DXY MACRO CONTEXT 

    def _get_dxy_context(self):
        """
        Ambil DXY change dari PAXG/BTC sebagai proxy.
        DXY kuat = bearish gold bias. DXY lemah = bullish gold bias.
        Cache 5 menit agar tidak spam API.
        """
        now = time.time()
        if now - self._dxy_cache["ts"] < 300:
            return self._dxy_cache

        try:
            url = "https://api.bitget.com/api/v2/mix/market/ticker?symbol=PAXGUSDT&productType=USDT-FUTURES"
            res = requests.get(url, timeout=5, verify=False)
            if res.status_code == 200:
                data = res.json().get("data", {})
                if isinstance(data, list): data = data[0] if data else {}
                change = float(data.get("change24h", data.get("chgPct", 0)))
                if abs(change) < 1.0:
                    change = change * 100
                dxy_change = -change
                trend = "NEUTRAL"
                if dxy_change > DXY_STRONG_THRESHOLD:   trend = "BULLISH"
                elif dxy_change < DXY_WEAK_THRESHOLD:   trend = "BEARISH"
                self._dxy_cache = {"change": round(dxy_change, 3), "trend": trend, "ts": now}
                return self._dxy_cache
        except Exception:
            pass

        self._dxy_cache["ts"] = now
        return self._dxy_cache

    # ── ORDER BOOK & WHALE DETECTION (via PAXG proxy) ────────────────────────

    def _calc_adx_forex(self, period: int = 14) -> float:
        """
        Hitung ADX untuk XAUUSD dari candle MetaAPI.
        ADX > 22 = trending, boleh entry.
        ADX < 18 = ranging, skip.
        """
        try:
            candles = self.get_candles(timeframe="15m", limit=period * 3)
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
            candles = self.get_candles(timeframe="15m", limit=30)
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
        Expected Value untuk XAUUSD trade — sudah include spread cost.
        EV = (P_win x TP_pct) - (P_loss x SL_pct) - spread_cost
        TP = 20 poin, SL = 8 poin, spread ~2.8 poin
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

        # XAUUSD: TP 20 poin / entry ~4700 = ~0.43%, SL 8 poin = ~0.17%
        entry_approx = self._last_known_price if self._last_known_price > 0 else 4700
        tp_pct = 20.0 / entry_approx
        sl_pct = 8.0  / entry_approx

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
        """Ambil trend HTF (4h atau 1h) dari candle MetaAPI."""
        try:
            candles = self.get_candles(timeframe=timeframe, limit=50)
            if len(candles) < 20:
                return "NEUTRAL"
            closes = [float(c.get("close", 0)) for c in candles]
            ema200 = closes[0]
            k = 2 / (min(200, len(closes)) + 1)
            for c in closes:
                ema200 = c * k + ema200 * (1 - k)
            last = closes[-1]
            if last > ema200 * 1.001: return "BULLISH"
            if last < ema200 * 0.999: return "BEARISH"
            return "NEUTRAL"
        except Exception:
            return "NEUTRAL"

    def _calc_indicators(self):
        """
        XAUUSD Multi-Timeframe Indicator Engine v6.0.
        Data source: MetaAPI candle 15m (fallback 5m, lalu price momentum).
        Tambahan v6.0: 4h trend bias, DXY context, lebih banyak sinyal.
        """
        candles = self.get_candles(timeframe="15m", limit=100)
        if len(candles) < 20:
            candles = self.get_candles(timeframe="5m", limit=100)

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

        # Trend 15m
        trend = "NEUTRAL"
        if last_close > ema200: trend = "BULLISH"
        elif last_close < ema200: trend = "BEARISH"

        # Volume Spike
        vol_spike = last_vol > avg_vol * 2.0

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

        # HTF trends (1h dan 4h)  bias filter
        trend_1h = self._get_htf_trend("1h")
        trend_4h = self._get_htf_trend("4h")

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

        # ── DEMAND/SUPPLY ZONE DETECTION ─────────────────────────────────────
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

        #  1. PUMP SIGNAL (max 35 poin) 
        if side == "buy":
            if pump_sig == "PUMP_IMMINENT":  score += 35
            elif pump_sig == "BREAKOUT_UP":  score += 25
            if rsi_div == "BULLISH_DIVERGENCE": score += 20
        else:
            if pump_sig == "DUMP_IMMINENT":   score += 35
            elif pump_sig == "BREAKOUT_DOWN": score += 25
            if rsi_div == "BEARISH_DIVERGENCE": score += 20

        #  2. Volume Spike (max 12 poin) 
        if vol_spike: score += 12

        #  3. RSI Zone (max 15 poin) 
        if side == "buy":
            if 28 <= rsi <= 48:   score += 15   # Oversold recovery
            elif 48 < rsi <= 58:  score += 8
            elif rsi > 72:        score -= 12   # Overbought, risky long
        else:
            if 52 <= rsi <= 72:   score += 15   # Overbought rejection
            elif 42 <= rsi < 52:  score += 8
            elif rsi < 28:        score -= 12   # Oversold, risky short

        #  4. FVG (max 10 poin) 
        if side == "buy"  and fvg == "BULLISH_FVG": score += 10
        if side == "sell" and fvg == "BEARISH_FVG": score += 10

        #  5. Order Block (max 8 poin) 
        if side == "buy"  and ob == "BULLISH_OB": score += 8
        if side == "sell" and ob == "BEARISH_OB": score += 8

        #  6. MSS / CHoCH (max 10 poin) 
        if side == "buy"  and (mss_b or choch_b): score += 10
        if side == "sell" and (mss_s or choch_s): score += 10

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

        #  8. Whale Signal via PAXG Order Book (max 15 poin) 
        # Ini sinyal paling kuat — whale di gold market = institutional money
        whale = ind.get("whale_signal", "NORMAL")
        obi   = ind.get("obi", 0.0)
        if side == "buy":
            if whale == "WHALE_BUY":   score += 15
            elif whale == "WHALE_SELL": score -= 12  # Whale jual = jangan beli
            if obi > 0.20:             score += 10  # Buyer dominance kuat
            elif obi > 0.10:           score += 5
            elif obi < -0.15:          score -= 8   # Seller dominance
        else:
            if whale == "WHALE_SELL":  score += 15
            elif whale == "WHALE_BUY": score -= 12
            if obi < -0.20:            score += 10
            elif obi < -0.10:          score += 5
            elif obi > 0.15:           score -= 8

        #  8. Trend 15m alignment (max 5 poin, penalti -8) 
        # Penalti dikurangi kalau ada sinyal pembalikan kuat (pump/dump signal)
        reversal_signal = pump_sig in ("PUMP_IMMINENT", "DUMP_IMMINENT", "BREAKOUT_UP", "BREAKOUT_DOWN")
        trend_penalty_15m = 4 if reversal_signal else 8   # penalti lebih kecil saat ada reversal
        if side == "buy"  and trend == "BULLISH": score += 5
        if side == "sell" and trend == "BEARISH": score += 5
        if side == "buy"  and trend == "BEARISH": score -= trend_penalty_15m
        if side == "sell" and trend == "BULLISH": score -= trend_penalty_15m

        #  9. Trend 1h confirmation (max 10 poin, penalti -12 normal, -6 saat reversal) 
        trend_penalty_1h = 6 if reversal_signal else 12
        if side == "buy"  and trend_1h == "BULLISH": score += 10
        if side == "sell" and trend_1h == "BEARISH": score += 10
        if side == "buy"  and trend_1h == "BEARISH": score -= trend_penalty_1h
        if side == "sell" and trend_1h == "BULLISH": score -= trend_penalty_1h

        #  10. Trend 4h BIAS FILTER (max 8 poin, penalti -15 normal, -5 saat reversal kuat) 
        # Saat PUMP/DUMP_IMMINENT, penalti 4h dikurangi drastis
        # Karena reversal sering terjadi melawan trend 4h
        trend_penalty_4h = 5 if reversal_signal else 15
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

        return max(0, min(100, score))

    def _determine_side(self, ind, spread_points):
        """
        Return (side, score, trades_to_open) atau (None, 0, 0).
        v6.0: lebih agresif  trades naik lebih cepat sesuai confidence.
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

        if buy_score >= sell_score and buy_score >= MIN_MOMENTUM_SCORE:
            best_side, best_score = "buy", buy_score
        elif sell_score > buy_score and sell_score >= MIN_MOMENTUM_SCORE:
            best_side, best_score = "sell", sell_score

        if best_side is None:
            return None, 0, 0

        # Skip pure neutral
        if rsi == 50.0 and trend == "NEUTRAL" and pump_sig == "NONE" and not choch_b and not choch_s:
            return None, 0, 0

        # Jumlah trade berdasarkan confidence  lebih agresif dari v5
        if best_score >= 80:   trades = MAX_TRADES_PER_SIGNAL       # 3 trade
        elif best_score >= 65: trades = 2
        elif best_score >= 50: trades = 1
        else:                  trades = 1

        return best_side, best_score, trades

    #  TP/SL & LOT SIZING 

    def _calc_tp_sl(self, price, side, atr):
        """
        TP/SL ATR-based dengan hard minimum.
        SL min 7 poin (spread + noise), TP min 15 poin (RR 1:2.1+).
        """
        if atr and 1.0 <= atr <= 15:
            sl_dist = max(atr * 1.5, SCALP_SL_POINTS)
            tp_dist = max(atr * 4.0, SCALP_TP_POINTS)
        else:
            sl_dist = SCALP_SL_POINTS
            tp_dist = SCALP_TP_POINTS

        sl_dist = max(sl_dist, 7.0)
        tp_dist = max(tp_dist, 15.0)
        sl_dist = min(sl_dist, 12.0)
        tp_dist = min(tp_dist, 30.0)

        if side == "buy":
            return round(price + tp_dist, 3), round(price - sl_dist, 3)
        else:
            return round(price - tp_dist, 3), round(price + sl_dist, 3)

    def _calc_lot_size(self, balance):
        """
        Lot sizing FIXED: selalu 0.01 lot per trade.
        Cent account — kontrol risiko ketat, tidak berubah apapun balance-nya.
        """
        return MIN_LOT_PER_TRADE  # Fixed 0.01

    def _is_trading_session(self):
        """
        Trade di London (07-16 UTC) dan NY (12-21 UTC).
        Tambah Asia open (02-05 UTC)  gold volatile saat Tokyo open.
        Skip weekend.
        """
        now_utc = datetime.datetime.utcnow()
        weekday = now_utc.weekday()
        if weekday == 6: return False
        if weekday == 5 and now_utc.hour >= 21: return False
        hour = now_utc.hour
        return (2 <= hour < 5) or (7 <= hour < 16) or (12 <= hour < 21)

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

    def place_forex_order(self, symbol, side, amount, tp=None, sl=None):
        if not self.is_active: return False, "Forex not active"
        try:
            url = self.base_url + "/users/current/accounts/" + self.account_id + "/trade"
            headers = {"auth-token": self.api_token, "Content-Type": "application/json"}

            # Validasi SL sebelum kirim — SL BUY harus < harga saat ini
            # Ini mencegah SL yang salah arah (misal breakeven dari posisi lain)
            if sl and sl > 0:
                live = self.get_live_price(symbol)
                mid  = live.get("mid", 0)
                if mid > 0:
                    if side.lower() == "buy" and sl >= mid:
                        # SL di atas harga — salah arah, recalculate
                        sl = round(mid - SCALP_SL_POINTS, 3)
                        print("[SL GUARD] BUY SL salah arah, reset ke " + str(sl))
                    elif side.lower() == "sell" and sl <= mid:
                        sl = round(mid + SCALP_SL_POINTS, 3)
                        print("[SL GUARD] SELL SL salah arah, reset ke " + str(sl))

            payload = {
                "symbol":     symbol,
                "actionType": "ORDER_TYPE_BUY" if side.lower() == "buy" else "ORDER_TYPE_SELL",
                "volume":     amount,
                "comment":    "GeniusForex v6.0",
            }
            if sl: payload["stopLoss"]   = sl
            if tp: payload["takeProfit"] = tp
            res    = requests.post(url, headers=headers, json=payload, timeout=10)
            result = res.json()
            if res.status_code == 200:
                print("[FOREX SUCCESS] " + side.upper() + " " + symbol + " lot=" + str(amount) + " TP=" + str(tp) + " SL=" + str(sl))
                return True, result
            else:
                msg = result.get("message", str(result))
                print("[FOREX FAILED] " + symbol + ": " + msg)
                return False, msg
        except Exception as e:
            print("[FOREX API CRASH] " + str(e))
            return False, str(e)

    def place_xauusd_scalp_batch(self, side, trades_count=3, volume=0.01, tp=None, sl=None):
        """Dipakai oleh news_sniper.py untuk eksekusi cepat."""
        sym = self._working_symbol or self._resolve_symbol("XAUUSD")
        price_data = self.get_live_price(sym)
        price = price_data["bid"] if side == "sell" else price_data["ask"]
        if price == 0:
            print("[SCALP BATCH] Cannot get price, aborting.")
            return False
        if tp is None or sl is None or tp == 0 or sl == 0:
            tp, sl = self._calc_tp_sl(price, side, 1.5)
        print("[SCALP BATCH] Firing " + str(trades_count) + "x " + side.upper() + " " + sym + " @ " + str(price) + " TP=" + str(tp) + " SL=" + str(sl))
        any_success = False
        for i in range(trades_count):
            success, _ = self.place_forex_order(sym, side, volume, tp=tp, sl=sl)
            if success:
                from database import log_trade
                log_trade(sym, price, tp, sl, market="forex")
                any_success = True
            time.sleep(0.1)
        return any_success

    def update_forex_sl(self, position_id, new_sl, current_tp=None):
        """
        Update SL posisi via POSITION_MODIFY.
        WAJIB kirim takeProfit bersamaan — kalau tidak, beberapa broker MT5
        akan reset TP ke 0 (hilang) saat SL diupdate.
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
            # Selalu sertakan TP kalau ada — mencegah broker reset TP ke 0
            if current_tp and float(current_tp) > 0:
                payload["takeProfit"] = float(current_tp)
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code == 200:
                return True
            try:
                err = res.json().get("message", res.text[:100])
            except Exception:
                err = res.text[:100]
            print("[UPDATE SL FAIL] pos=" + str(position_id) + " sl=" + str(new_sl) + " status=" + str(res.status_code) + ": " + err)
            return False
        except Exception as e:
            print("[UPDATE SL ERROR] pos=" + str(position_id) + ": " + str(e))
            return False

    #  TRAILING STOP 

    def _trail_positions(self, positions):
        """
        Trailing SL — 2 momen kritis untuk XAUUSD.
        Selalu kirim TP bersamaan saat update SL agar TP tidak hilang.
        """
        for p in positions:
            if "XAU" not in p.get("symbol", "").upper(): continue
            open_price  = float(p.get("openPrice", 0))
            pos_id      = p.get("id")
            pos_type    = p.get("type", "")
            profit      = float(p.get("profit", 0))
            current_sl  = float(p.get("stopLoss", 0))
            current_tp  = float(p.get("takeProfit", 0))   # ambil TP dari posisi
            sym         = p.get("symbol", self._working_symbol or "XAUUSDc")
            if open_price == 0: continue

            is_buy        = pos_type == "POSITION_TYPE_BUY"
            current_price = float(p.get("currentPrice", 0))
            profit_pt     = 0
            if current_price > 0 and current_price != open_price:
                profit_pt = (current_price - open_price) if is_buy else (open_price - current_price)

            direction = "BUY" if is_buy else "SELL"
            print("[TRAIL] " + sym + " " + direction + " open=" + str(open_price) + " cur=" + str(current_price) + " profit=$" + str(round(profit,2)) + " pt=" + str(round(profit_pt,2)) + " sl=" + str(current_sl))

            # AUTO-CLOSE: rugi > $7
            if profit < -7.0 and pos_id not in self._close_attempted:
                self._close_attempted.add(pos_id)
                print("[FOREX AUTO-CLOSE] " + str(pos_id) + " loss exceeded. Closing.")
                try:
                    url = self.base_url + "/users/current/accounts/" + self.account_id + "/trade"
                    headers = {"auth-token": self.api_token, "Content-Type": "application/json"}
                    res = requests.post(url, headers=headers,
                        json={"actionType": "POSITION_CLOSE_ID", "positionId": pos_id}, timeout=8)
                    if res.status_code == 200:
                        print("[FOREX AUTO-CLOSE] " + str(pos_id) + " closed OK")
                    else:
                        self._close_attempted.discard(pos_id)
                except Exception as e:
                    self._close_attempted.discard(pos_id)
                continue

            # TRAILING SL - LOGIKA BARU (jarak konsisten 8 poin dari harga)
            # Tidak ada breakeven +0.2 yang terlalu sempit.
            # SL hanya naik kalau profit sudah solid.
            # Jarak SL ke harga selalu ~8 poin = cukup untuk noise XAUUSD.
            #
            # profit < 12 poin  : DIAM, SL awal di entry-8 tetap
            # profit >= 12 poin : SL ke entry+4  (jarak ke harga = profit-4, min 8)
            # profit >= 18 poin : SL ke entry+10 (jarak ke harga = profit-10, min 8)
            # TP kena di 20 poin: selesai, profit $2+ per trade
            #
            # Contoh: entry 4711, profit 12 poin (harga 4723)
            #   SL naik ke 4715 (entry+4), jarak ke harga = 8 poin ✓
            # Contoh: entry 4711, profit 18 poin (harga 4729)
            #   SL naik ke 4721 (entry+10), jarak ke harga = 8 poin ✓

            if profit_pt < 12.0:
                # Belum 12 poin — diam, biarkan SL awal bekerja
                if profit_pt > 0:
                    print("[TRAIL] " + sym + " profit_pt=" + str(round(profit_pt,2)) + " < 12.0, waiting...")
                continue

            if is_buy:
                if profit_pt >= 18.0:
                    target_sl = round(open_price + 12.0, 3)
                    stage     = "LOCK-12"
                else:
                    target_sl = round(open_price + 5.0, 3)
                    stage     = "LOCK-5"
            else:
                if profit_pt >= 18.0:
                    target_sl = round(open_price - 12.0, 3)
                    stage     = "LOCK-12"
                else:
                    target_sl = round(open_price - 5.0, 3)
                    stage     = "LOCK-5"

            # SL hanya bergerak ke arah profit, tidak pernah mundur
            if is_buy:
                should_update = (current_sl == 0 or target_sl > current_sl)
            else:
                should_update = (current_sl == 0 or target_sl < current_sl)

            if should_update:
                # Selalu kirim current_tp agar TP tidak hilang saat SL diupdate
                ok = self.update_forex_sl(pos_id, target_sl, current_tp=current_tp)
                if ok:
                    print("OK [" + stage + "] " + sym +
                          " SL " + str(current_sl) + " -> " + str(target_sl) +
                          " | TP=" + str(current_tp) +
                          " | profit_pt=" + str(round(profit_pt, 1)) + "pt")
                else:
                    print("FAIL [" + stage + "] " + sym + " -> " + str(target_sl))

    #  MAIN ENGINE LOOP 

    def monitor_forex_market(self):
        """
        FOREX ENGINE v6.0 - Aggressive Genius XAUUSD Scalper.

        PERBAIKAN KRITIS v6.0:
        - FIX: UnboundLocalError 'side' - variabel side sekarang didefinisikan
          SEBELUM dipakai di COMMIT TO DIRECTION check
        - Cooldown 45 detik (lebih agresif)
        - Lot sizing dinamis
        - 4h trend bias filter
        - DXY macro context
        - Trailing aktif dari 3 poin profit
        """
        print("[FOREX ENGINE v6.0] Aggressive Genius XAUUSD Scalper AKTIF!")
        print("  Sessions: Asia(02-05) + London(07-16) + NY(12-21) UTC")
        print("  TP: " + str(SCALP_TP_POINTS) + " pts | SL: " + str(SCALP_SL_POINTS) + " pts | Cooldown: " + str(COOLDOWN_AFTER_TRADE) + "s")
        last_auto_trade = 0

        while True:
            try:
                if not self.is_active:
                    time.sleep(60)
                    continue

                # TRAILING STOP — jalan SELALU, tidak peduli session
                # Harus sebelum session filter agar posisi tetap diproteksi
                # bahkan saat outside trading hours
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

                if broker_price > 0:
                    print("[FOREX] Price: " + str(broker_price) + " | Trades: " + str(active_count) + " | Lots: " + str(round(total_lots,2)) + " | Spread: " + str(spread_pts) + "pts")

                if broker_price > 0 and positions:
                    for p in positions:
                        if "XAU" in p.get("symbol", "").upper():
                            p["currentPrice"] = broker_price
                    self._trail_positions(positions)

                # SESSION FILTER — hanya untuk entry baru, bukan trailing
                if not self._is_trading_session():
                    print("[FOREX SESSION] Outside trading session. Waiting 5 min...")
                    time.sleep(300)
                    continue

                # EQUITY GUARD
                info = self.get_account_information()
                if not info:
                    time.sleep(10)
                    continue
                balance = float(info.get("balance", 0))
                equity  = float(info.get("equity", 0))
                if balance > 0 and equity < balance * EQUITY_GUARD_PCT:
                    print("[EQUITY GUARD] Drawdown! Equity: $" + str(equity) + " / Balance: $" + str(balance) + ". Halting.")
                    time.sleep(60)
                    continue

                if broker_price == 0:
                    time.sleep(5)
                    continue

                # SPREAD FILTER
                if spread_pts > MAX_SPREAD_POINTS:
                    print("[SPREAD GUARD] Spread " + str(spread_pts) + "pts too wide. Skipping.")
                    time.sleep(SCAN_INTERVAL)
                    continue

                # COOLDOWN
                now = time.time()
                cooldown_remaining = COOLDOWN_AFTER_TRADE - (now - last_auto_trade)
                if cooldown_remaining > 0:
                    if int(now) % 30 < 3:
                        print("[FOREX COOLDOWN] " + str(round(cooldown_remaining)) + "s remaining")
                    time.sleep(SCAN_INTERVAL)
                    continue

                # CALCULATE INDICATORS DULU  side harus ada sebelum COMMIT check
                print("[FOREX SCAN] Calculating indicators for " + str(self._working_symbol) + "...")
                ind = self._calc_indicators()
                if not ind:
                    print("[FOREX SCAN] No indicators. Retrying...")
                    time.sleep(5)
                    continue

                rsi_val  = ind.get("rsi", 0)
                trend    = ind.get("trend", "NEUTRAL")
                trend_1h = ind.get("trend_1h", "NEUTRAL")
                trend_4h = ind.get("trend_4h", "NEUTRAL")
                pump_sig = ind.get("pump_signal", "NONE")
                print("[FOREX SCAN] RSI:" + str(rsi_val) + " 15m:" + trend + " 1h:" + trend_1h + " 4h:" + trend_4h + " Pump:" + pump_sig)

                # DETERMINE SIDE  HARUS SEBELUM COMMIT CHECK
                side, score, trades_to_open = self._determine_side(ind, spread_pts)
                if side is None:
                    buy_sc  = self._score_setup(ind, "buy",  spread_pts)
                    sell_sc = self._score_setup(ind, "sell", spread_pts)
                    print("[FOREX SCAN] No setup. Buy:" + str(buy_sc) + " Sell:" + str(sell_sc) + " (need " + str(MIN_MOMENTUM_SCORE) + "+)")
                    time.sleep(SCAN_INTERVAL)
                    continue

                # MARKET REGIME FILTER (ADX)
                adx = self._calc_adx_forex()
                if adx < 18:
                    print("[REGIME] XAUUSD ADX=" + str(adx) + " RANGING. Skip entry.")
                    time.sleep(SCAN_INTERVAL)
                    continue
                regime = "TRENDING" if adx >= 22 else "WEAK_TREND"

                # VOLATILITY REGIME FILTER
                vol_data   = self._calc_vol_regime_forex()
                vol_regime = vol_data.get("regime", "NORMAL")
                if vol_regime == "HIGH_VOL":
                    print("[VOL] XAUUSD HIGH_VOL ratio=" + str(vol_data["atr_ratio"]) + ". Skip.")
                    time.sleep(SCAN_INTERVAL)
                    continue
                if vol_regime == "LOW_VOL":
                    print("[VOL] XAUUSD LOW_VOL ratio=" + str(vol_data["atr_ratio"]) + ". Skip.")
                    time.sleep(SCAN_INTERVAL)
                    continue

                # EXPECTED VALUE CHECK
                ev = self._calc_ev_forex(side, ind, score)
                if ev < 0.0003:
                    print("[EV] XAUUSD EV=" + str(ev) + " terlalu kecil. Skip.")
                    time.sleep(SCAN_INTERVAL)
                    continue

                print("[INTEL] ADX:" + str(adx) + " " + regime + " | Vol:" + vol_regime + " | EV:" + str(ev) + " | Whale:" + str(ind.get("whale_signal","NORMAL")) + " OBI:" + str(ind.get("obi",0)))

                # POSITION QUALITY CHECK
                xau_positions = [p for p in positions if "XAU" in p.get("symbol", "").upper()]
                if xau_positions:
                    # Hard cap 3 posisi XAU
                    if len(xau_positions) >= 3:
                        if int(now) % 60 < 3:
                            print("[FOREX QUALITY] Sudah " + str(len(xau_positions)) + " posisi aktif (max 3). Skip.")
                        time.sleep(SCAN_INTERVAL)
                        continue

                    # COMMIT TO DIRECTION  side sudah terdefinisi di atas
                    active_types = set(p.get("type", "") for p in xau_positions)
                    has_buy  = "POSITION_TYPE_BUY"  in active_types
                    has_sell = "POSITION_TYPE_SELL" in active_types
                    if has_buy and side == "sell":
                        if int(now) % 60 < 3:
                            print("[FOREX COMMIT] Ada posisi BUY aktif. Tidak buka SELL. Tunggu SL/TP.")
                        time.sleep(SCAN_INTERVAL)
                        continue
                    if has_sell and side == "buy":
                        if int(now) % 60 < 3:
                            print("[FOREX COMMIT] Ada posisi SELL aktif. Tidak buka BUY. Tunggu SL/TP.")
                        time.sleep(SCAN_INTERVAL)
                        continue

                    # Jangan tambah kalau ada yang rugi
                    losing = [p for p in xau_positions if float(p.get("profit", 0)) < -0.5]
                    if losing:
                        if int(now) % 30 < 3:
                            print("[FOREX QUALITY] " + str(len(losing)) + " posisi rugi. Tunggu dulu.")
                        time.sleep(SCAN_INTERVAL)
                        continue

                # POSITION LIMIT
                xau_active      = len(xau_positions)
                slots_available = max(0, 3 - xau_active)
                trades_to_open  = min(trades_to_open, slots_available)
                if trades_to_open <= 0:
                    time.sleep(SCAN_INTERVAL)
                    continue

                # CALCULATE TP/SL
                entry_price = price_data["ask"] if side == "buy" else price_data["bid"]
                atr         = ind.get("atr", 1.5)
                tp, sl      = self._calc_tp_sl(entry_price, side, atr)

                # LOT SIZE DINAMIS
                lot = self._calc_lot_size(balance)

                # EXECUTE
                sym     = self._working_symbol or "XAUUSD"
                dxy_ctx = self._get_dxy_context()
                print("")
                print("=" * 65)
                print("[FOREX v6.0] XAUUSD " + side.upper() + " x" + str(trades_to_open) + " | Score: " + str(score) + "/100")
                print("  Pump: " + str(pump_sig) + " | RSI Div: " + str(ind.get("rsi_divergence","NONE")))
                print("  Price: " + str(entry_price) + " | ATR: " + str(atr) + " | Lot: " + str(lot))
                print("  RSI: " + str(rsi_val) + " | VWAP: " + str(ind.get("vwap_dist",0)) + "%")
                print("  15m: " + trend + " | 1h: " + trend_1h + " | 4h: " + trend_4h)
                print("  DXY: " + dxy_ctx.get("trend","NEUTRAL") + " (" + str(dxy_ctx.get("change",0)) + "%)")
                print("  Whale: " + str(ind.get("whale_signal","NORMAL")) + " | OBI: " + str(ind.get("obi",0)))
                print("  DemandZone: " + str(ind.get("in_demand",False)) + " | SupplyZone: " + str(ind.get("in_supply",False)))
                print("  TP: " + str(tp) + " | SL: " + str(sl))
                print("=" * 65)

                opened = 0
                for i in range(trades_to_open):
                    # Refresh harga untuk setiap trade — harga bisa bergerak antar trade
                    fresh_price = self.get_live_price()
                    fresh_entry = fresh_price["ask"] if side == "buy" else fresh_price["bid"]
                    if fresh_entry == 0:
                        fresh_entry = entry_price  # fallback ke harga awal

                    # Recalculate TP/SL dari harga fresh
                    fresh_tp, fresh_sl = self._calc_tp_sl(fresh_entry, side, atr)

                    # Validasi ketat: SL BUY harus < entry, SL SELL harus > entry
                    if side == "buy" and fresh_sl >= fresh_entry:
                        print("[SL GUARD] BUY SL " + str(fresh_sl) + " >= entry " + str(fresh_entry) + " — skip trade")
                        continue
                    if side == "sell" and fresh_sl <= fresh_entry:
                        print("[SL GUARD] SELL SL " + str(fresh_sl) + " <= entry " + str(fresh_entry) + " — skip trade")
                        continue

                    success, _ = self.place_forex_order(sym, side, lot, tp=fresh_tp, sl=fresh_sl)
                    if success:
                        from database import log_trade
                        log_trade(sym, fresh_entry, fresh_tp, fresh_sl, market="forex",
                                  side=side, lot_size=lot, score=score,
                                  reason="Pump:" + str(pump_sig) + " RSI:" + str(rsi_val) + " 15m:" + trend + " 1h:" + trend_1h + " 4h:" + trend_4h)
                        opened += 1
                    time.sleep(0.2)  # sedikit lebih lama agar harga stabil

                if opened > 0:
                    print("[FOREX] Opened " + str(opened) + "/" + str(trades_to_open) + " trades OK")
                    last_auto_trade = time.time()

                time.sleep(SCAN_INTERVAL)

            except Exception as e:
                print("[FOREX ENGINE ERROR] " + str(e))
                time.sleep(5)
