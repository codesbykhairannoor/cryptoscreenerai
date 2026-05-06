"""
CRYPTO ENGINE v9.0 - WHALE OBSERVER MODE
=========================================
Filosofi:
- 1 trade terbaik, semua modal, fokus penuh
- Selama 15 menit cooldown: bot AKTIF scan, observasi, dan akumulasi kandidat
- Di akhir cooldown: masuk koin dengan score TERTINGGI + KONSISTEN (bukan yang pertama lolos)
- "Baca masa depan" ala whale: OI trend, funding momentum, volume accumulation, liquidity hunt
- SL berbasis peak PnL (tidak pernah turun)
- TP full di satu level

WHALE OBSERVER LOGIC:
- Setiap 10 detik selama cooldown, bot scan top 20 koin
- Setiap koin yang lolos filter dicatat: symbol, score, side, timestamp
- Koin yang KONSISTEN muncul dengan score tinggi = sinyal whale accumulation
- Koin yang score-nya NAIK dari scan ke scan = momentum building
- Di akhir cooldown, pilih koin dengan: highest avg_score x consistency_bonus x momentum_bonus

SINYAL "BACA MASA DEPAN":
1. OI naik + harga flat = akumulasi diam-diam (whale masuk sebelum pump)
2. Funding rate negatif + OI tinggi = short squeeze imminent
3. Volume spike di candle kecil (1m/3m) sebelum candle besar = early signal
4. Liquidity sweep di bawah support = stop hunt sebelum reversal naik
5. Bid/Ask imbalance naik konsisten = buyer dominance building

MATEMATIKA:
- Modal $8, leverage 10x = $80 notional
- Fee round trip = $80 x 0.12% = $0.096 = 1.2% PnL
- TP 80% PnL bersih = 78.8% -> $6.30 per win
- SL 15% PnL = $1.20 per loss
- 1 win = 5.25 loss -> butuh win 1 dari 6 trade
"""

import time
import requests
from collections import defaultdict
from data_fetcher import (
    fetch_all_tickers, get_technical_indicators,
    get_retail_sentiment, detect_institutional_flow
)
from sentiment import get_crypto_news, get_global_market_data
from ai_model import analyze_and_sort
from database import log_trade
from bitget_executor import BitgetExecutor

# ─── KONFIGURASI ──────────────────────────────────────────────────────────────
MAX_POSITIONS        = 1      # FOKUS: 1 trade saja
SCAN_INTERVAL        = 10     # Scan setiap 10 detik selama cooldown (observasi aktif)
COOLDOWN_AFTER_TRADE = 900    # 15 menit cooldown - bot AKTIF observasi, bukan diam
NEWS_REPORT_INTERVAL = 600
GLOBAL_REPORT_INTERVAL = 300
LEVERAGE             = 10
MIN_MOMENTUM_SCORE   = 40     # Combined score minimum untuk masuk watchlist
MIN_TECH_SCORE       = 30     # Tech score minimum
MIN_PUMP_SCORE       = 25     # Pump score minimum

# ── WHALE OBSERVER CONFIG ─────────────────────────────────────────────────────
MIN_APPEARANCES      = 3
MIN_AVG_SCORE        = 45
CONSISTENCY_BONUS    = 1.15
MOMENTUM_BONUS       = 1.10
REPEAT_LOSS_BLACKLIST_HOURS = 4
REPEAT_LOSS_MAX_COUNT       = 2

# OI & Funding thresholds
OI_SURGE_THRESHOLD   = 0.05
FUNDING_SQUEEZE_THR  = -0.001
VOLUME_SPIKE_RATIO   = 2.5

# TP/SL berbasis PnL target (10x leverage)
SCALP_TP_PCT  = 0.08
SCALP_SL_PCT  = 0.015
SCALP_TP_ATR  = 5.0
SCALP_SL_ATR  = 1.5

# Session filter
CRYPTO_SESSION_START_UTC = 1
CRYPTO_SESSION_END_UTC   = 15

SIDEWAYS_HOURS       = 1.0
SIDEWAYS_PNL_RANGE   = 2.0
SIDEWAYS_PRICE_MOVE  = 0.5
DAILY_LOSS_LIMIT_PCT = -40

# ── MARKET INTELLIGENCE CONFIG ────────────────────────────────────────────────
# ADX Market Regime: hanya trade di trending market
ADX_TRENDING_THRESHOLD  = 22   # ADX > 22 = trending, boleh entry
ADX_RANGING_THRESHOLD   = 18   # ADX < 18 = ranging, skip semua entry
ADX_PERIOD              = 14

# Volatility Regime: ATR relatif vs baseline
VOL_HIGH_MULTIPLIER     = 2.5  # ATR > 2.5x baseline = terlalu volatile, SL sering kena noise
VOL_LOW_MULTIPLIER      = 0.4  # ATR < 0.4x baseline = terlalu sepi, spread makan profit
VOL_BASELINE_PERIOD     = 20   # Periode untuk hitung ATR baseline

# Expected Value minimum sebelum entry
# EV = (win_rate_estimate x TP_pct) - (loss_rate x SL_pct)
# Kalau EV negatif atau terlalu kecil, skip
MIN_EXPECTED_VALUE      = 0.005  # Minimum 0.5% EV per trade


# ─── MARKET INTELLIGENCE ENGINE ──────────────────────────────────────────────

def _calc_adx(symbol: str, period: int = ADX_PERIOD, interval: str = "15m") -> float:
    """
    Hitung ADX (Average Directional Index) dari candle Bitget.
    ADX mengukur KEKUATAN trend, bukan arahnya.
    ADX > 25 = trend kuat (trending market) -> sinyal SMC reliable
    ADX < 20 = market ranging/sideways -> sinyal SMC banyak false signal
    """
    try:
        url = (
            f"https://api.bitget.com/api/v2/mix/market/history-candles"
            f"?symbol={symbol}&granularity={interval}&limit={period*3}&productType=USDT-FUTURES"
        )
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code != 200:
            return 25.0  # Default: assume trending kalau tidak bisa fetch

        data = r.json().get('data', [])
        if len(data) < period + 2:
            return 25.0

        highs  = [float(c[2]) for c in data]
        lows   = [float(c[3]) for c in data]
        closes = [float(c[4]) for c in data]

        # True Range
        trs = []
        for i in range(1, len(closes)):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i]  - closes[i-1]))
            trs.append(tr)

        # Directional Movement
        plus_dm  = []
        minus_dm = []
        for i in range(1, len(highs)):
            up   = highs[i]  - highs[i-1]
            down = lows[i-1] - lows[i]
            plus_dm.append(up   if up > down and up > 0   else 0)
            minus_dm.append(down if down > up and down > 0 else 0)

        # Smoothed ATR, +DM, -DM (Wilder's smoothing)
        def wilder_smooth(data, n):
            result = [sum(data[:n]) / n]
            for i in range(n, len(data)):
                result.append(result[-1] - result[-1]/n + data[i])
            return result

        atr_s    = wilder_smooth(trs,      period)
        plus_s   = wilder_smooth(plus_dm,  period)
        minus_s  = wilder_smooth(minus_dm, period)

        # DI+ dan DI-
        di_plus  = [100 * p / a if a > 0 else 0 for p, a in zip(plus_s,  atr_s)]
        di_minus = [100 * m / a if a > 0 else 0 for m, a in zip(minus_s, atr_s)]

        # DX dan ADX
        dx_list = []
        for p, m in zip(di_plus, di_minus):
            total = p + m
            dx_list.append(100 * abs(p - m) / total if total > 0 else 0)

        if len(dx_list) < period:
            return 25.0

        adx = sum(dx_list[-period:]) / period
        return round(adx, 2)

    except Exception:
        return 25.0  # Default: assume trending


def _calc_volatility_regime(symbol: str, interval: str = "15m") -> dict:
    """
    Hitung volatility regime berdasarkan ATR relatif.
    Bandingkan ATR candle terakhir vs ATR baseline (20 periode).

    Return:
      regime : "NORMAL" / "HIGH_VOL" / "LOW_VOL"
      atr_ratio : ATR sekarang / ATR baseline
      atr_current : nilai ATR sekarang
    """
    try:
        url = (
            f"https://api.bitget.com/api/v2/mix/market/history-candles"
            f"?symbol={symbol}&granularity={interval}&limit=50&productType=USDT-FUTURES"
        )
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code != 200:
            return {"regime": "NORMAL", "atr_ratio": 1.0, "atr_current": 0}

        data = r.json().get('data', [])
        if len(data) < VOL_BASELINE_PERIOD + 2:
            return {"regime": "NORMAL", "atr_ratio": 1.0, "atr_current": 0}

        highs  = [float(c[2]) for c in data]
        lows   = [float(c[3]) for c in data]
        closes = [float(c[4]) for c in data]

        trs = []
        for i in range(1, len(closes)):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i]  - closes[i-1]))
            trs.append(tr)

        if len(trs) < VOL_BASELINE_PERIOD:
            return {"regime": "NORMAL", "atr_ratio": 1.0, "atr_current": 0}

        atr_current  = trs[-1]
        atr_baseline = sum(trs[-VOL_BASELINE_PERIOD:]) / VOL_BASELINE_PERIOD
        atr_ratio    = atr_current / atr_baseline if atr_baseline > 0 else 1.0

        if atr_ratio > VOL_HIGH_MULTIPLIER:
            regime = "HIGH_VOL"   # Terlalu volatile - SL sering kena noise
        elif atr_ratio < VOL_LOW_MULTIPLIER:
            regime = "LOW_VOL"    # Terlalu sepi - spread makan profit
        else:
            regime = "NORMAL"

        return {
            "regime":      regime,
            "atr_ratio":   round(atr_ratio, 2),
            "atr_current": round(atr_current, 6),
        }

    except Exception:
        return {"regime": "NORMAL", "atr_ratio": 1.0, "atr_current": 0}


def _calc_expected_value(side: str, tech: dict, combined_score: int) -> float:
    """
    Hitung Expected Value (EV) per trade sebelum entry.

    Formula institusi:
    EV = (P_win x TP_pct) - (P_loss x SL_pct)

    P_win diestimasi dari:
    - combined_score (sinyal kualitas)
    - Alignment sinyal (trend, whale, OBI)
    - ADX (kekuatan trend)

    Kalau EV < MIN_EXPECTED_VALUE -> skip, tidak worth it.

    Contoh:
    - Score 70, trend aligned, whale buy -> P_win ~55%
    - TP 8%, SL 1.5%
    - EV = (0.55 x 0.08) - (0.45 x 0.015) = 0.044 - 0.0068 = 0.037 = 3.7% ✓

    - Score 42, no whale, ranging market -> P_win ~30%
    - EV = (0.30 x 0.08) - (0.70 x 0.015) = 0.024 - 0.0105 = 0.0135 = 1.35% ✓ (tapi tipis)
    """
    # Estimasi P_win dari combined_score (base probability)
    # Score 40 = 35% win rate (minimum), Score 100 = 65% win rate (maximum)
    base_p_win = 0.30 + (combined_score / 100) * 0.35  # range 30%-65%

    # Adjustment berdasarkan sinyal tambahan
    adjustments = 0.0

    # Whale alignment
    whale = tech.get('whale_signal', 'NORMAL')
    if side == "buy"  and whale == "WHALE_BUY":   adjustments += 0.08
    if side == "sell" and whale == "WHALE_SELL":  adjustments += 0.08
    if side == "buy"  and whale == "WHALE_SELL":  adjustments -= 0.10
    if side == "sell" and whale == "WHALE_BUY":   adjustments -= 0.10

    # OBI alignment
    obi = tech.get('obi', 0)
    if side == "buy"  and obi > 0.15:  adjustments += 0.05
    if side == "sell" and obi < -0.15: adjustments += 0.05

    # Funding rate (short squeeze = higher P_win for buy)
    funding = tech.get('funding_rate', 0)
    if side == "buy"  and funding < -0.001: adjustments += 0.06  # short squeeze
    if side == "sell" and funding > 0.001:  adjustments += 0.04  # long squeeze

    # MSS/CHoCH confirmation
    if side == "buy"  and tech.get('mss_bullish'):  adjustments += 0.05
    if side == "sell" and tech.get('mss_bearish'):  adjustments += 0.05

    p_win  = min(0.75, max(0.20, base_p_win + adjustments))
    p_loss = 1.0 - p_win

    tp_pct = SCALP_TP_PCT   # 8%
    sl_pct = SCALP_SL_PCT   # 1.5%

    ev = (p_win * tp_pct) - (p_loss * sl_pct)
    return round(ev, 4)

    def __init__(self):
        # {clean_base: [(timestamp, combined_score, tech_score, side, tech_dict), ...]}
        self._watchlist: dict = defaultdict(list)
        # OI baseline saat pertama kali koin masuk watchlist
        self._oi_baseline: dict = {}
        # Waktu mulai observasi periode ini
        self._obs_start: float = 0.0

    def reset(self):
        """Reset watchlist untuk periode observasi baru."""
        self._watchlist.clear()
        self._oi_baseline.clear()
        self._obs_start = time.time()
        print(f"[WHALE OBSERVER] Periode observasi baru dimulai. "
              f"Akan pilih kandidat terbaik dalam {COOLDOWN_AFTER_TRADE//60} menit.")

    def record(self, clean_base: str, combined_score: int, tech_score: int,
               side: str, tech: dict):
        """Catat satu observasi untuk koin ini."""
        now = time.time()
        self._watchlist[clean_base].append((now, combined_score, tech_score, side, tech))

        # Simpan OI baseline pertama kali
        if clean_base not in self._oi_baseline:
            self._oi_baseline[clean_base] = tech.get('open_interest', 0)

    def _calc_future_score(self, clean_base: str, entries: list) -> float:
        """
        Hitung "future score" - seberapa besar probabilitas koin ini akan bergerak.
        
        Sinyal yang dipakai (ala whale intelligence):
        1. OI Surge: OI naik dari baseline = akumulasi diam-diam sebelum pump
        2. Funding Squeeze: funding negatif + OI tinggi = short squeeze imminent
        3. Volume Spike Consistency: volume spike muncul berulang = institutional buying
        4. Liquidity Hunt: liquidity sweep berulang = stop hunt sebelum reversal
        5. Score Momentum: score naik dari scan ke scan = momentum building
        6. Whale Signal Consistency: WHALE_BUY muncul berulang = smart money masuk
        """
        if not entries:
            return 0.0

        future_score = 0.0
        latest_tech  = entries[-1][4]  # tech dict dari observasi terakhir
        side         = entries[-1][3]

        # ── 1. OI SURGE (max 25 poin) ─────────────────────────────────────────
        # OI naik dari baseline = posisi baru dibuka = akumulasi
        oi_now      = latest_tech.get('open_interest', 0)
        oi_baseline = self._oi_baseline.get(clean_base, oi_now)
        if oi_baseline > 0 and oi_now > 0:
            oi_change = (oi_now - oi_baseline) / oi_baseline
            if side == "buy":
                if oi_change >= 0.15:   future_score += 25  # OI naik 15%+ = akumulasi kuat
                elif oi_change >= 0.08: future_score += 18  # OI naik 8%+
                elif oi_change >= 0.03: future_score += 10  # OI naik 3%+
                elif oi_change < -0.05: future_score -= 10  # OI turun = posisi ditutup
            else:  # sell
                if oi_change >= 0.10:   future_score += 20  # OI naik + short = distribution
                elif oi_change >= 0.05: future_score += 12

        # ── 2. FUNDING SQUEEZE (max 20 poin) ──────────────────────────────────
        # Funding negatif = shorts bayar longs = short squeeze imminent
        funding = latest_tech.get('funding_rate', 0)
        if side == "buy" and funding < FUNDING_SQUEEZE_THR:
            squeeze_strength = abs(funding) / abs(FUNDING_SQUEEZE_THR)
            future_score += min(20, squeeze_strength * 20)
            print(f"[FUTURE] {clean_base} SHORT SQUEEZE signal! Funding: {funding:.4f}")
        elif side == "sell" and funding > 0.001:
            # Funding positif tinggi = longs terlalu mahal = long squeeze
            future_score += min(15, (funding / 0.001) * 10)

        # ── 3. SCORE MOMENTUM (max 20 poin) ───────────────────────────────────
        # Score naik dari scan ke scan = momentum building
        if len(entries) >= 3:
            scores = [e[1] for e in entries]  # combined_score per scan
            # Hitung slope: apakah score naik?
            n = len(scores)
            x_mean = (n - 1) / 2
            y_mean = sum(scores) / n
            numerator   = sum((i - x_mean) * (scores[i] - y_mean) for i in range(n))
            denominator = sum((i - x_mean) ** 2 for i in range(n))
            slope = numerator / denominator if denominator > 0 else 0

            if slope > 1.5:    future_score += 20  # Score naik cepat
            elif slope > 0.5:  future_score += 12  # Score naik pelan
            elif slope > 0:    future_score += 5   # Score stabil naik
            elif slope < -1.5: future_score -= 15  # Score turun = sinyal melemah

        # ── 4. WHALE SIGNAL CONSISTENCY (max 15 poin) ─────────────────────────
        # WHALE_BUY muncul berulang = smart money terus akumulasi
        whale_signals = [e[4].get('whale_signal', 'NORMAL') for e in entries]
        if side == "buy":
            whale_buy_count = whale_signals.count('WHALE_BUY')
            whale_ratio = whale_buy_count / len(whale_signals)
            if whale_ratio >= 0.6:   future_score += 15  # 60%+ scan ada whale buy
            elif whale_ratio >= 0.4: future_score += 10
            elif whale_ratio >= 0.2: future_score += 5
        else:
            whale_sell_count = whale_signals.count('WHALE_SELL')
            whale_ratio = whale_sell_count / len(whale_signals)
            if whale_ratio >= 0.6:   future_score += 15
            elif whale_ratio >= 0.4: future_score += 10

        # ── 5. LIQUIDITY HUNT (max 10 poin) ───────────────────────────────────
        # Liquidity sweep berulang = stop hunt sebelum reversal
        liq_sweeps = sum(1 for e in entries if e[4].get('is_liquidity_sweep', False))
        liq_ratio  = liq_sweeps / len(entries)
        if liq_ratio >= 0.4:   future_score += 10  # 40%+ scan ada liq sweep
        elif liq_ratio >= 0.2: future_score += 5

        # ── 6. OBI CONSISTENCY (max 10 poin) ──────────────────────────────────
        # Bid/Ask imbalance konsisten ke satu arah = buyer/seller dominance
        obis = [e[4].get('obi', 0) for e in entries]
        avg_obi = sum(obis) / len(obis) if obis else 0
        if side == "buy"  and avg_obi > 0.12:  future_score += 10
        elif side == "buy"  and avg_obi > 0.06: future_score += 5
        elif side == "sell" and avg_obi < -0.12: future_score += 10
        elif side == "sell" and avg_obi < -0.06: future_score += 5

        return round(future_score, 2)

        # Pilih kandidat terbaik dari observasi. Return dict atau None.
        """
        """
        now = time.time()
        best = None
        best_final = 0.0

        print(f"\n[WHALE OBSERVER] Evaluasi {len(self._watchlist)} kandidat dari "
              f"{round((now - self._obs_start)/60, 1)} menit observasi:")

        for clean_base, entries in self._watchlist.items():
            # Skip koin yang sudah ada posisi atau baru di-exit
            if clean_base in open_bases:
                continue
            if clean_base in recently_exited:
                mins_ago = round((now - recently_exited[clean_base]) / 60, 1)
                print(f"  [SKIP] {clean_base} baru exit {mins_ago} menit lalu")
                continue

            # Minimum appearances filter
            if len(entries) < MIN_APPEARANCES:
                continue

            # Hitung avg combined score
            avg_score = sum(e[1] for e in entries) / len(entries)
            if avg_score < MIN_AVG_SCORE:
                continue

            # Ambil side yang paling sering muncul (majority vote)
            sides = [e[3] for e in entries if e[3] is not None]
            if not sides:
                continue
            side = max(set(sides), key=sides.count)

            # Filter entries yang side-nya sesuai majority
            side_entries = [e for e in entries if e[3] == side]
            if len(side_entries) < MIN_APPEARANCES:
                continue

            # Consistency bonus: muncul banyak kali = sinyal stabil
            appearances = len(entries)
            consistency = CONSISTENCY_BONUS if appearances >= 6 else 1.0

            # Momentum bonus: score naik dari scan ke scan
            scores = [e[1] for e in entries]
            is_rising = len(scores) >= 3 and scores[-1] > scores[0]
            momentum  = MOMENTUM_BONUS if is_rising else 1.0

            # Future score (sinyal prediktif)
            future_sc = self._calc_future_score(clean_base, side_entries)

            # Final score
            final = (avg_score * consistency * momentum) + future_sc

            # GUARD: jangan pilih koin yang tidak punya sinyal prediktif sama sekali
            # Future=0 + Rising=False = tidak ada bukti whale/momentum - terlalu spekulatif
            # Kecuali tidak ada kandidat lain (akan di-handle di bawah dengan flag)
            has_predictive_signal = future_sc > 0 or is_rising or \
                                    latest_tech.get('whale_signal') == 'WHALE_BUY' or \
                                    latest_tech.get('whale_signal') == 'WHALE_SELL'

            # Ambil tech dari observasi terakhir
            latest_tech = side_entries[-1][4]
            avg_tech_score = sum(e[2] for e in side_entries) / len(side_entries)

            print(f"  {clean_base:10s} | Side:{side:4s} | Appear:{appearances:2d}x | "
                  f"AvgScore:{avg_score:.1f} | Future:{future_sc:.1f} | Final:{final:.1f} "
                  f"{'📈' if is_rising else '  '} "
                  f"{'🐋' if latest_tech.get('whale_signal')=='WHALE_BUY' else '  '}"
                  f"{'⚠️ NO_SIGNAL' if not has_predictive_signal else ''}")

            if final > best_final:
                best_final = final
                best = {
                    'clean_base':          clean_base,
                    'side':                side,
                    'avg_score':           round(avg_score, 1),
                    'final_score':         round(final, 1),
                    'future_score':        round(future_sc, 1),
                    'appearances':         appearances,
                    'is_rising':           is_rising,
                    'has_predictive_signal': has_predictive_signal,
                    'tech':                latest_tech,
                    'avg_tech_score':      round(avg_tech_score, 1),
                }

        if best:
            print(f"\n[WHALE OBSERVER] 🎯 PILIHAN TERBAIK: {best['clean_base']} {best['side'].upper()}")
            print(f"  AvgScore:{best['avg_score']} | Future:{best['future_score']} | "
                  f"Final:{best['final_score']} | Muncul:{best['appearances']}x | "
                  f"Rising:{best['is_rising']}")
        else:
            print(f"[WHALE OBSERVER] Tidak ada kandidat yang memenuhi syarat.")

        return best


# ─── HELPER: HITUNG VWAP ──────────────────────────────────────────────────────
def _calc_vwap_dist(mark_price: float, symbol: str) -> float:
    """
    Hitung jarak harga dari VWAP dalam persen menggunakan candle 15m.
    Bitget candle format: [ts, open, high, low, close, vol, quoteVol]
    Index:                  0    1     2    3    4      5    6
    """
    try:
        url = (
            f"https://api.bitget.com/api/v2/mix/market/history-candles"
            f"?symbol={symbol}&granularity=15m&limit=96&productType=USDT-FUTURES"
        )
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code != 200:
            return 0.0
        data = r.json().get('data', [])
        if not data or len(data) < 5:
            return 0.0

        cum_pv = 0.0
        cum_v  = 0.0
        for c in data:
            # Bitget: [ts, open, high, low, close, baseVol, quoteVol]
            try:
                high  = float(c[2])
                low   = float(c[3])
                close = float(c[4])
                vol   = float(c[5])  # base volume
                if vol <= 0:
                    continue
                typical = (high + low + close) / 3
                cum_pv += typical * vol
                cum_v  += vol
            except (IndexError, ValueError):
                continue

        if cum_v == 0:
            return 0.0
        vwap = cum_pv / cum_v
        if vwap == 0:
            return 0.0
        dist = ((mark_price - vwap) / vwap) * 100
        # Sanity check: VWAP dist > 20% tidak masuk akal untuk 24h
        if abs(dist) > 20:
            return 0.0
        return round(dist, 4)
    except Exception:
        return 0.0


# ─── HELPER: HITUNG RSI ───────────────────────────────────────────────────────
def _calc_rsi(symbol: str, period: int = 14, interval: str = "15m") -> float:
    """Hitung RSI dari candle Bitget."""
    try:
        url = (
            f"https://api.bitget.com/api/v2/mix/market/history-candles"
            f"?symbol={symbol}&granularity={interval}&limit=100&productType=USDT-FUTURES"
        )
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code != 200:
            return 50.0
        data = r.json().get('data', [])
        if len(data) < period + 1:
            return 50.0

        closes = [float(c[4]) for c in data]
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0
        rs  = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 2)
    except Exception:
        return 50.0


# ─── HELPER: DETECT VOLATILITY SPIKE ─────────────────────────────────────────
def detect_volatility_spike(symbol: str, timeframe: str = "1m") -> bool:
    """Deteksi apakah ada volume spike 3x dari rata-rata."""
    try:
        url = (
            f"https://data-api.binance.vision/api/v3/klines"
            f"?symbol={symbol.replace('USDT', '')}USDT&interval={timeframe}&limit=5"
        )
        res = requests.get(url, timeout=2)
        data = res.json()
        if not data or len(data) < 5:
            return False
        last_vol = float(data[-1][5])
        avg_vol  = sum(float(d[5]) for d in data[:-1]) / 4
        return last_vol > avg_vol * 3.0
    except Exception:
        return False


# ─── CORE: MOMENTUM SCORING SYSTEM ───────────────────────────────────────────
def _score_candidate(tech: dict, rsi: float, vwap_dist: float, side: str) -> int:
    """
    Hitung momentum score 0-100 untuk sebuah kandidat.
    Semakin tinggi = semakin bagus untuk entry.
    """
    score = 0

    # 1. RSI Zone (max 25 poin)
    if side == "buy":
        if 30 <= rsi <= 50:   score += 25   # Oversold recovery - ideal
        elif 50 < rsi <= 60:  score += 15   # Momentum building
        elif 20 <= rsi < 30:  score += 10   # Terlalu oversold, risky
        elif rsi > 70:        score -= 10   # Overbought, skip
    else:  # sell
        if 50 <= rsi <= 70:   score += 25   # Overbought rejection - ideal
        elif 40 <= rsi < 50:  score += 15   # Momentum bearish
        elif rsi > 80:        score += 10   # Terlalu overbought, risky
        elif rsi < 30:        score -= 10   # Oversold, skip short

    # 2. VWAP Distance (max 20 poin)
    if side == "buy":
        if -3.0 <= vwap_dist <= -0.5:  score += 20  # Di bawah VWAP - discount zone
        elif -0.5 < vwap_dist <= 0.5:  score += 10  # Dekat VWAP
        elif vwap_dist > 3.0:          score -= 10  # Terlalu jauh di atas VWAP
    else:
        if 0.5 <= vwap_dist <= 3.0:    score += 20  # Di atas VWAP - premium zone
        elif -0.5 <= vwap_dist < 0.5:  score += 10  # Dekat VWAP
        elif vwap_dist < -3.0:         score -= 10  # Terlalu jauh di bawah VWAP

    # 3. SMC Signals (max 20 poin)
    fvg = tech.get('fvg', 'NONE')
    ob  = tech.get('order_block', 'NONE')
    if side == "buy":
        if fvg == 'BULLISH_FVG':   score += 12
        if ob  == 'BULLISH_OB':    score += 8
    else:
        if fvg == 'BEARISH_FVG':   score += 12
        if ob  == 'BEARISH_OB':    score += 8

    # 4. Market Structure (max 15 poin)
    if side == "buy":
        if tech.get('mss_bullish'):   score += 15
        elif tech.get('choch_bullish'): score += 8
    else:
        if tech.get('mss_bearish'):   score += 15
        elif tech.get('choch_bearish'): score += 8

    # 5. Whale & OBI (max 15 poin)
    whale = tech.get('whale_signal', 'NORMAL')
    obi   = tech.get('obi', 0)
    if side == "buy":
        if whale == 'WHALE_BUY':   score += 10
        if obi > 0.15:             score += 5
    else:
        if whale == 'WHALE_SELL':  score += 10
        if obi < -0.15:            score += 5

    # 6. Institutional Flow (max 5 poin)
    inst = tech.get('inst_flow', 'NORMAL')
    if side == "buy"  and inst == 'INSTITUTIONAL_ACCUMULATION': score += 5
    if side == "sell" and inst == 'INSTITUTIONAL_DISTRIBUTION': score += 5

    # 7. Funding Rate Penalty
    funding = tech.get('funding_rate', 0)
    if side == "buy"  and funding > 0.001:  score -= 10  # Longs terlalu mahal
    if side == "sell" and funding < -0.001: score -= 10  # Shorts terlalu mahal

    return max(0, min(100, score))


# ─── CORE: TENTUKAN SIDE & REASON ────────────────────────────────────────────
def _determine_trade_side(tech: dict, rsi: float, vwap_dist: float,
                           market_sentiment: str) -> tuple[str | None, str, int]:
    """
    Return (side, reason, score) atau (None, '', 0) kalau tidak ada setup.
    Bi-directional: bisa long DAN short.
    """
    best_side   = None
    best_reason = ""
    best_score  = 0

    fvg   = tech.get('fvg', 'NONE')
    ob    = tech.get('order_block', 'NONE')
    whale = tech.get('whale_signal', 'NORMAL')
    liq   = tech.get('is_liquidity_sweep', False)
    mss_b = tech.get('mss_bullish', False)
    mss_s = tech.get('mss_bearish', False)
    choch_b = tech.get('choch_bullish', False)
    choch_s = tech.get('choch_bearish', False)
    obi   = tech.get('obi', 0)

    # ── LONG SETUPS ──────────────────────────────────────────────────────────
    long_candidates = []

    # Setup 1: Whale Accumulation + Discount Zone
    if whale == 'WHALE_BUY' and vwap_dist < 0.5:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "WHALE ACCUMULATION + DISCOUNT ZONE"))

    # Setup 2: Bullish FVG Re-entry
    if fvg == 'BULLISH_FVG' and rsi < 60:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "BULLISH FVG RE-ENTRY"))

    # Setup 3: MSS Bullish Breakout
    if mss_b and obi > 0.05:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "MSS BULLISH BREAKOUT"))

    # Setup 4: CHoCH + Liquidity Sweep
    if choch_b and liq and rsi < 55:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "CHoCH REVERSAL + LIQUIDITY SWEEP"))

    # Setup 5: Bullish OB + Oversold RSI
    if ob == 'BULLISH_OB' and rsi < 45:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "BULLISH ORDER BLOCK + OVERSOLD RSI"))

    # Setup 6: RSI Oversold Recovery (tidak butuh SMC signal)
    if 28 <= rsi <= 42 and vwap_dist < 2.0:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "RSI OVERSOLD RECOVERY"))

    # Setup 7: Momentum Breakout (harga di bawah VWAP, mulai naik)
    if -3.0 <= vwap_dist <= -0.3 and (choch_b or mss_b or fvg == 'BULLISH_FVG'):
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "MOMENTUM BREAKOUT FROM DISCOUNT"))

    # ── SHORT SETUPS ─────────────────────────────────────────────────────────
    short_candidates = []

    # Setup 1: Whale Distribution + Premium Zone
    if whale == 'WHALE_SELL' and vwap_dist > 0.5:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "WHALE DISTRIBUTION + PREMIUM ZONE"))

    # Setup 2: Bearish FVG Rejection
    if fvg == 'BEARISH_FVG' and rsi > 45:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "BEARISH FVG REJECTION"))

    # Setup 3: MSS Bearish Breakdown
    if mss_s and obi < -0.05:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "MSS BEARISH BREAKDOWN"))

    # Setup 4: CHoCH + Liquidity Sweep Bearish
    if choch_s and liq and rsi > 50:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "CHoCH BEARISH + LIQUIDITY SWEEP"))

    # Setup 5: Bearish OB + Overbought RSI
    if ob == 'BEARISH_OB' and rsi > 60:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "BEARISH ORDER BLOCK + OVERBOUGHT RSI"))

    # Setup 6: RSI Overbought Rejection (tidak butuh SMC signal)
    if 68 <= rsi <= 85 and vwap_dist > 1.0:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "RSI OVERBOUGHT REJECTION"))

    # Setup 7: Bearish Momentum (harga di atas VWAP, mulai turun)
    if 1.0 <= vwap_dist <= 5.0 and (choch_s or mss_s or fvg == 'BEARISH_FVG'):
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "BEARISH MOMENTUM FROM PREMIUM"))

    # ── PILIH SETUP TERBAIK ───────────────────────────────────────────────────
    all_candidates = [("buy", s, r) for s, r in long_candidates] + \
                     [("sell", s, r) for s, r in short_candidates]

    if not all_candidates:
        return None, "", 0

    # Sort by score descending
    all_candidates.sort(key=lambda x: x[1], reverse=True)
    best_side, best_score, best_reason = all_candidates[0]

    # Sentiment alignment bonus/penalty
    if best_side == "buy"  and market_sentiment == "BULLISH":  best_score = min(100, best_score + 5)
    if best_side == "sell" and market_sentiment == "BEARISH":  best_score = min(100, best_score + 5)
    if best_side == "buy"  and market_sentiment == "BEARISH":  best_score = max(0,   best_score - 8)
    if best_side == "sell" and market_sentiment == "BULLISH":  best_score = max(0,   best_score - 8)

    return best_side, best_reason, best_score


# ─── CORE: HITUNG TP/SL BERBASIS PnL TARGET ──────────────────────────────────
def _calc_tp_sl(mark_price: float, side: str, tech: dict) -> tuple[float, float]:
    """
    TP/SL berbasis PnL target di 10x leverage.
    
    Target FIXED:
    - SL = -15% PnL = -1.5% price move (SELALU, tidak bisa lebih kecil)
    - TP = +80% PnL = +8% price move
    
    ATR hanya dipakai kalau LEBIH BESAR dari minimum % - untuk koin
    volatile yang butuh SL lebih lebar. Tidak pernah lebih kecil dari 1.5%.
    
    Contoh DOGS (harga $0.001, ATR $0.000003):
    - ATR x 1.5 = $0.0000045 = 0.45% -> TERLALU KECIL
    - min_sl = $0.001 x 0.015 = $0.000015 = 1.5% -> PAKAI INI
    
    Contoh BTC (harga $60000, ATR $800):
    - ATR x 1.5 = $1200 = 2% -> LEBIH BESAR dari 1.5%
    - Pakai ATR-based = $1200
    """
    atr = tech.get('atr', 0)

    # HARD MINIMUM: SL tidak boleh lebih kecil dari 1.5% price (= 15% PnL di 10x)
    min_sl_dist = mark_price * SCALP_SL_PCT   # 1.5% - TIDAK BOLEH LEBIH KECIL
    min_tp_dist = mark_price * SCALP_TP_PCT   # 8%

    if atr and atr > 0:
        atr_sl = atr * SCALP_SL_ATR  # ATR x 1.5
        atr_tp = atr * SCALP_TP_ATR  # ATR x 5.0
        # Ambil yang LEBIH BESAR - ATR atau minimum %
        sl_dist = max(atr_sl, min_sl_dist)
        tp_dist = max(atr_tp, min_tp_dist)
    else:
        sl_dist = min_sl_dist
        tp_dist = min_tp_dist

    if side == "buy":
        return round(mark_price + tp_dist, 6), round(mark_price - sl_dist, 6)
    else:
        return round(mark_price - tp_dist, 6), round(mark_price + sl_dist, 6)


# ─── MAIN ENGINE ──────────────────────────────────────────────────────────────
def run_crypto_engine():
    """
    [CRYPTO SCALPER v9.0] - Whale Observer Mode.

    FLOW:
    ┌─────────────────────────────────────────────────────────┐
    │  FASE OBSERVASI (15 menit setelah trade / startup)      │
    │  ↓ Setiap 10 detik:                                     │
    │    - Scan top 20 koin                                   │
    │    - Evaluasi setiap koin (pump + SMC + future signals) │
    │    - Catat ke WhaleObserver watchlist                   │
    │  ↓ Di akhir 15 menit:                                   │
    │    - Pilih koin dengan final_score tertinggi            │
    │    - Eksekusi dengan full confidence                    │
    └─────────────────────────────────────────────────────────┘
    """
    executor = BitgetExecutor()
    observer  = WhaleObserver()

    from database import check_pending_trades, get_performance_stats
    from sentiment import get_market_news_digest

    print("[CRYPTO SCALPER v9.0] Whale Observer Mode AKTIF!")
    print(f"  Strategy : 1 trade terbaik | {LEVERAGE}x leverage")
    print(f"  Cooldown : {COOLDOWN_AFTER_TRADE//60} menit observasi aktif")
    print(f"  Min appear: {MIN_APPEARANCES}x dalam cooldown window")

    last_exec_time     = 0
    last_news_report   = 0
    last_global_report = 0
    _dxy_cache         = {"trend": "NEUTRAL", "ts": 0}
    _recently_exited   = {}  # {clean_base: exit_timestamp}
    # Track koin yang sering kena SL - {clean_base: [timestamp_sl1, timestamp_sl2, ...]}
    # Kalau kena SL 2x dalam 4 jam -> blacklist sementara
    _loss_tracker      = {}  # {clean_base: [timestamps]}

    # Mulai observasi langsung dari startup
    observer.reset()

    while True:
        try:
            # ── 1. MANAGE EXISTING POSITIONS ─────────────────────────────────
            executor.manage_open_positions()
            check_pending_trades()

            now = time.time()

            # ── 2. NEWS VELOCITY (setiap 10 menit) ───────────────────────────
            if now - last_news_report > NEWS_REPORT_INTERVAL:
                digest = get_market_news_digest()
                print(f"[NEWS VELOCITY] Sentiment: {digest['sentiment']} | "
                      f"Top: {digest['crypto_top']}")
                last_news_report = now

            # ── 3. GLOBAL CONTEXT (setiap 5 menit) ───────────────────────────
            if now - last_global_report > GLOBAL_REPORT_INTERVAL:
                global_ctx = get_global_market_data()
                print(f"[GLOBAL] {global_ctx}")
                last_global_report = now

            # ── 4. CIRCUIT BREAKER ────────────────────────────────────────────
            stats     = get_performance_stats('crypto')
            daily_pnl = stats.get('daily_pnl', 0)  # pakai daily_pnl, bukan win_rate
            if daily_pnl < DAILY_LOSS_LIMIT_PCT:
                print(f"[CIRCUIT BREAKER] Daily loss {daily_pnl}% melewati limit "
                      f"{DAILY_LOSS_LIMIT_PCT}%. Standby 30 menit.")
                time.sleep(1800)
                continue

            # ── 4b. SESSION FILTER ────────────────────────────────────────────
            import datetime as _dt
            utc_hour = _dt.datetime.utcnow().hour
            if not (CRYPTO_SESSION_START_UTC <= utc_hour < CRYPTO_SESSION_END_UTC):
                if int(now) % 300 < 10:
                    wib_hour = (utc_hour + 7) % 24
                    print(f"[CRYPTO SESSION] Off-hours ({wib_hour:02d}:xx WIB). "
                          f"Aktif jam 08:00-22:00 WIB.")
                time.sleep(60)
                continue

            # ── 5. POSITION CHECK ─────────────────────────────────────────────
            positions  = executor.get_all_positions()
            open_count = len(positions) if isinstance(positions, list) else 0
            open_bases = [executor._clean_symbol(p['symbol']) for p in positions] \
                         if isinstance(positions, list) else []

            if open_count >= MAX_POSITIONS:
                print(f"[LIMIT] {open_count}/{MAX_POSITIONS} posisi aktif. Manage existing.")
                time.sleep(SCAN_INTERVAL)
                continue

            # ── 6. COOLDOWN CHECK ─────────────────────────────────────────────
            elapsed_since_trade = now - last_exec_time
            cooldown_remaining  = COOLDOWN_AFTER_TRADE - elapsed_since_trade
            in_cooldown         = cooldown_remaining > 0

            # ── 7. BERSIHKAN recently_exited + TRACK LOSSES ──────────────────
            _recently_exited = {k: v for k, v in _recently_exited.items()
                                 if now - v < 1800}
            try:
                from shared_state import state as _state
                if hasattr(_state, 'recently_exited'):
                    for k, v in list(_state.recently_exited.items()):
                        if now - v < 1800:
                            # Koin baru di-exit - catat ke loss tracker
                            if k not in _recently_exited:
                                # Ini exit baru, tambah ke loss tracker
                                if k not in _loss_tracker:
                                    _loss_tracker[k] = []
                                _loss_tracker[k].append(v)
                                loss_count = len([t for t in _loss_tracker[k]
                                                  if t > now - REPEAT_LOSS_BLACKLIST_HOURS * 3600])
                                if loss_count >= REPEAT_LOSS_MAX_COUNT:
                                    print(f"[LOSS TRACKER] {k} kena SL {loss_count}x dalam "
                                          f"{REPEAT_LOSS_BLACKLIST_HOURS}h. Blacklist sementara.")
                            _recently_exited[k] = v
                        else:
                            del _state.recently_exited[k]
            except Exception:
                pass

            # ── 8. MARKET SENTIMENT & DXY ────────────────────────────────────
            digest           = get_market_news_digest()
            market_sentiment = digest.get('sentiment', 'NEUTRAL')

            if now - _dxy_cache["ts"] > 300:
                try:
                    from data_fetcher import get_forex_data
                    dxy = get_forex_data("DXY")
                    _dxy_cache["trend"]  = dxy.get('trend', 'NEUTRAL') if dxy else 'NEUTRAL'
                    _dxy_cache["change"] = dxy.get('change', 0) if dxy else 0
                    _dxy_cache["ts"]     = now
                except Exception:
                    pass
            dxy_trend  = _dxy_cache.get("trend", "NEUTRAL")
            dxy_change = _dxy_cache.get("change", 0)

            # ── 9. SCAN & OBSERVASI ───────────────────────────────────────────
            raw_data   = fetch_all_tickers()
            candidates = analyze_and_sort(raw_data)

            if not candidates:
                time.sleep(SCAN_INTERVAL)
                continue

            # Bersihkan loss tracker yang sudah expired
            cutoff = now - (REPEAT_LOSS_BLACKLIST_HOURS * 3600)
            for base in list(_loss_tracker.keys()):
                _loss_tracker[base] = [t for t in _loss_tracker[base] if t > cutoff]
                if not _loss_tracker[base]:
                    del _loss_tracker[base]

            # Koin yang kena SL 2x+ dalam 4 jam = blacklist sementara
            _repeat_losers = {b for b, ts in _loss_tracker.items()
                              if len(ts) >= REPEAT_LOSS_MAX_COUNT}
            if _repeat_losers:
                print(f"[BLACKLIST] Koin blacklist sementara: {_repeat_losers}")

            # Kalau baru mulai observasi (setelah trade atau startup), reset observer
            if last_exec_time > 0 and elapsed_since_trade < SCAN_INTERVAL + 5:
                observer.reset()

            # ── 9a. SCAN SEMUA KANDIDAT & CATAT KE OBSERVER ──────────────────
            scan_count = 0
            for coin in candidates[:20]:
                symbol     = coin.get('symbol', '')
                clean_base = executor._clean_symbol(symbol)

                # Filter dasar
                if clean_base in open_bases:                          continue
                if clean_base in ('BTC', 'ETH'):                      continue
                if any(x in clean_base for x in ('USD','DAI','BUSD','TUSD','WBTC','WETH')): continue
                if clean_base in _recently_exited:                    continue
                # Skip koin yang sudah sering kena SL
                if clean_base in _repeat_losers:                      continue

                pump_sc = float(coin.get('pump_score', 0))
                if pump_sc < MIN_PUMP_SCORE:                          continue

                # Ambil indikator teknikal
                tech = get_technical_indicators(symbol)
                if not tech:                                           continue

                mark_price = tech.get('mark_price', 0) or float(coin.get('lastPrice', 0))
                if mark_price == 0:                                    continue

                rsi       = tech.get('rsi', _calc_rsi(symbol))
                vwap_dist = _calc_vwap_dist(mark_price, symbol)

                side, reason, tech_score = _determine_trade_side(
                    tech, rsi, vwap_dist, market_sentiment
                )

                combined_score = round((pump_sc * 0.5) + (tech_score * 0.5))

                # ── MARKET REGIME FILTER (ADX) ────────────────────────────────
                # Hanya trade di trending market. Ranging market = sinyal SMC palsu.
                adx = _calc_adx(symbol)
                if adx < ADX_RANGING_THRESHOLD:
                    print(f"[REGIME] {clean_base} ADX={adx} < {ADX_RANGING_THRESHOLD} (RANGING). Skip.")
                    continue
                regime_label = "TRENDING" if adx >= ADX_TRENDING_THRESHOLD else "WEAK_TREND"

                # ── VOLATILITY REGIME FILTER ──────────────────────────────────
                # Skip kalau terlalu volatile (SL kena noise) atau terlalu sepi (spread makan profit)
                vol_data = _calc_volatility_regime(symbol)
                vol_regime = vol_data.get("regime", "NORMAL")
                if vol_regime == "HIGH_VOL":
                    print(f"[VOL] {clean_base} ATR ratio={vol_data['atr_ratio']} HIGH_VOL. Skip.")
                    continue
                if vol_regime == "LOW_VOL":
                    print(f"[VOL] {clean_base} ATR ratio={vol_data['atr_ratio']} LOW_VOL. Skip.")
                    continue

                # ── EXPECTED VALUE CHECK ──────────────────────────────────────
                # Hitung EV sebelum entry. Kalau EV terlalu kecil, tidak worth it.
                ev = _calc_expected_value(side, tech, combined_score) if side else 0
                if ev < MIN_EXPECTED_VALUE:
                    print(f"[EV] {clean_base} EV={ev:.4f} < {MIN_EXPECTED_VALUE}. Skip.")
                    continue

                # DXY override
                is_dxy_active = abs(dxy_change) > 0.0001
                if is_dxy_active and side == "buy" and dxy_trend == "BULLISH" and dxy_change > 0.2:
                    continue

                # Order book confirmation
                from data_fetcher import get_order_book_details
                ob_data  = get_order_book_details(symbol)
                ob_ratio = ob_data.get('ratio', 0)
                if side == "buy"  and ob_ratio < -0.1: continue
                if side == "sell" and ob_ratio > 0.1:  continue

                # Lolos semua filter - catat ke observer
                if side is not None and combined_score >= MIN_MOMENTUM_SCORE and tech_score >= MIN_TECH_SCORE:
                    observer.record(clean_base, combined_score, tech_score, side, tech)
                    scan_count += 1
                    print(f"[OBS] {clean_base:8s} {side:4s} | Pump:{pump_sc:.0f} "
                          f"Tech:{tech_score} Combined:{combined_score} | "
                          f"RSI:{rsi} VWAP:{vwap_dist}% | "
                          f"ADX:{adx} {regime_label} | Vol:{vol_regime} | EV:{ev:.3f} | "
                          f"OI:{tech.get('open_interest',0):.0f} "
                          f"Fund:{tech.get('funding_rate',0):.4f}")

            print(f"[SCAN] {scan_count} kandidat lolos filter | "
                  f"Cooldown: {'YA ' + str(round(cooldown_remaining))+'s' if in_cooldown else 'TIDAK - SIAP ENTRY'}")

            # ── 10. KEPUTUSAN ENTRY ───────────────────────────────────────────
            if in_cooldown:
                # Masih dalam cooldown - terus observasi, jangan entry
                mins_left = round(cooldown_remaining / 60, 1)
                print(f"[OBSERVER] Observasi aktif. {mins_left} menit lagi sebelum entry. "
                      f"Watchlist: {len(observer._watchlist)} koin.")
                time.sleep(SCAN_INTERVAL)
                continue

            # Cooldown selesai - pilih kandidat terbaik dari observasi
            best = observer.get_best_candidate(open_bases, _recently_exited)

            if best is None:
                # Tidak ada kandidat yang cukup kuat dari observasi
                obs_duration = time.time() - observer._obs_start
                if obs_duration > COOLDOWN_AFTER_TRADE * 1.5:
                    print(f"[ENGINE] Observasi {round(obs_duration/60,1)} menit, tidak ada kandidat kuat. Reset.")
                    observer.reset()
                else:
                    print(f"[ENGINE] Belum ada kandidat kuat. Lanjut observasi ({round(obs_duration/60,1)}/{COOLDOWN_AFTER_TRADE//60} menit).")
                time.sleep(SCAN_INTERVAL)
                continue

            # Kalau kandidat terbaik tidak punya sinyal prediktif sama sekali,
            # lanjut observasi kecuali sudah > 30 menit (2x cooldown)
            if not best.get('has_predictive_signal', True):
                obs_duration = time.time() - observer._obs_start
                if obs_duration < COOLDOWN_AFTER_TRADE * 2:
                    print(f"[ENGINE] {best['clean_base']} tidak ada sinyal prediktif "
                          f"(Future:0, Rising:False, Whale:NORMAL). "
                          f"Lanjut observasi {round(obs_duration/60,1)}/{COOLDOWN_AFTER_TRADE*2//60} menit.")
                    time.sleep(SCAN_INTERVAL)
                    continue
                else:
                    print(f"[ENGINE] Sudah {round(obs_duration/60,1)} menit. "
                          f"Masuk {best['clean_base']} meski sinyal prediktif lemah.")

            # ── 11. EKSEKUSI KANDIDAT TERBAIK ────────────────────────────────
            clean_base = best['clean_base']
            side       = best['side']
            tech       = best['tech']

            # Cari symbol lengkap dari candidates
            symbol = None
            for coin in candidates:
                if executor._clean_symbol(coin.get('symbol', '')) == clean_base:
                    symbol = coin.get('symbol')
                    break
            if not symbol:
                symbol = clean_base + 'USDT'

            # Ambil harga terbaru
            fresh_tech = get_technical_indicators(symbol)
            if fresh_tech:
                tech = fresh_tech  # Pakai data fresh untuk eksekusi

            mark_price = tech.get('mark_price', 0)
            if mark_price == 0:
                print(f"[SKIP] {clean_base} tidak bisa ambil harga terbaru.")
                # Jangan reset observer - coba kandidat lain di cycle berikutnya
                time.sleep(SCAN_INTERVAL)
                continue

            rsi       = tech.get('rsi', 50)
            vwap_dist = _calc_vwap_dist(mark_price, symbol)

            # Re-validasi side dengan data fresh
            fresh_side, fresh_reason, fresh_tech_score = _determine_trade_side(
                tech, rsi, vwap_dist, market_sentiment
            )

            # Kalau side berubah dari observasi, pakai yang fresh
            if fresh_side != side:
                print(f"[REVALIDATE] {clean_base} side berubah: {side} -> {fresh_side}. "
                      f"Pakai data terbaru.")
                side = fresh_side
                if side is None:
                    print(f"[SKIP] {clean_base} sinyal hilang saat revalidasi.")
                    # Jangan reset observer - sinyal bisa kembali di cycle berikutnya
                    time.sleep(SCAN_INTERVAL)
                    continue

            reason = fresh_reason or f"Whale Observer Score {best['final_score']}"

            # Hitung TP/SL
            tp, sl = _calc_tp_sl(mark_price, side, tech)

            # Hitung size
            amount = executor.get_max_available(symbol, leverage=LEVERAGE)
            if amount <= 0:
                print(f"[MARGIN GUARD] Insufficient margin for {clean_base}.")
                # Jangan reset - margin issue bukan alasan buang data observasi
                time.sleep(SCAN_INTERVAL)
                continue

            # ── EKSEKUSI ──────────────────────────────────────────────────────
            print(f"\n{'='*65}")
            print(f"[WHALE OBSERVER] 🎯 ENTRY: {clean_base} {side.upper()}")
            print(f"  Reason      : {reason}")
            print(f"  Avg Score   : {best['avg_score']}/100 | Final: {best['final_score']}")
            print(f"  Future Score: {best['future_score']} | Appearances: {best['appearances']}x")
            print(f"  Rising      : {'YA' if best['is_rising'] else 'TIDAK'} | "
                  f"Whale: {tech.get('whale_signal','NORMAL')}")
            print(f"  Price       : {mark_price} | RSI: {rsi} | VWAP: {vwap_dist}%")
            print(f"  OI          : {tech.get('open_interest',0):.0f} | "
                  f"Funding: {tech.get('funding_rate',0):.4f}")
            if side == "buy":
                print(f"  TP: {tp} (+{round((tp/mark_price-1)*100,2)}%) | "
                      f"SL: {sl} (-{round((1-sl/mark_price)*100,2)}%)")
            else:
                print(f"  TP: {tp} (-{round((1-tp/mark_price)*100,2)}%) | "
                      f"SL: {sl} (+{round((sl/mark_price-1)*100,2)}%)")
            print(f"  Leverage    : {LEVERAGE}x | Sentiment: {market_sentiment}")
            print(f"{'='*65}\n")

            success, order = executor.place_order(
                symbol, side, amount, tp=tp, sl=sl, leverage=LEVERAGE
            )
            if success:
                log_trade(symbol, mark_price, tp, sl,
                          side=side,
                          score=best['final_score'],
                          reason=reason)
                last_exec_time = time.time()
                open_count    += 1
                open_bases.append(clean_base)
                print(f"[TRADE LOGGED] {clean_base} {side.upper()} @ {mark_price} "
                      f"| Score: {best['final_score']}")
                # Reset observer untuk periode observasi berikutnya
                observer.reset()
            else:
                print(f"[ORDER FAILED] {clean_base}: {order}")
                # Tetap reset observer - jangan stuck di kandidat yang gagal
                observer.reset()

            time.sleep(SCAN_INTERVAL)

        except Exception as e:
            print(f"[ENGINE ERROR] {e}")
            time.sleep(30)
