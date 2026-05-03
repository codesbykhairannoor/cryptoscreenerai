"""
FOREX SCALPER v4.0 - SMALL CAPITAL AGGRESSIVE EDITION (MetaAPI Native)
=======================================================================
Optimized untuk modal kecil (cent account / micro account).

Perubahan dari v3.0:
- COOLDOWN_AFTER_TRADE: 60s → 30s  (lebih sering entry)
- MIN_MOMENTUM_SCORE: 50 → 40  (lebih berani)
- MAX_SPREAD_POINTS: 200 → 300  (toleransi spread lebih longgar)
- TP/SL: Scalp ratio 1:1.5 (TP 1.5 poin, SL 1 poin = 15 pip TP, 10 pip SL)
- Lot sizing: 2% risk per trade (lebih agresif dari 1%)
- Session: Tambah Asia session untuk XAUUSD (02:00-06:00 UTC)
- Trailing: Breakeven lebih cepat di +5 pip (bukan +10 pip)
"""

import requests
import os
import time
import datetime
from dotenv import load_dotenv

load_dotenv()

MAX_POSITIONS        = 3      # Max 3 posisi XAUUSD (fokus modal kecil)
SCAN_INTERVAL        = 3      # Scan setiap 3 detik
COOLDOWN_AFTER_TRADE = 30     # Cooldown 30 detik (lebih agresif)
EQUITY_GUARD_PCT     = 0.92   # Halt kalau equity < 92% (sedikit lebih toleran)
MAX_SPREAD_POINTS    = 300    # Toleransi spread lebih longgar untuk scalping
MIN_MOMENTUM_SCORE   = 40     # Threshold lebih rendah = lebih berani
CANDLE_LIMIT         = 100

# Scalp TP/SL untuk XAUUSD (dalam poin, 1 poin = 10 pip)
SCALP_TP_POINTS      = 1.5    # TP 15 pip
SCALP_SL_POINTS      = 1.0    # SL 10 pip (1:1.5 RR)
RISK_PCT_PER_TRADE   = 0.02   # 2% risk per trade (agresif untuk modal kecil)


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
        """Ambil candle historis dari MetaAPI langsung."""
        sym = symbol or self._working_symbol or "XAUUSD"
        try:
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/historical-market-data/{sym}/{timeframe}/candles?limit={limit}"
            headers = {"auth-token": self.api_token}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                candles = res.json()
                if isinstance(candles, list) and len(candles) > 0:
                    return candles
        except Exception as e:
            print(f"[FOREX CANDLE ERROR] {e}")
        return []

    # --- TECHNICAL INDICATORS FROM METAAPI CANDLES ---

    def _calc_indicators(self):
        """
        Hitung semua indikator teknikal dari candle MetaAPI 5m.
        RSI, EMA200, ATR, VWAP, MSS, CHoCH, FVG, Liquidity Sweep.
        """
        candles = self.get_candles(timeframe="5m", limit=100)
        if len(candles) < 20:
            return {}

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

        # Market Structure (MSS / CHoCH)
        last_close  = closes[-1]
        recent_high = max(highs[-10:-1])
        recent_low  = min(lows[-10:-1])
        avg_vol     = sum(vols[-20:]) / 20 if len(vols) >= 20 else 1
        last_vol    = vols[-1]

        choch_bull = last_close > recent_high
        choch_bear = last_close < recent_low
        mss_bull   = choch_bull and last_vol > avg_vol * 1.5
        mss_bear   = choch_bear and last_vol > avg_vol * 1.5

        # FVG (Fair Value Gap)
        fvg = "NONE"
        if len(candles) >= 3:
            c1h = highs[-3]
            c3l = lows[-1]
            c1l = lows[-3]
            c3h = highs[-1]
            if c1h < c3l: fvg = "BULLISH_FVG"
            elif c1l > c3h: fvg = "BEARISH_FVG"

        # Liquidity Sweep
        liq_sweep = (lows[-1] < lows[-2] and closes[-1] > lows[-2]) or \
                    (highs[-1] > highs[-2] and closes[-1] < highs[-2])

        # Trend
        trend = "NEUTRAL"
        if last_close > ema200: trend = "BULLISH"
        elif last_close < ema200: trend = "BEARISH"

        vwap_dist = ((last_close - vwap) / vwap * 100) if vwap > 0 else 0

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
        }

    # --- MOMENTUM SCORING ---

    def _score_setup(self, ind, side, spread_points):
        """Hitung momentum score 0-100 untuk setup XAUUSD."""
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

        # RSI (max 25 poin)
        if side == "buy":
            if 30 <= rsi <= 50:   score += 25
            elif 50 < rsi <= 60:  score += 15
            elif rsi < 30:        score += 8
            elif rsi > 70:        score -= 15
        else:
            if 50 <= rsi <= 70:   score += 25
            elif 40 <= rsi < 50:  score += 15
            elif rsi > 80:        score += 8
            elif rsi < 30:        score -= 15

        # VWAP Distance (max 20 poin)
        if side == "buy":
            if -3.0 <= vwap_dist <= -0.3: score += 20
            elif -0.3 < vwap_dist <= 0.5: score += 10
            elif vwap_dist > 3.0:         score -= 10
        else:
            if 0.3 <= vwap_dist <= 3.0:   score += 20
            elif -0.5 <= vwap_dist < 0.3: score += 10
            elif vwap_dist < -3.0:        score -= 10

        # FVG (max 15 poin)
        if side == "buy"  and fvg == "BULLISH_FVG": score += 15
        if side == "sell" and fvg == "BEARISH_FVG": score += 15

        # MSS / CHoCH (max 20 poin)
        if side == "buy"  and mss_b:    score += 20
        if side == "sell" and mss_s:    score += 20
        if side == "buy"  and choch_b:  score += 10
        if side == "sell" and choch_s:  score += 10

        # Liquidity Sweep (max 10 poin)
        if liq: score += 10

        # Trend alignment (max 10 poin)
        if side == "buy"  and trend == "BULLISH": score += 10
        if side == "sell" and trend == "BEARISH": score += 10
        if side == "buy"  and trend == "BEARISH": score -= 5
        if side == "sell" and trend == "BULLISH": score -= 5

        # Spread penalty
        if spread_points > 100: score -= 10
        if spread_points > 150: score -= 20

        return max(0, min(100, score))

    def _determine_side(self, ind, spread_points):
        """Return (side, score) atau (None, 0) kalau tidak ada setup."""
        buy_score  = self._score_setup(ind, "buy",  spread_points)
        sell_score = self._score_setup(ind, "sell", spread_points)
        if buy_score >= sell_score and buy_score >= MIN_MOMENTUM_SCORE:
            return "buy",  buy_score
        if sell_score > buy_score and sell_score >= MIN_MOMENTUM_SCORE:
            return "sell", sell_score
        return None, 0

    # --- TP/SL & LOT SIZING ---

    def _calc_tp_sl(self, price, side, atr):
        """
        Scalp TP/SL untuk modal kecil.
        Fixed: TP 15 pip, SL 10 pip (1:1.5 RR).
        ATR dipakai kalau lebih kecil dari fixed (market tenang = target lebih kecil).
        """
        # Gunakan yang lebih kecil antara ATR-based dan fixed scalp target
        atr_tp = atr * 2.0 if atr > 0 else SCALP_TP_POINTS
        atr_sl = atr * 1.0 if atr > 0 else SCALP_SL_POINTS
        tp_dist = min(atr_tp, SCALP_TP_POINTS * 2)  # Cap max TP
        sl_dist = min(atr_sl, SCALP_SL_POINTS * 1.5)  # Cap max SL
        # Minimum scalp target
        tp_dist = max(tp_dist, SCALP_TP_POINTS)
        sl_dist = max(sl_dist, SCALP_SL_POINTS)
        if side == "buy":
            return round(price + tp_dist, 3), round(price - sl_dist, 3)
        else:
            return round(price - tp_dist, 3), round(price + sl_dist, 3)

    def _calc_lot_size(self, balance, risk_pct=RISK_PCT_PER_TRADE):
        """
        2% risk per trade untuk modal kecil.
        Cent account: balance dalam cents, lot minimum 0.01.
        """
        risk_amount = balance * risk_pct
        # XAUUSD: $1 per pip per 0.01 lot (standard), atau $0.01 per pip (cent account)
        # Asumsi cent account: 1 lot = $0.10/pip, SL = 10 pip = $1 per 0.01 lot
        lot = round(max(0.01, min(risk_amount / 100, 1.0)), 2)
        return lot

    def _is_trading_session(self):
        """
        Trade saat London (07-16 UTC), NY (12-21 UTC), DAN Asia (02-06 UTC).
        Asia session bagus untuk XAUUSD karena ada volatilitas dari China/India.
        """
        now_utc = datetime.datetime.utcnow()
        hour = now_utc.hour
        return (2 <= hour < 6) or (7 <= hour < 16) or (12 <= hour < 21)

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

    def update_forex_sl(self, position_id, new_sl):
        if not self.is_active: return False
        try:
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/positions/{position_id}"
            headers = {"auth-token": self.api_token, "Content-Type": "application/json"}
            payload = {"stopLoss": new_sl}
            res = requests.put(url, headers=headers, json=payload, timeout=10)
            return res.status_code in [200, 204]
        except Exception:
            return False

    # --- TRAILING STOP ---

    def _trail_positions(self, positions):
        """
        Aggressive trailing stop untuk scalping modal kecil.
        Breakeven lebih cepat di +5 pip (bukan +10 pip).
        """
        for p in positions:
            if "XAU" not in p.get("symbol", "").upper(): continue
            open_price    = float(p.get("openPrice", 0))
            current_price = float(p.get("currentPrice", 0))
            pos_id        = p.get("id")
            pos_type      = p.get("type", "")
            if open_price == 0 or current_price == 0: continue

            is_buy    = pos_type == "POSITION_TYPE_BUY"
            profit_pt = (current_price - open_price) if is_buy else (open_price - current_price)

            # Breakeven lebih cepat: +5 pip (0.5 point)
            if profit_pt >= 0.5:
                be_sl = open_price + 0.05 if is_buy else open_price - 0.05
                self.update_forex_sl(pos_id, be_sl)

            # Trail agresif: setiap +3 pip setelah BE
            if profit_pt >= 0.8:
                trail_sl = current_price - 0.3 if is_buy else current_price + 0.3
                self.update_forex_sl(pos_id, trail_sl)

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

                # LIVE PRICE FROM METAAPI
                price_data   = self.get_live_price()
                broker_price = price_data["mid"]
                spread_pts   = price_data["spread_points"]

                if broker_price == 0:
                    time.sleep(5)
                    continue

                # POSITIONS
                positions    = self._get_positions()
                active_count = len(positions)
                total_lots   = sum(float(p.get("volume", 0)) for p in positions)
                print(f"[FOREX DASHBOARD] Price: {broker_price} | Trades: {active_count} | Lots: {round(total_lots, 2)} | Spread: {spread_pts}pts")

                # TRAILING STOP
                self._trail_positions(positions)

                # POSITION LIMIT
                if active_count >= MAX_POSITIONS:
                    time.sleep(SCAN_INTERVAL)
                    continue

                # SPREAD FILTER
                if spread_pts > MAX_SPREAD_POINTS:
                    print(f"[SPREAD GUARD] Spread {spread_pts}pts too wide. Skipping.")
                    time.sleep(SCAN_INTERVAL)
                    continue

                # COOLDOWN
                if time.time() - last_auto_trade < COOLDOWN_AFTER_TRADE:
                    time.sleep(SCAN_INTERVAL)
                    continue

                # CALCULATE INDICATORS FROM METAAPI CANDLES
                ind = self._calc_indicators()
                if not ind:
                    print("[FOREX] Cannot get candles from MetaAPI. Retrying...")
                    time.sleep(10)
                    continue

                # DETERMINE SIDE
                side, score = self._determine_side(ind, spread_pts)
                if side is None:
                    time.sleep(SCAN_INTERVAL)
                    continue

                # CALCULATE TP/SL
                entry_price = price_data["ask"] if side == "buy" else price_data["bid"]
                atr         = ind.get("atr", 1.5)
                tp, sl      = self._calc_tp_sl(entry_price, side, atr)

                # LOT SIZE
                lot = self._calc_lot_size(balance)

                # EXECUTE
                sym = self._working_symbol or "XAUUSD"
                rsi_val  = ind.get("rsi", 0)
                vwap_val = ind.get("vwap_dist", 0)
                trend    = ind.get("trend", "NEUTRAL")
                fvg_val  = ind.get("fvg", "NONE")
                print("")
                print("=" * 60)
                print(f"[FOREX SCALPER v4.0] XAUUSD {side.upper()} | Score: {score}/100")
                print(f"  Price  : {entry_price} | ATR: {atr}")
                print(f"  RSI    : {rsi_val} | VWAP Dist: {vwap_val}%")
                print(f"  Trend  : {trend} | FVG: {fvg_val}")
                print(f"  TP     : {tp} (+{SCALP_TP_POINTS}pt) | SL: {sl} (-{SCALP_SL_POINTS}pt) | Lot: {lot}")
                print("=" * 60)

                success, _ = self.place_forex_order(sym, side, lot, tp=tp, sl=sl)
                if success:
                    from database import log_trade
                    log_trade(sym, entry_price, tp, sl, market="forex")
                    last_auto_trade = time.time()

                time.sleep(SCAN_INTERVAL)

            except Exception as e:
                print(f"[FOREX ENGINE ERROR] {e}")
                time.sleep(5)
