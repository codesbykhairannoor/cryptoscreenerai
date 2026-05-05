"""
FOREX SCALPER v5.0 - SMART TP/SL EDITION
=========================================
Strategi TP/SL yang masuk akal untuk XAUUSD:

MASALAH SEBELUMNYA:
- SL 1.5-3 poin terlalu dekat → kena noise + spread 2.8 pts
- TP 3 poin terlalu kecil → tidak worth it setelah fee

STRATEGI BARU:
- SL: 7-10 poin (70-100 pip) — cukup jauh dari noise dan spread
- TP: 20 poin (200 pip) — 1:2.5 RR minimum
- Trailing: SL naik setiap +5 poin profit, lock profit agresif
- Lot: 0.01 per trade (cent account, risk terkontrol)
"""

import requests
import os
import time
import datetime
from dotenv import load_dotenv

load_dotenv()

MAX_POSITIONS        = 5      # Max 5 posisi sekaligus
SCAN_INTERVAL        = 3      # Scan setiap 3 detik
COOLDOWN_AFTER_TRADE = 60     # Cooldown 60 detik antar entry
COOLDOWN_AFTER_CONFLICT = 600 # 10 menit cooldown setelah direction conflict
EQUITY_GUARD_PCT     = 0.92   # Halt kalau equity < 92%
MAX_SPREAD_POINTS    = 300    # Toleransi spread
MIN_MOMENTUM_SCORE   = 35     # Minimum score untuk entry
CANDLE_LIMIT         = 100

# Max trade per signal — dikurangi untuk kontrol risk
# 5 trade salah arah = loss besar. Max 2 lebih aman.
MAX_TRADES_PER_SIGNAL = 3     # Max 3 trade per signal

# TP/SL yang masuk akal untuk XAUUSD cent account
SCALP_TP_POINTS      = 20.0   # TP 200 pip (20 poin)
SCALP_SL_POINTS      = 8.0    # SL 80 pip (8 poin)
RISK_PCT_PER_TRADE   = 0.01   # 1% risk per trade
MAX_LOT_PER_TRADE    = 0.01   # Max 0.01 lot per trade


class ForexExecutor:
    """
    Dedicated Forex Engine for MetaTrader 5 via MetaAPI.
    XAUUSD Institutional Scalping - SMC + Momentum Scoring.
    Semua data harga dan indikator dari MetaAPI langsung.
    """
    def __init__(self):
        self.api_token  = os.getenv("FOREX_META_API_TOKEN")
        self.account_id = os.getenv("FOREX_ACCOUNT_ID")
        self.base_url   = "https://mt-client-api-v1.london.agiliumtrade.ai"
        self.is_active  = bool(self.api_token and self.account_id)
        self._working_symbol = None

        if self.is_active:
            try:
                info = self.get_account_information()
                if info:
                    bal = info.get("balance", 0)
                    eq  = info.get("equity", 0)
                    print("[FOREX STARTUP] MT5 Balance: $" + str(bal) + " (Equity: $" + str(eq) + ")")
                pos = self._get_positions()
                if pos:
                    print(f"[FOREX STARTUP] Active Trades: {len(pos)}")
                    for p in pos[:5]:
                        sym = p.get("symbol")
                        vol = p.get("volume")
                        pnl = p.get("profit")
                        print(f"   > {sym} | Vol: {vol} | Profit: {pnl}")
                else:
                    print("[FOREX STARTUP] No active trades.")
                self._working_symbol = self._resolve_symbol("XAUUSD")
                print(f"[FOREX STARTUP] Working symbol: {self._working_symbol}")
            except Exception as e:
                print(f"[FOREX STARTUP ERROR] {e}")
        else:
            print("[FOREX] MetaAPI credentials missing. Forex engine disabled.")

    # --- ACCOUNT & CONNECTION ---

    def get_account_information(self):
        if not self.is_active: return None
        try:
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/account-information"
            headers = {"auth-token": self.api_token}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200: return res.json()
        except Exception as e:
            print(f"[FOREX ERROR] Account fetch failed: {e}")
        return None

    def test_connection(self):
        info = self.get_account_information()
        if info and "balance" in info:
            bal = info["balance"]
            return True, "Connected to MT5 (Balance: $" + str(bal) + ")"
        return False, "MT5 Connection Failed."

    # --- SYMBOL RESOLUTION ---

    def _resolve_symbol(self, base):
        """Cari suffix yang benar untuk broker ini."""
        suffixes = ["", "c", ".m", ".i", "+", "#", "m"]
        for s in suffixes:
            sym = base + s
            try:
                url = f"{self.base_url}/users/current/accounts/{self.account_id}/symbols/{sym}/current-price"
                headers = {"auth-token": self.api_token}
                res = requests.get(url, headers=headers, timeout=5)
                if res.status_code == 200:
                    d = res.json()
                    if float(d.get("bid", 0)) > 0:
                        return sym
            except Exception:
                continue
        return base

    # --- PRICE FETCHING ---

    def get_live_price(self, symbol=None):
        """Ambil harga live dari MetaAPI. Return dict: {bid, ask, spread_points, mid}"""
        sym = symbol or self._working_symbol or "XAUUSD"
        try:
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/symbols/{sym}/current-price"
            headers = {"auth-token": self.api_token}
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                d      = res.json()
                bid    = float(d.get("bid", 0))
                ask    = float(d.get("ask", bid))
                spread = round((ask - bid) * 10, 1)
                return {"bid": bid, "ask": ask, "spread_points": spread, "mid": (bid + ask) / 2}
        except Exception as e:
            print(f"[FOREX PRICE ERROR] {e}")
        return {"bid": 0, "ask": 0, "spread_points": 999, "mid": 0}

    # --- CANDLE DATA FROM METAAPI ---

    def get_candles(self, symbol=None, timeframe="5m", limit=CANDLE_LIMIT):
        """
        Ambil candle historis dari MetaAPI.
        
        PENTING: Historical candles pakai hostname BERBEDA dari trading API:
        Trading:   mt-client-api-v1.london.agiliumtrade.ai
        Candles:   mt-market-data-client-api-v1.new-york.agiliumtrade.ai
        
        Path yang benar:
        /users/current/accounts/{id}/historical-market-data/symbols/{symbol}/timeframes/{tf}/candles
        """
        sym     = symbol or self._working_symbol or "XAUUSD"
        headers = {"auth-token": self.api_token}

        # Hostname khusus untuk historical market data
        market_data_hosts = [
            "https://mt-market-data-client-api-v1.new-york.agiliumtrade.ai",
            "https://mt-market-data-client-api-v1.london.agiliumtrade.ai",
            "https://mt-market-data-client-api-v1.singapore.agiliumtrade.ai",
        ]

        for host in market_data_hosts:
            url = (f"{host}/users/current/accounts/{self.account_id}"
                   f"/historical-market-data/symbols/{sym}/timeframes/{timeframe}/candles"
                   f"?limit={limit}")
            try:
                res = requests.get(url, headers=headers, timeout=15)
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, list) and len(data) > 0:
                        print(f"[METAAPI CANDLE] Got {len(data)} candles from {host.split('.')[0].split('-')[-1]}")
                        return data
                elif res.status_code != 404:
                    # Log error selain 404 (404 = coba host lain)
                    try:
                        err = res.json().get('message', res.text[:80])
                    except Exception:
                        err = res.text[:80]
                    print(f"[METAAPI CANDLE] {res.status_code} from {host}: {err}")
            except Exception as e:
                print(f"[METAAPI CANDLE ERROR] {host}: {e}")
                continue

        return []

    # --- TECHNICAL INDICATORS FROM METAAPI CANDLES ---

    def _calc_indicators(self):
        """
        XAUUSD Indicator Engine.
        Prioritas:
        1. Candle 5m dari MetaAPI (paling akurat)
        2. Candle 1m dari MetaAPI
        3. Price momentum dari harga live MetaAPI (fallback)
        Tidak pakai proxy atau data dari exchange lain.
        """
        candles = self.get_candles(timeframe="5m", limit=100)

        # Level 2: Coba candle 1m kalau 5m gagal
        if len(candles) < 20:
            candles = self.get_candles(timeframe="1m", limit=50)

        # Level 3: Fallback — tidak ada candle tersedia
        # Gunakan price momentum dari harga live MetaAPI
        # (TIDAK pakai PAXG atau proxy lain — data harus dari MetaAPI)
        if len(candles) < 10:
            price_data = self.get_live_price()
            price = price_data.get("mid", 0)
            if price == 0:
                return {}

            # Simpan history harga live untuk deteksi momentum
            if not hasattr(self, '_price_history'):
                self._price_history = []
            self._price_history.append(price)
            if len(self._price_history) > 20:
                self._price_history.pop(0)

            trend      = "NEUTRAL"
            rsi_approx = 50.0
            liq_sweep  = False
            choch_bull = False
            choch_bear = False

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

            print(f"[FOREX FALLBACK] MetaAPI candle unavailable. Using price momentum. RSI~{rsi_approx} Trend:{trend}")
            return {
                "rsi": rsi_approx, "ema200": price, "atr": price * 0.001,
                "vwap": price, "vwap_dist": 0.0, "trend": trend,
                "mss_bullish": trend == "BULLISH" and liq_sweep,
                "mss_bearish": trend == "BEARISH" and liq_sweep,
                "choch_bullish": choch_bull, "choch_bearish": choch_bear,
                "fvg": "NONE", "is_liquidity_sweep": liq_sweep,
                "last_close": price, "vol_spike": False,
                "rsi_divergence": "NONE", "pump_signal": "NONE",
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
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i]  - closes[i-1]))
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

        # FVG
        fvg = "NONE"
        if len(candles) >= 3:
            if highs[-3] < lows[-1]:  fvg = "BULLISH_FVG"
            elif lows[-3] > highs[-1]: fvg = "BEARISH_FVG"

        # Liquidity Sweep
        liq_sweep = (lows[-1] < lows[-2] and closes[-1] > lows[-2]) or \
                    (highs[-1] > highs[-2] and closes[-1] < highs[-2])

        # Trend
        trend = "NEUTRAL"
        if last_close > ema200: trend = "BULLISH"
        elif last_close < ema200: trend = "BEARISH"

        # ── PUMP SIGNALS KHUSUS XAUUSD ────────────────────────────────────────

        # Volume Spike: candle terakhir > 2x rata-rata
        vol_spike = last_vol > avg_vol * 2.0

        # RSI Divergence: harga buat lower low tapi RSI buat higher low = bullish divergence
        rsi_divergence = "NONE"
        if len(rsi_history) >= 5 and len(closes) >= 5:
            price_lower_low = closes[-1] < min(closes[-5:-1])
            rsi_higher_low  = rsi > min(rsi_history[-5:]) if rsi_history else False
            if price_lower_low and rsi_higher_low:
                rsi_divergence = "BULLISH_DIVERGENCE"  # Pump signal kuat

            price_higher_high = closes[-1] > max(closes[-5:-1])
            rsi_lower_high    = rsi < max(rsi_history[-5:]) if rsi_history else False
            if price_higher_high and rsi_lower_high:
                rsi_divergence = "BEARISH_DIVERGENCE"  # Dump signal kuat

        # Pump Signal Summary
        pump_signal = "NONE"
        if rsi_divergence == "BULLISH_DIVERGENCE" or (liq_sweep and fvg == "BULLISH_FVG"):
            pump_signal = "PUMP_IMMINENT"
        elif rsi_divergence == "BEARISH_DIVERGENCE" or (liq_sweep and fvg == "BEARISH_FVG"):
            pump_signal = "DUMP_IMMINENT"
        elif mss_bull and vol_spike:
            pump_signal = "BREAKOUT_UP"
        elif mss_bear and vol_spike:
            pump_signal = "BREAKOUT_DOWN"

        return {
            "rsi":              round(rsi, 2),
            "ema200":           round(ema200, 3),
            "atr":              round(atr, 3),
            "vwap":             round(vwap, 3),
            "vwap_dist":        round(vwap_dist, 4),
            "trend":            trend,
            "mss_bullish":      mss_bull,
            "mss_bearish":      mss_bear,
            "choch_bullish":    choch_bull,
            "choch_bearish":    choch_bear,
            "fvg":              fvg,
            "is_liquidity_sweep": liq_sweep,
            "last_close":       last_close,
            "vol_spike":        vol_spike,
            "rsi_divergence":   rsi_divergence,
            "pump_signal":      pump_signal,
        }

    # --- MOMENTUM SCORING ---

    def _score_setup(self, ind, side, spread_points):
        """
        XAUUSD Pump Predictor Score 0-100.
        Prioritas: pump_signal > rsi_divergence > MSS > FVG > RSI > VWAP
        """
        score     = 0
        rsi       = ind.get("rsi", 50)
        vwap_dist = ind.get("vwap_dist", 0)
        fvg       = ind.get("fvg", "NONE")
        mss_b     = ind.get("mss_bullish", False)
        mss_s     = ind.get("mss_bearish", False)
        choch_b   = ind.get("choch_bullish", False)
        choch_s   = ind.get("choch_bearish", False)
        liq       = ind.get("is_liquidity_sweep", False)
        trend     = ind.get("trend", "NEUTRAL")
        vol_spike = ind.get("vol_spike", False)
        rsi_div   = ind.get("rsi_divergence", "NONE")
        pump_sig  = ind.get("pump_signal", "NONE")

        # ── PUMP SIGNAL (max 35 poin) — sinyal terkuat ───────────────────────
        if side == "buy":
            if pump_sig == "PUMP_IMMINENT":  score += 35
            elif pump_sig == "BREAKOUT_UP":  score += 25
            if rsi_div == "BULLISH_DIVERGENCE": score += 20
        else:
            if pump_sig == "DUMP_IMMINENT":   score += 35
            elif pump_sig == "BREAKOUT_DOWN": score += 25
            if rsi_div == "BEARISH_DIVERGENCE": score += 20

        # ── Volume Spike (max 15 poin) ────────────────────────────────────────
        if vol_spike: score += 15

        # ── RSI Zone (max 15 poin) ────────────────────────────────────────────
        if side == "buy":
            if 30 <= rsi <= 50:   score += 15
            elif 50 < rsi <= 60:  score += 8
            elif rsi > 70:        score -= 10
        else:
            if 50 <= rsi <= 70:   score += 15
            elif 40 <= rsi < 50:  score += 8
            elif rsi < 30:        score -= 10

        # ── FVG (max 10 poin) ─────────────────────────────────────────────────
        if side == "buy"  and fvg == "BULLISH_FVG": score += 10
        if side == "sell" and fvg == "BEARISH_FVG": score += 10

        # ── MSS / CHoCH (max 10 poin) ─────────────────────────────────────────
        if side == "buy"  and (mss_b or choch_b): score += 10
        if side == "sell" and (mss_s or choch_s): score += 10

        # ── Liquidity Sweep (max 5 poin) ──────────────────────────────────────
        if liq: score += 5

        # ── Trend alignment (max 5 poin) ──────────────────────────────────────
        if side == "buy"  and trend == "BULLISH": score += 5
        if side == "sell" and trend == "BEARISH": score += 5
        if side == "buy"  and trend == "BEARISH": score -= 8   # Lebih besar penaltinya
        if side == "sell" and trend == "BULLISH": score -= 8

        # ── Spread penalty ────────────────────────────────────────────────────
        if spread_points > 100: score -= 10
        if spread_points > 150: score -= 20

        # ── Session bonus: London/NY open lebih volatile ──────────────────────
        now_utc = datetime.datetime.utcnow()
        hour = now_utc.hour
        # London open (07-09 UTC) dan NY open (13-15 UTC) = paling volatile
        if (7 <= hour <= 9) or (13 <= hour <= 15):
            score += 8   # Bonus sesi paling aktif

        return max(0, min(100, score))

    def _determine_side(self, ind, spread_points):
        """
        Return (side, score, trades_to_open) atau (None, 0, 0).
        Max 5 trade. TP fixed dari entry, tidak berubah.
        """
        buy_score  = self._score_setup(ind, "buy",  spread_points)
        sell_score = self._score_setup(ind, "sell", spread_points)

        trend    = ind.get("trend", "NEUTRAL")
        pump_sig = ind.get("pump_signal", "NONE")
        rsi      = ind.get("rsi", 50)
        choch_b  = ind.get("choch_bullish", False)
        choch_s  = ind.get("choch_bearish", False)

        best_score = 0
        best_side  = None

        if buy_score >= sell_score and buy_score >= MIN_MOMENTUM_SCORE:
            best_side, best_score = "buy", buy_score
        elif sell_score > buy_score and sell_score >= MIN_MOMENTUM_SCORE:
            best_side, best_score = "sell", sell_score

        if best_side is None:
            return None, 0, 0

        # Skip kalau pure neutral (tidak ada sinyal sama sekali)
        if rsi == 50.0 and trend == "NEUTRAL" and pump_sig == "NONE" and not choch_b and not choch_s:
            return None, 0, 0

        # Jumlah trade berdasarkan confidence (max MAX_TRADES_PER_SIGNAL)
        # Tapi tidak boleh melebihi slot yang tersedia
        if best_score >= 80:   trades = MAX_TRADES_PER_SIGNAL
        elif best_score >= 65: trades = min(2, MAX_TRADES_PER_SIGNAL)
        elif best_score >= 50: trades = min(2, MAX_TRADES_PER_SIGNAL)
        else:                  trades = 1

        return best_side, best_score, trades

    # --- TP/SL & LOT SIZING ---

    def _calc_tp_sl(self, price, side, atr):
        """
        TP/SL yang masuk akal untuk XAUUSD.
        
        Logika:
        - SL harus > spread (2.8 pts) + noise (ATR) → minimum 7 poin
        - TP harus 2x SL minimum → 20 poin
        - ATR dipakai untuk menyesuaikan, tapi tidak boleh kurang dari minimum
        
        Contoh dengan ATR=4.5:
        - SL = max(4.5 × 1.5, 8.0) = max(6.75, 8.0) = 8.0 poin (80 pip)
        - TP = max(4.5 × 4.0, 20.0) = max(18.0, 20.0) = 20.0 poin (200 pip)
        - RR = 1:2.5
        """
        if atr and 1.0 <= atr <= 15:
            sl_dist = max(atr * 1.5, SCALP_SL_POINTS)
            tp_dist = max(atr * 4.0, SCALP_TP_POINTS)
        else:
            sl_dist = SCALP_SL_POINTS
            tp_dist = SCALP_TP_POINTS

        # Hard minimum: SL tidak boleh kurang dari 7 poin (spread + noise)
        sl_dist = max(sl_dist, 7.0)
        # Hard minimum: TP tidak boleh kurang dari 15 poin
        tp_dist = max(tp_dist, 15.0)
        # Cap maksimum
        sl_dist = min(sl_dist, 12.0)   # Max 120 pip SL
        tp_dist = min(tp_dist, 30.0)   # Max 300 pip TP

        if side == "buy":
            return round(price + tp_dist, 3), round(price - sl_dist, 3)
        else:
            return round(price - tp_dist, 3), round(price + sl_dist, 3)

    def _calc_lot_size(self, balance, risk_pct=RISK_PCT_PER_TRADE):
        """
        Lot sizing untuk cent account dengan SL 8 poin.
        
        Cent account: 1 lot = $1/pip, 0.01 lot = $0.01/pip
        SL 8 poin = 80 pip
        Risk per 0.01 lot = 80 × $0.01 = $0.80
        
        Dengan balance $515 dan risk 1%:
        risk_amount = $5.15
        lot = 5.15 / 0.80 = 0.06 → capped di MAX_LOT_PER_TRADE (0.01)
        
        Pakai MAX_LOT_PER_TRADE = 0.01 untuk kontrol ketat.
        """
        return MAX_LOT_PER_TRADE  # Fixed 0.01 lot per trade untuk cent account
        return lot

    def _is_trading_session(self):
        """
        XAUUSD aktif hampir 24 jam kecuali Jumat malam - Minggu malam.
        Buka semua session: Asia + London + NY.
        Tutup hanya saat weekend (Sabtu-Minggu UTC).
        """
        now_utc = datetime.datetime.utcnow()
        weekday = now_utc.weekday()  # 0=Senin, 5=Sabtu, 6=Minggu
        # Tutup saat weekend
        if weekday == 6:  # Minggu
            return False
        if weekday == 5 and now_utc.hour >= 21:  # Sabtu malam
            return False
        return True  # Semua jam lain = buka

    # --- POSITIONS ---

    def _get_positions(self):
        if not self.is_active: return []
        try:
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/positions"
            headers = {"auth-token": self.api_token}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return data if isinstance(data, list) else []
        except Exception:
            pass
        return []

    # --- ORDER EXECUTION ---

    def place_forex_order(self, symbol, side, amount, tp=None, sl=None):
        if not self.is_active: return False, "Forex not active"
        try:
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/trade"
            headers = {"auth-token": self.api_token, "Content-Type": "application/json"}
            payload = {
                "symbol":     symbol,
                "actionType": "ORDER_TYPE_BUY" if side.lower() == "buy" else "ORDER_TYPE_SELL",
                "volume":     amount,
                "comment":    "SuperGenius SMC v3.0",
            }
            if sl: payload["stopLoss"]   = sl
            if tp: payload["takeProfit"] = tp
            res    = requests.post(url, headers=headers, json=payload, timeout=10)
            result = res.json()
            if res.status_code == 200:
                print(f"[FOREX SUCCESS] {side.upper()} {symbol} lot={amount} TP={tp} SL={sl}")
                return True, result
            else:
                msg = result.get("message", str(result))
                print(f"[FOREX FAILED] {symbol}: {msg}")
                return False, msg
        except Exception as e:
            print(f"[FOREX API CRASH] {e}")
            return False, str(e)

    def place_xauusd_scalp_batch(self, side, trades_count=3, volume=0.01, tp=None, sl=None):
        """
        Dipakai oleh news_sniper.py dan main.py untuk eksekusi cepat.
        tp/sl opsional — kalau tidak diberikan, dihitung otomatis dari ATR.
        """
        sym = self._working_symbol or self._resolve_symbol("XAUUSD")
        price_data = self.get_live_price(sym)
        price = price_data["bid"] if side == "sell" else price_data["ask"]
        if price == 0:
            print("[SCALP BATCH] Cannot get price, aborting.")
            return False
        # Hitung TP/SL otomatis kalau tidak diberikan
        if tp is None or sl is None or tp == 0 or sl == 0:
            atr = 1.5
            tp, sl = self._calc_tp_sl(price, side, atr)
        print(f"[SCALP BATCH] Firing {trades_count}x {side.upper()} {sym} @ {price} | TP={tp} SL={sl}")
        any_success = False
        for i in range(trades_count):
            success, _ = self.place_forex_order(sym, side, volume, tp=tp, sl=sl)
            if success:
                from database import log_trade
                log_trade(sym, price, tp, sl, market="forex")
                any_success = True
            time.sleep(0.1)
        return any_success

    def update_forex_sl(self, position_id, new_sl, new_tp=None):
        """
        Update SL posisi via MetaAPI POSITION_MODIFY.
        TP TIDAK diubah — TP fixed dari entry dan tidak boleh berubah.
        new_tp parameter diabaikan untuk menjaga TP tetap.
        """
        if not self.is_active: return False
        try:
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/trade"
            headers = {"auth-token": self.api_token, "Content-Type": "application/json"}
            payload = {
                "actionType": "POSITION_MODIFY",
                "positionId": str(position_id),
                "stopLoss":   new_sl,
                # takeProfit TIDAK dimasukkan — biarkan TP tetap seperti saat entry
            }
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code == 200:
                return True
            else:
                try:
                    err = res.json().get("message", res.text[:100])
                except Exception:
                    err = res.text[:100]
                print(f"[UPDATE SL FAIL] pos={position_id} sl={new_sl} status={res.status_code}: {err}")
                return False
        except Exception as e:
            print(f"[UPDATE SL ERROR] pos={position_id}: {e}")
            return False

    # --- TRAILING STOP ---
    # --- TRAILING STOP ---
    # --- TRAILING STOP + DIRECTION CONFLICT ---

    def _trail_positions(self, positions):
        """
        1. Direction conflict: tidak boleh ada BUY dan SELL bersamaan.
           Kalau ada, tutup sisi yang lebih kecil profitnya.
        2. Trailing SL: SL selalu naik (buy) atau turun (sell).
           Formula: SL = entry + (profit_pt - buffer)
           Buffer = 5 poin. Setiap profit naik, SL ikut naik.
        """
        if not hasattr(self, "_close_attempted"):
            self._close_attempted = set()
        if not hasattr(self, "_conflict_cooldown"):
            self._conflict_cooldown = 0

        # DIRECTION CONFLICT CHECK
        xau_buys  = [p for p in positions if "XAU" in p.get("symbol","").upper()
                     and p.get("type") == "POSITION_TYPE_BUY"]
        xau_sells = [p for p in positions if "XAU" in p.get("symbol","").upper()
                     and p.get("type") == "POSITION_TYPE_SELL"]

        if xau_buys and xau_sells:
            buy_profit  = sum(float(p.get("profit", 0)) for p in xau_buys)
            sell_profit = sum(float(p.get("profit", 0)) for p in xau_sells)
            to_close = xau_sells if buy_profit >= sell_profit else xau_buys
            direction = "SELL" if buy_profit >= sell_profit else "BUY"
            print(f"[FOREX CONFLICT] BUY=${buy_profit:.2f} vs SELL=${sell_profit:.2f}. Closing {direction}.")
            for p in to_close:
                pos_id = p.get("id")
                if pos_id not in self._close_attempted:
                    self._close_attempted.add(pos_id)
                    try:
                        url = f"{self.base_url}/users/current/accounts/{self.account_id}/trade"
                        headers = {"auth-token": self.api_token, "Content-Type": "application/json"}
                        res = requests.post(url, headers=headers,
                            json={"actionType": "POSITION_CLOSE_ID", "positionId": pos_id}, timeout=8)
                        if res.status_code == 200:
                            print(f"[FOREX CONFLICT CLOSE] {pos_id} closed")
                        else:
                            self._close_attempted.discard(pos_id)
                    except Exception as e:
                        self._close_attempted.discard(pos_id)
            # Cooldown 10 menit setelah conflict — jangan langsung buka arah baru
            self._conflict_cooldown = time.time()
            print(f"[FOREX CONFLICT] Cooldown {COOLDOWN_AFTER_CONFLICT}s. Tidak entry baru dulu.")

        # TRAILING SL
        for p in positions:
            if "XAU" not in p.get("symbol", "").upper(): continue
            open_price = float(p.get("openPrice", 0))
            pos_id     = p.get("id")
            pos_type   = p.get("type", "")
            profit     = float(p.get("profit", 0))
            current_sl = float(p.get("stopLoss", 0))
            sym        = p.get("symbol", self._working_symbol or "XAUUSDc")
            if open_price == 0: continue

            is_buy = pos_type == "POSITION_TYPE_BUY"

            # Hitung profit_pt dari currentPrice (di-inject dari broker_price)
            # BUY: profit kalau current > open → profit_pt = current - open
            # SELL: profit kalau current < open → profit_pt = open - current
            current_price = float(p.get("currentPrice", 0))
            if current_price > 0 and current_price != open_price:
                profit_pt = (current_price - open_price) if is_buy else (open_price - current_price)
            else:
                profit_pt = 0

            direction = "BUY" if is_buy else "SELL"
            print(f"[TRAIL DEBUG] {sym} {direction} open={open_price} current={current_price} profit=${profit} profit_pt={round(profit_pt,2)} sl={current_sl}")

            # AUTO-CLOSE: rugi > $7 (safety net kalau SL tidak terpasang)
            if profit < -7.0 and pos_id not in self._close_attempted:
                self._close_attempted.add(pos_id)
                print(f"[FOREX AUTO-CLOSE] {pos_id} loss . Closing.")
                try:
                    url = f"{self.base_url}/users/current/accounts/{self.account_id}/trade"
                    headers = {"auth-token": self.api_token, "Content-Type": "application/json"}
                    res = requests.post(url, headers=headers,
                        json={"actionType": "POSITION_CLOSE_ID", "positionId": pos_id}, timeout=8)
                    if res.status_code == 200:
                        print(f"[FOREX AUTO-CLOSE] {pos_id} closed")
                    else:
                        self._close_attempted.discard(pos_id)
                except Exception as e:
                    self._close_attempted.discard(pos_id)
                continue

            # TRAILING SL: SL = entry + (profit_pt - buffer)
            # Buffer = 5 poin. SL hanya naik, tidak pernah turun.
            # Contoh: entry=4580, profit_pt=12 -> SL = 4580 + (12-5) = 4587
            if profit_pt < 5.0:
                if profit_pt > 0:
                    print(f"[FOREX TRAIL] {sym} profit_pt={round(profit_pt,2)} < 5.0, waiting...")
                continue

            buffer = 5.0
            if is_buy:
                new_sl = round(open_price + (profit_pt - buffer), 3)
                print(f"[TRAIL ATTEMPT] {sym} BUY trying SL {current_sl} -> {new_sl} (profit_pt={round(profit_pt,1)})")
                if current_sl == 0 or new_sl > current_sl:
                    ok = self.update_forex_sl(pos_id, new_sl)
                    if ok:
                        print(f"✅ [FOREX TRAIL] {sym} SL {current_sl} -> {new_sl} (+{round(profit_pt,1)}pt)")
                    else:
                        print(f"❌ [FOREX TRAIL FAIL] {sym} could not update SL to {new_sl}")
                else:
                    print(f"[TRAIL SKIP] {sym} new_sl={new_sl} not better than current_sl={current_sl}")
            else:
                new_sl = round(open_price - (profit_pt - buffer), 3)
                print(f"[TRAIL ATTEMPT] {sym} SELL trying SL {current_sl} -> {new_sl} (profit_pt={round(profit_pt,1)})")
                if current_sl == 0 or new_sl < current_sl:
                    ok = self.update_forex_sl(pos_id, new_sl)
                    if ok:
                        print(f"✅ [FOREX TRAIL] {sym} SL {current_sl} -> {new_sl} (+{round(profit_pt,1)}pt)")
                    else:
                        print(f"❌ [FOREX TRAIL FAIL] {sym} could not update SL to {new_sl}")
                else:
                    print(f"[TRAIL SKIP] {sym} new_sl={new_sl} not better than current_sl={current_sl}")

    # --- MAIN ENGINE LOOP ---

    def monitor_forex_market(self):
        """
        [FOREX ENGINE v3.0] Super Genius XAUUSD Scalper.
        Semua data dari MetaAPI langsung. Tidak ada proxy.
        """
        print("[FOREX ENGINE v4.0] Small Capital Aggressive XAUUSD Scalper AKTIF!")
        print(f"  Sessions: Asia(02-06) + London(07-16) + NY(12-21) UTC")
        print(f"  TP: {SCALP_TP_POINTS} pts | SL: {SCALP_SL_POINTS} pts | Risk: {int(RISK_PCT_PER_TRADE*100)}%/trade")
        last_auto_trade = 0

        while True:
            try:
                if not self.is_active:
                    time.sleep(60)
                    continue

                # SESSION FILTER
                if not self._is_trading_session():
                    print("[FOREX SESSION] Outside London/NY session. Waiting 5 min...")
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

                # LIVE PRICE — simpan cache, jangan skip trailing kalau timeout
                price_data   = self.get_live_price()
                broker_price = price_data["mid"]
                spread_pts   = price_data["spread_points"]

                # Cache harga terakhir yang berhasil
                if broker_price > 0:
                    self._last_known_price = broker_price
                    self._last_known_spread = spread_pts
                else:
                    # Pakai cache kalau timeout
                    broker_price = getattr(self, '_last_known_price', 0)
                    spread_pts   = getattr(self, '_last_known_spread', 999)

                # POSITIONS — selalu ambil, tidak bergantung pada harga
                positions    = self._get_positions()
                active_count = len(positions)
                total_lots   = sum(float(p.get("volume", 0)) for p in positions)

                if broker_price > 0:
                    print(f"[FOREX DASHBOARD] Price: {broker_price} | Trades: {active_count} | Lots: {round(total_lots, 2)} | Spread: {spread_pts}pts")

                # TRAILING STOP — selalu jalan, inject harga ke posisi
                # Tidak boleh di-skip karena timeout harga
                if broker_price > 0 and positions:
                    for p in positions:
                        if "XAU" in p.get("symbol", "").upper():
                            p["currentPrice"] = broker_price
                    self._trail_positions(positions)

                # Kalau tidak ada harga sama sekali, skip entry tapi trailing sudah jalan
                if broker_price == 0:
                    time.sleep(5)
                    continue

                # SPREAD FILTER
                if spread_pts > MAX_SPREAD_POINTS:
                    print(f"[SPREAD GUARD] Spread {spread_pts}pts too wide. Skipping.")
                    time.sleep(SCAN_INTERVAL)
                    continue

                # COOLDOWN
                now = time.time()
                cooldown_remaining = COOLDOWN_AFTER_TRADE - (now - last_auto_trade)
                if cooldown_remaining > 0:
                    if int(now) % 30 < 3:
                        print(f"[FOREX COOLDOWN] {round(cooldown_remaining)}s remaining")
                    time.sleep(SCAN_INTERVAL)
                    continue

                # CONFLICT COOLDOWN — tunggu 10 menit setelah direction conflict
                conflict_remaining = COOLDOWN_AFTER_CONFLICT - (now - getattr(self, '_conflict_cooldown', 0))
                if conflict_remaining > 0:
                    if int(now) % 60 < 3:
                        print(f"[FOREX CONFLICT COOLDOWN] {round(conflict_remaining)}s remaining after conflict")
                    time.sleep(SCAN_INTERVAL)
                    continue

                # POSITION QUALITY CHECK
                # 1. Jangan buka trade baru kalau ada posisi yang masih rugi
                # 2. Hard cap: max 3 posisi XAU aktif sekaligus
                xau_positions = [p for p in positions if "XAU" in p.get("symbol", "").upper()]
                if xau_positions:
                    # Hard cap 3 posisi
                    if len(xau_positions) >= 3:
                        if int(now) % 60 < 3:
                            print(f"[FOREX QUALITY] Sudah {len(xau_positions)} posisi aktif (max 3). Skip.")
                        time.sleep(SCAN_INTERVAL)
                        continue
                    # Jangan tambah kalau ada yang rugi
                    losing = [p for p in xau_positions if float(p.get("profit", 0)) < -0.5]
                    if losing:
                        if int(now) % 30 < 3:
                            print(f"[FOREX QUALITY] {len(losing)} posisi rugi. Tunggu dulu.")
                        time.sleep(SCAN_INTERVAL)
                        continue

                # CALCULATE INDICATORS (with fallback if candles unavailable)
                print(f"[FOREX SCAN] Calculating indicators for {self._working_symbol}...")
                ind = self._calc_indicators()
                if not ind:
                    print(f"[FOREX SCAN] No indicators available (price=0?). Retrying...")
                    time.sleep(5)
                    continue

                rsi_val  = ind.get("rsi", 0)
                trend    = ind.get("trend", "NEUTRAL")
                pump_sig = ind.get("pump_signal", "NONE")
                print(f"[FOREX SCAN] RSI:{rsi_val} Trend:{trend} Pump:{pump_sig} | Slots:{MAX_POSITIONS - active_count}")

                # DETERMINE SIDE + CONFIDENCE
                side, score, trades_to_open = self._determine_side(ind, spread_pts)
                if side is None:
                    buy_sc  = self._score_setup(ind, "buy",  spread_pts)
                    sell_sc = self._score_setup(ind, "sell", spread_pts)
                    print(f"[FOREX SCAN] No setup. BuyScore:{buy_sc} SellScore:{sell_sc} (need {MIN_MOMENTUM_SCORE}+)")
                    time.sleep(SCAN_INTERVAL)
                    continue

                # POSITION LIMIT — hard cap 3 posisi XAU aktif
                xau_active = len([p for p in positions if "XAU" in p.get("symbol", "").upper()])
                slots_available = max(0, 3 - xau_active)  # Max 3 posisi XAU
                trades_to_open  = min(trades_to_open, slots_available)
                if trades_to_open <= 0:
                    time.sleep(SCAN_INTERVAL)
                    continue

                # CALCULATE TP/SL
                entry_price = price_data["ask"] if side == "buy" else price_data["bid"]
                atr         = ind.get("atr", 1.5)
                tp, sl      = self._calc_tp_sl(entry_price, side, atr)

                # LOT SIZE
                lot = self._calc_lot_size(balance)

                # EXECUTE — buka sejumlah trades_to_open
                sym      = self._working_symbol or "XAUUSD"
                rsi_val  = ind.get("rsi", 0)
                vwap_val = ind.get("vwap_dist", 0)
                trend    = ind.get("trend", "NEUTRAL")
                fvg_val  = ind.get("fvg", "NONE")
                pump_sig = ind.get("pump_signal", "NONE")
                rsi_div  = ind.get("rsi_divergence", "NONE")
                print("")
                print("=" * 60)
                print(f"[FOREX SCALPER] XAUUSD {side.upper()} x{trades_to_open} | Score: {score}/100")
                print(f"  Pump Signal : {pump_sig} | RSI Div: {rsi_div}")
                print(f"  Price  : {entry_price} | ATR: {atr}")
                print(f"  RSI    : {rsi_val} | VWAP Dist: {vwap_val}%")
                print(f"  Trend  : {trend} | FVG: {fvg_val}")
                print(f"  TP     : {tp} | SL: {sl} | Lot: {lot} each")
                print("=" * 60)

                opened = 0
                for _ in range(trades_to_open):
                    success, _ = self.place_forex_order(sym, side, lot, tp=tp, sl=sl)
                    if success:
                        from database import log_trade
                        log_trade(sym, entry_price, tp, sl, market="forex")
                        opened += 1
                    time.sleep(0.15)

                if opened > 0:
                    print(f"[FOREX] Opened {opened}/{trades_to_open} trades successfully")
                    last_auto_trade = time.time()

                time.sleep(SCAN_INTERVAL)

            except Exception as e:
                print(f"[FOREX ENGINE ERROR] {e}")
                time.sleep(5)
