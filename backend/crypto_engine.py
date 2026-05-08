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
from concurrent.futures import ThreadPoolExecutor, as_completed

from data_fetcher import (
    get_technical_indicators, fetch_all_tickers,
    get_volume_profile, get_htf_key_levels, get_fibonacci_levels, 
    detect_stop_hunt, detect_institutional_liquidity_grab
)
from sentiment import get_crypto_news, get_global_market_data
from ai_model import analyze_and_sort
from database import log_trade
from bitget_executor import BitgetExecutor

#  KONFIGURASI 
MAX_POSITIONS        = 1      # FOKUS: 1 trade saja
SCAN_INTERVAL        = 10     # Scan setiap 10 detik
COOLDOWN_AFTER_TRADE = 120    # 2 menit cooldown — versi profit May 5
NEWS_REPORT_INTERVAL = 600
GLOBAL_REPORT_INTERVAL = 300
LEVERAGE             = 10
MIN_MOMENTUM_SCORE   = 40     # Threshold versi profit May 6
MIN_TECH_SCORE       = 30     # Tech score minimum
MIN_PUMP_SCORE       = 25     # Pump score minimum untuk masuk scan

#  WHALE OBSERVER CONFIG (Legacy/Reference)
MIN_APPEARANCES      = 3      
MIN_AVG_SCORE        = 42     # Rata-rata combined score minimum — versi profit May 6
CONSISTENCY_BONUS    = 1.15
MOMENTUM_BONUS       = 1.10
REPEAT_LOSS_BLACKLIST_HOURS = 8
REPEAT_LOSS_MAX_COUNT       = 2

# OI & Funding thresholds
OI_SURGE_THRESHOLD   = 0.05
FUNDING_SQUEEZE_THR  = -0.0003  # Fix: -0.03% lebih realistis (sebelumnya -0.1% hampir tidak pernah terjadi)
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

#  MARKET INTELLIGENCE CONFIG 
# ADX Market Regime: hanya trade di trending market
ADX_TRENDING_THRESHOLD  = 22
ADX_RANGING_THRESHOLD   = 18
ADX_PERIOD              = 14

# Volatility Regime
VOL_HIGH_MULTIPLIER     = 2.5
VOL_LOW_MULTIPLIER      = 0.4
VOL_BASELINE_PERIOD     = 20

# Expected Value minimum
# Fee Bitget futures taker = 0.06% per side = 0.12% round trip
# Notional $70  fee = $0.084 per trade = 1.2% PnL
BITGET_FEE_PCT          = 0.0012  # 0.12% round trip fee
MIN_EXPECTED_VALUE      = 0.015   # NAIK: Minimum EV 1.5% setelah fee

# BTC Correlation Filter
# Kalau BTC bearish kuat, jangan LONG altcoin (semua altcoin ikut turun)
# Kalau BTC bullish kuat, jangan SHORT altcoin
BTC_BEAR_THRESHOLD      = -2.0    # BTC turun > 2% dalam 1 jam = bearish kuat
BTC_BULL_THRESHOLD      = 2.0     # BTC naik > 2% dalam 1 jam = bullish kuat
BTC_CACHE_TTL           = 120     # Cache BTC data 2 menit

# Consecutive Loss Tracker
# Kalau kalah 2x berturut-turut, pause 30 menit
# Ini mencegah bot terus masuk saat kondisi market sedang tidak favorable
CONSEC_LOSS_LIMIT       = 2       # Maksimal 2 loss berturut-turut
CONSEC_LOSS_PAUSE_MIN   = 30      # Pause 30 menit setelah 2x loss berturut-turut


#  MARKET INTELLIGENCE ENGINE 

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
    - EV = (0.55 x 0.08) - (0.45 x 0.015) = 0.044 - 0.0068 = 0.037 = 3.7% 

    - Score 42, no whale, ranging market -> P_win ~30%
    - EV = (0.30 x 0.08) - (0.70 x 0.015) = 0.024 - 0.0105 = 0.0135 = 1.35%  (tapi tipis)
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

    # Fee-adjusted EV: kurangi biaya fee Bitget dari EV
    # Fee 0.12% round trip = langsung mengurangi profit
    ev_gross = (p_win * tp_pct) - (p_loss * sl_pct)
    ev_net   = ev_gross - BITGET_FEE_PCT  # EV setelah fee
    return round(ev_net, 4)


def _get_btc_context() -> dict:
    """
    Ambil konteks BTC untuk correlation filter.
    BTC adalah market leader  pergerakannya mempengaruhi semua altcoin.

    Return:
      trend    : BULLISH / BEARISH / NEUTRAL
      change_1h: % perubahan harga BTC dalam 1 jam terakhir
      signal   : AVOID_LONG / AVOID_SHORT / NEUTRAL
                 AVOID_LONG  = BTC bearish kuat, jangan LONG altcoin
                 AVOID_SHORT = BTC bullish kuat, jangan SHORT altcoin
    """
    # Cache sederhana di module level
    if not hasattr(_get_btc_context, '_cache'):
        _get_btc_context._cache = {"ts": 0, "result": {"trend": "NEUTRAL", "change_1h": 0, "signal": "NEUTRAL"}}

    now = time.time()
    if now - _get_btc_context._cache["ts"] < BTC_CACHE_TTL:
        return _get_btc_context._cache["result"]

    try:
        # Ambil candle 1h BTC dari Bitget
        url = ("https://api.bitget.com/api/v2/mix/market/history-candles"
               "?symbol=BTCUSDT&granularity=1h&limit=3&productType=USDT-FUTURES")
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code != 200:
            return _get_btc_context._cache["result"]

        data = r.json().get('data', [])
        if len(data) < 2:
            return _get_btc_context._cache["result"]

        # Hitung % change dari 1 jam lalu ke sekarang
        close_now  = float(data[0][4])   # candle terbaru
        close_1h   = float(data[1][4])   # 1 jam lalu
        change_1h  = ((close_now - close_1h) / close_1h) * 100 if close_1h > 0 else 0

        # Tentukan trend dan signal
        if change_1h <= BTC_BEAR_THRESHOLD:
            trend  = "BEARISH"
            signal = "AVOID_LONG"   # BTC turun kuat, jangan LONG altcoin
        elif change_1h >= BTC_BULL_THRESHOLD:
            trend  = "BULLISH"
            signal = "AVOID_SHORT"  # BTC naik kuat, jangan SHORT altcoin
        else:
            trend  = "NEUTRAL"
            signal = "NEUTRAL"

        result = {"trend": trend, "change_1h": round(change_1h, 2), "signal": signal}
        _get_btc_context._cache = {"ts": now, "result": result}
        return result

    except Exception:
        return _get_btc_context._cache["result"]


# WHALE OBSERVER
class WhaleObserver:
    """Akumulasi dan evaluasi kandidat selama 15 menit cooldown."""

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
               side: str, tech: dict, adx: float = 25.0, ev: float = 0.01,
               vol_regime: str = "NORMAL"):
        """
        Catat satu observasi untuk koin ini.
        Setiap 10 detik selama cooldown, data terbaru disimpan.
        Di akhir cooldown, semua data ini dianalisis untuk pilih yang terbaik.
        """
        now = time.time()
        entry = (now, combined_score, tech_score, side, tech, adx, ev, vol_regime)
        self._watchlist[clean_base].append(entry)

        # OI baseline: simpan pertama kali, update setiap 5 menit
        # Ini mencegah baseline jadi stale setelah observasi panjang
        oi_now = tech.get('open_interest', 0)
        if clean_base not in self._oi_baseline:
            self._oi_baseline[clean_base] = oi_now
        elif oi_now > 0:
            # Update baseline setiap 5 menit (30 scan × 10 detik)
            entries = self._watchlist[clean_base]
            if len(entries) % 30 == 0:
                # Rolling baseline: rata-rata 5 observasi terakhir
                recent_oi = [e[4].get('open_interest', 0) for e in entries[-5:] if e[4].get('open_interest', 0) > 0]
                if recent_oi:
                    self._oi_baseline[clean_base] = sum(recent_oi) / len(recent_oi)

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

        #  0. ADX TREND STRENGTH BONUS (max 15 poin) 
        # Koin yang konsisten di trending market = sinyal lebih reliable
        adx_values = [e[5] for e in entries if len(e) > 5]
        if adx_values:
            avg_adx = sum(adx_values) / len(adx_values)
            if avg_adx >= 30:   future_score += 15  # Trend kuat konsisten
            elif avg_adx >= 25: future_score += 10
            elif avg_adx >= 22: future_score += 5
            # ADX < 22 = tidak ada bonus, tapi sudah lolos filter minimum

        #  0b. EV TREND BONUS (max 10 poin) 
        # EV yang naik dari scan ke scan = kondisi membaik
        ev_values = [e[6] for e in entries if len(e) > 6]
        if len(ev_values) >= 3:
            ev_slope = ev_values[-1] - ev_values[0]
            if ev_slope > 0.005:   future_score += 10  # EV naik signifikan
            elif ev_slope > 0.002: future_score += 5
            elif ev_slope < -0.005: future_score -= 8  # EV turun = kondisi memburuk
        #  1. OI SURGE (max 25 poin) 
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

        #  2. FUNDING SQUEEZE (max 20 poin) 
        # Funding negatif = shorts bayar longs = short squeeze imminent
        funding = latest_tech.get('funding_rate', 0)
        if side == "buy" and funding < FUNDING_SQUEEZE_THR:
            squeeze_strength = abs(funding) / abs(FUNDING_SQUEEZE_THR)
            future_score += min(20, squeeze_strength * 20)
            print(f"[FUTURE] {clean_base} SHORT SQUEEZE signal! Funding: {funding:.4f}")
        elif side == "sell" and funding > 0.001:
            # Funding positif tinggi = longs terlalu mahal = long squeeze
            future_score += min(15, (funding / 0.001) * 10)

        #  3. SCORE MOMENTUM (max 20 poin) 
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

        #  4. WHALE SIGNAL CONSISTENCY (max 15 poin) 
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

        #  5. LIQUIDITY HUNT (max 10 poin) 
        # Liquidity sweep berulang = stop hunt sebelum reversal
        liq_sweeps = sum(1 for e in entries if e[4].get('is_liquidity_sweep', False))
        liq_ratio  = liq_sweeps / len(entries)
        if liq_ratio >= 0.4:   future_score += 10  # 40%+ scan ada liq sweep
        elif liq_ratio >= 0.2: future_score += 5

        #  6. OBI CONSISTENCY (max 10 poin) 
        # Bid/Ask imbalance konsisten ke satu arah = buyer/seller dominance
        obis = [e[4].get('obi', 0) for e in entries]
        avg_obi = sum(obis) / len(obis) if obis else 0
        if side == "buy"  and avg_obi > 0.12:  future_score += 10
        elif side == "buy"  and avg_obi > 0.06: future_score += 5
        elif side == "sell" and avg_obi < -0.12: future_score += 10
        elif side == "sell" and avg_obi < -0.06: future_score += 5

        return round(future_score, 2)

    def get_best_candidate(self, open_bases: list, recently_exited: dict,
                           min_appearances: int = MIN_APPEARANCES,
                           require_signal: bool = False,
                           min_avg_score: float = MIN_AVG_SCORE) -> dict | None:
        # Pilih kandidat terbaik dari observasi. Return dict atau None.
        now = time.time()
        best = None
        best_final = 0.0

        session_label = "OFF-HOURS" if require_signal else "ACTIVE"
        print(f"\n[WHALE OBSERVER] Evaluasi {len(self._watchlist)} kandidat dari "
              f"{round((now - self._obs_start)/60, 1)} menit observasi "
              f"[{session_label} | min_appear:{min_appearances} min_score:{min_avg_score}]:")

        for clean_base, entries in self._watchlist.items():
            # Skip koin yang sudah ada posisi atau baru di-exit
            if clean_base in open_bases:
                continue
            if clean_base in recently_exited:
                mins_ago = round((now - recently_exited[clean_base]) / 60, 1)
                print(f"  [SKIP] {clean_base} baru exit {mins_ago} menit lalu")
                continue

            # Minimum appearances filter
            if len(entries) < min_appearances:
                continue

            # Hitung avg combined score
            avg_score = sum(e[1] for e in entries) / len(entries)
            if avg_score < min_avg_score:
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

            # Ambil tech dari observasi terakhir (HARUS sebelum has_predictive_signal)
            latest_tech = side_entries[-1][4]
            avg_tech_score = sum(e[2] for e in side_entries) / len(side_entries)

            # GUARD: jangan pilih koin yang tidak punya sinyal prediktif sama sekali
            # Future=0 + Rising=False = tidak ada bukti whale/momentum - terlalu spekulatif
            # Kecuali tidak ada kandidat lain (akan di-handle di bawah dengan flag)
            has_predictive_signal = future_sc > 0 or is_rising or \
                                    latest_tech.get('whale_signal') == 'WHALE_BUY' or \
                                    latest_tech.get('whale_signal') == 'WHALE_SELL'

            # OFF-HOURS: wajib ada sinyal prediktif kuat
            # Jam sepi = volume rendah = sinyal lemah lebih sering false
            if require_signal and not has_predictive_signal:
                print(f"  [SKIP-OFFHOURS] {clean_base} tidak ada sinyal prediktif di jam sepi.")
                continue

            print(f"  {clean_base:10s} | Side:{side:4s} | Appear:{appearances:2d}x | "
                  f"AvgScore:{avg_score:.1f} | Future:{future_sc:.1f} | Final:{final:.1f} "
                  f"{'' if is_rising else '  '} "
                  f"{'' if latest_tech.get('whale_signal')=='WHALE_BUY' else '  '}"
                  f"{'NO_SIGNAL' if not has_predictive_signal else ''}")

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
            print(f"\n[WHALE OBSERVER]  PILIHAN TERBAIK: {best['clean_base']} {best['side'].upper()}")
            print(f"  AvgScore:{best['avg_score']} | Future:{best['future_score']} | "
                  f"Final:{best['final_score']} | Muncul:{best['appearances']}x | "
                  f"Rising:{best['is_rising']}")
        else:
            print(f"[WHALE OBSERVER] Tidak ada kandidat yang memenuhi syarat.")

        return best


#  HELPER: HITUNG VWAP 
def _calc_vwap_dist(mark_price: float, symbol: str) -> float:
    """
    Hitung jarak harga dari VWAP intraday (8 jam terakhir = 32 candle 15m).
    
    Kenapa 32 candle (8 jam)?
    - VWAP 24 jam terlalu "rata" — tidak sensitif terhadap pergerakan hari ini
    - VWAP 8 jam lebih relevan untuk scalping 15m
    - Koin yang naik 10% hari ini akan terlihat "premium" di VWAP 8 jam
      tapi "neutral" di VWAP 24 jam — yang 8 jam lebih akurat
    
    Bitget candle format: [ts, open, high, low, close, vol, quoteVol]
    """
    try:
        url = (
            f"https://api.bitget.com/api/v2/mix/market/history-candles"
            f"?symbol={symbol}&granularity=15m&limit=32&productType=USDT-FUTURES"
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
            try:
                high  = float(c[2])
                low   = float(c[3])
                close = float(c[4])
                vol   = float(c[5])
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
        # Sanity check: VWAP dist > 15% tidak masuk akal untuk 8 jam
        if abs(dist) > 15:
            return 0.0
        return round(dist, 4)
    except Exception:
        return 0.0


#  HELPER: HITUNG RSI 
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


#  HELPER: DETECT VOLATILITY SPIKE 
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


#  CORE: MOMENTUM SCORING SYSTEM 
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

    # 3b. DEMAND/SUPPLY ZONE (max 20 poin)  lebih kuat dari Order Block biasa
    # Zona ini terbentuk dari konsolidasi institusi sebelum impulse move
    in_demand = tech.get('in_demand', False)
    in_supply = tech.get('in_supply', False)
    dz_strength = tech.get('demand_zone', {}).get('strength', 0)
    sz_strength = tech.get('supply_zone', {}).get('strength', 0)
    if side == "buy" and in_demand:
        score += 15 + min(5, dz_strength)  # max 20 poin, lebih kuat kalau lebih banyak candle
    if side == "sell" and in_supply:
        score += 15 + min(5, sz_strength)

    # 3c. FIBONACCI RETRACEMENT (max 15 poin)
    # Harga di level fib = institusi sering entry di sini
    if side == "buy"  and tech.get('at_fib_support', False):
        fib_lvl = tech.get('current_fib_level', 'NONE')
        bonus = 15 if fib_lvl in ('0.618', '0.786') else 10  # 0.618 dan 0.786 lebih kuat
        score += bonus
    if side == "sell" and tech.get('at_fib_resistance', False):
        fib_lvl = tech.get('current_fib_level', 'NONE')
        bonus = 15 if fib_lvl in ('0.618', '0.786') else 10
        score += bonus

    # 3d. STOP HUNT SIGNAL (max 15 poin)
    # Stop hunt = institusi sweep stop loss retail sebelum reversal
    hunt_strength = tech.get('hunt_strength', 0)
    if side == "buy"  and tech.get('bull_stop_hunt', False):
        score += 10 + min(5, hunt_strength * 2)  # max 15 poin
    if side == "sell" and tech.get('bear_stop_hunt', False):
        score += 10 + min(5, hunt_strength * 2)

    # 3g. INSTITUTIONAL LIQUIDITY GRAB (max 15 poin)
    # Rejection wick panjang = BlackRock style liquidity hunter footprint
    liq = tech.get('liquidity_grab', {})
    if side == "buy" and liq.get('bullish_grab'):
        score += 15
    if side == "sell" and liq.get('bearish_grab'):
        score += 15

    # 3e. VOLUME PROFILE / POC (max 10 poin, penalti -8)
    # Harga di bawah POC = discount zone (bagus untuk BUY)
    # Harga di atas POC = premium zone (bagus untuk SELL)
    price_vs_poc = tech.get('price_vs_poc', 'UNKNOWN')
    poc_dist = abs(tech.get('poc_distance_pct', 0))
    if side == "buy"  and price_vs_poc == "BELOW": score += min(10, poc_dist * 3)
    if side == "sell" and price_vs_poc == "ABOVE": score += min(10, poc_dist * 3)
    if side == "buy"  and price_vs_poc == "ABOVE" and poc_dist > 2: score -= 8
    if side == "sell" and price_vs_poc == "BELOW" and poc_dist > 2: score -= 8

    # 3f. HTF KEY LEVELS (penalti -15 kalau melawan level kritis)
    # Jangan LONG kalau harga dekat daily/weekly high (resistance kuat)
    # Jangan SHORT kalau harga dekat daily/weekly low (support kuat)
    htf_bias = tech.get('htf_level_bias', 'NEUTRAL')
    near_daily  = tech.get('near_daily_level', False)
    near_weekly = tech.get('near_weekly_level', False)
    if side == "buy"  and htf_bias == "RESISTANCE":
        score -= 15 if near_weekly else 8  # Weekly level lebih kuat
    if side == "sell" and htf_bias == "SUPPORT":
        score -= 15 if near_weekly else 8

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

    # 8. Binance Long/Short Ratio (Squeeze / Stop Hunt Predictor)
    # ls_ratio = None berarti API gagal — skip, jangan pakai data palsu
    ls_ratio = tech.get('ls_ratio', None)
    if ls_ratio is not None and ls_ratio > 0:
        if side == "buy":
            if ls_ratio < 0.6: score += 15    # Retail nge-short parah = Siap-siap Short Squeeze (Pump)
            elif ls_ratio > 2.5: score -= 15  # Retail terlalu banyak Long = Rawan Dump
        else:
            if ls_ratio > 2.5: score += 15    # Retail terlalu banyak Long = Siap-siap Long Squeeze (Dump)
            elif ls_ratio < 0.6: score -= 15  # Retail nge-short parah = Rawan Pump

    return max(0, min(100, score))


#  CORE: TENTUKAN SIDE & REASON 
def _determine_trade_side(tech: dict, rsi: float, vwap_dist: float,
                           market_sentiment: str) -> tuple[str | None, str, int]:
    """
    Return (side, reason, score) atau (None, '', 0) kalau tidak ada setup.
    Bi-directional: bisa long DAN short.

    ANTI-FALLING-KNIFE FILTER:
    - Tidak boleh BUY kalau 4h trend BEARISH (seperti SKYAI)
    - Tidak boleh SELL kalau 4h trend BULLISH
    - Exception: kalau ada stop hunt atau demand/supply zone yang sangat kuat
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

    #  HTF TREND FILTER 
    trend_1h = tech.get('trend_1h', 'NEUTRAL')
    trend_4h = tech.get('trend_4h', 'NEUTRAL')

    #  LONG SETUPS 
    long_candidates = []

    # Setup 1: Whale Accumulation
    if whale == 'WHALE_BUY' and vwap_dist < 0.5:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "WHALE ACCUMULATION"))

    # Setup 2: Bullish FVG
    if fvg == 'BULLISH_FVG' and rsi < 65 and vwap_dist < 0.5:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "BULLISH FVG"))

    # Setup 3: MSS Bullish
    if mss_b and (obi > 0 or rsi < 50):
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "MSS BULLISH"))

    # Setup 4: CHoCH + Liquidity Sweep
    if choch_b and liq:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "CHoCH REVERSAL"))

    # Setup 5: Bullish OB
    if ob == 'BULLISH_OB' and rsi < 55:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "BULLISH ORDER BLOCK"))

    # Setup 6: RSI Oversold
    if rsi <= 35 and vwap_dist < 1.0:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "RSI OVERSOLD"))

    #  SHORT SETUPS 
    short_candidates = []

    # Setup 1: Whale Distribution
    if whale == 'WHALE_SELL' and vwap_dist > 0.5:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "WHALE DISTRIBUTION"))

    # Setup 2: Bearish FVG
    if fvg == 'BEARISH_FVG' and rsi > 35 and vwap_dist > -0.5:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "BEARISH FVG"))

    # Setup 3: MSS Bearish
    if mss_s and (obi < 0 or rsi > 50):
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "MSS BEARISH"))

    # Setup 4: CHoCH + Liquidity Sweep
    if choch_s and liq:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "CHoCH BEARISH"))

    # Setup 5: Bearish OB
    if ob == 'BEARISH_OB' and rsi > 45:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "BEARISH ORDER BLOCK"))

    # Setup 6: RSI Overbought
    if rsi >= 65 and vwap_dist > -1.0:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "RSI OVERBOUGHT"))

    #  PILIH SETUP TERBAIK 
    all_candidates = [("buy", s, r) for s, r in long_candidates] + \
                     [("sell", s, r) for s, r in short_candidates]

    if not all_candidates:
        return None, "", 0

    all_candidates.sort(key=lambda x: x[1], reverse=True)
    best_side, best_score, best_reason = all_candidates[0]

    # HTF alignment bonus
    if best_side == "buy"  and trend_4h == "BULLISH": best_score = min(100, best_score + 10)
    if best_side == "sell" and trend_4h == "BEARISH": best_score = min(100, best_score + 10)

    return best_side, best_reason, best_score


#  CORE: HITUNG TP/SL BERBASIS PnL TARGET 
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


#  MAIN ENGINE 
def run_crypto_engine():
    """
    CRYPTO SCALPER v5.1 - Direct Execution Mode
    =============================================
    Restored to profitable May 5 logic:
    - Scan top 20 coins every 10 seconds
    - If coin passes filters -> execute immediately (no 15-min observation)
    - Session filter: 08:00-22:00 WIB only (hard stop off-hours)
    - Cooldown: 120 seconds between trades
    """
    executor = BitgetExecutor()

    from database import check_pending_trades, get_performance_stats
    from sentiment import get_market_news_digest

    print("[CRYPTO SCALPER v5.1] Direct Execution Mode AKTIF!", flush=True)
    print(f"  Strategy : 1 trade terbaik | {LEVERAGE}x leverage", flush=True)
    print(f"  Cooldown : {COOLDOWN_AFTER_TRADE}s antara trade", flush=True)
    print(f"  Session  : 08:00-22:00 WIB (01:00-15:00 UTC)", flush=True)

    try:
        print("[SYSTEM] Sinkronisasi awal dengan Bitget...", flush=True)
        executor.sync_state_with_exchange()
        print("[SYSTEM] Sinkronisasi Bitget SUKSES.", flush=True)
    except Exception as e:
        print(f"[SYSTEM WARNING] Gagal sinkronisasi awal: {e}", flush=True)

    last_exec_time      = 0
    last_news_report    = 0
    last_global_report  = 0
    last_deepseek_report = 0
    _dxy_cache          = {"trend": "NEUTRAL", "ts": 0}
    _recently_exited    = {}
    _loss_tracker       = {}
    _consec_losses      = 0
    _consec_pause_until = 0

    while True:
        try:
            now = time.time()
            if int(now) % 60 < 10:
                print("[CRYPTO ENGINE] Heartbeat: Loop is running...", flush=True)

            #  1. MANAGE EXISTING POSITIONS
            executor.manage_open_positions()
            check_pending_trades()

            #  2. NEWS VELOCITY (setiap 10 menit)
            if now - last_news_report > NEWS_REPORT_INTERVAL:
                digest = get_market_news_digest()
                print(f"[NEWS VELOCITY] Sentiment: {digest['sentiment']} | Top: {digest['crypto_top']}", flush=True)
                last_news_report = now

            #  3. GLOBAL CONTEXT (setiap 5 menit)
            if now - last_global_report > GLOBAL_REPORT_INTERVAL:
                global_ctx = get_global_market_data()
                print(f"[GLOBAL] {global_ctx}")
                last_global_report = now

            #  4. CIRCUIT BREAKER
            stats     = get_performance_stats('crypto')
            daily_pnl = stats.get('daily_pnl', 0)
            if daily_pnl < DAILY_LOSS_LIMIT_PCT:
                print(f"[CIRCUIT BREAKER] Daily loss {daily_pnl}% melewati limit. Standby 30 menit.")
                time.sleep(1800)
                continue

            #  4b. CONSECUTIVE LOSS PAUSE
            if now < _consec_pause_until:
                remaining = round((_consec_pause_until - now) / 60, 1)
                if int(now) % 60 < 10:
                    print(f"[CONSEC LOSS] Pause aktif. {remaining} menit lagi.")
                time.sleep(SCAN_INTERVAL)
                continue

            #  4c. SESSION FILTER — OFF-HOURS REQUIREMENT (Strict Mode)
            # DATA: Jam 22:00-08:00 WIB volume rendah. Kita izinkan trade hanya jika sinyal SANGAT KUAT.
            import datetime as _dt
            utc_hour = _dt.datetime.utcnow().hour
            is_off_hours = not (CRYPTO_SESSION_START_UTC <= utc_hour < CRYPTO_SESSION_END_UTC)
            
            if is_off_hours:
                if int(now) % 300 < 10:
                    wib_hour = (utc_hour + 7) % 24
                    print(f"[CRYPTO SESSION] Off-hours ({wib_hour:02d}:xx WIB). Strict mode active.")
            
            # Pass is_off_hours to the evaluator

            #  5. POSITION CHECK
            positions  = executor.get_all_positions()
            open_count = len(positions) if isinstance(positions, list) else 0
            open_bases = [executor._clean_symbol(p['symbol']) for p in positions] \
                         if isinstance(positions, list) else []

            if open_count >= MAX_POSITIONS:
                print(f"[LIMIT] {open_count}/{MAX_POSITIONS} posisi aktif. Manage existing.")
                time.sleep(SCAN_INTERVAL)
                continue

            #  6. COOLDOWN CHECK
            elapsed_since_trade = now - last_exec_time
            cooldown_remaining  = COOLDOWN_AFTER_TRADE - elapsed_since_trade
            if cooldown_remaining > 0:
                if int(now) % 30 < 10:
                    print(f"[COOLDOWN] {round(cooldown_remaining)}s remaining")
                time.sleep(SCAN_INTERVAL)
                continue

            #  7. BERSIHKAN recently_exited + TRACK LOSSES
            _recently_exited = {k: v for k, v in _recently_exited.items() if now - v < 1800}
            try:
                from shared_state import state as _state
                if hasattr(_state, 'recently_exited'):
                    for k, v in list(_state.recently_exited.items()):
                        if now - v < 1800:
                            if k not in _recently_exited:
                                last_pnl = getattr(_state, 'exit_pnl', {}).get(k, -1.0)
                                if last_pnl < 0:
                                    if k not in _loss_tracker:
                                        _loss_tracker[k] = []
                                    _loss_tracker[k].append(v)
                                    _consec_losses += 1
                                    print(f"[CONSEC LOSS] Loss ke-{_consec_losses} ({k}) | PnL: {last_pnl}%")
                                    if _consec_losses >= CONSEC_LOSS_LIMIT:
                                        pause_minutes = CONSEC_LOSS_PAUSE_MIN * (2 ** (_consec_losses - CONSEC_LOSS_LIMIT))
                                        pause_minutes = min(pause_minutes, 240)
                                        _consec_pause_until = now + (pause_minutes * 60)
                                        print(f"[CONSEC LOSS] {_consec_losses}x loss! Pause {pause_minutes} menit.")
                                        _consec_losses = CONSEC_LOSS_LIMIT
                                else:
                                    print(f"[WIN TRACKER] {k} take profit ({last_pnl}%)! Reset consec loss.")
                                    _consec_losses = 0
                            _recently_exited[k] = v
                        else:
                            del _state.recently_exited[k]
            except Exception:
                pass

            #  8. MARKET SENTIMENT & DXY
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

            #  9. SCAN & EVALUATE CANDIDATES PARALLEL (DIRECT MODE)
            raw_data   = fetch_all_tickers()
            candidates = analyze_and_sort(raw_data)

            if not candidates:
                if int(now) % 60 < 10:
                    print("[CRYPTO WARNING] Tidak ada kandidat. Retrying...")
                time.sleep(SCAN_INTERVAL)
                continue

            # Bersihkan loss tracker
            cutoff = now - (REPEAT_LOSS_BLACKLIST_HOURS * 3600)
            for base in list(_loss_tracker.keys()):
                _loss_tracker[base] = [t for t in _loss_tracker[base] if t > cutoff]
                if not _loss_tracker[base]:
                    del _loss_tracker[base]
            _repeat_losers = {b for b, ts in _loss_tracker.items() if len(ts) >= REPEAT_LOSS_MAX_COUNT}

            btc_ctx = _get_btc_context()
            print(f"[CRYPTO ENGINE] Scan {min(20, len(candidates))} koin | "
                  f"Sentiment: {market_sentiment} | DXY: {dxy_trend} | "
                  f"BTC: {btc_ctx['trend']} ({btc_ctx['change_1h']:+.1f}%/1h)", flush=True)

            #  SUB-FUNCTION FOR PARALLEL EVALUATION
            def evaluate_coin(coin, off_hours=False):
                symbol = coin.get('symbol', '')
                clean_base = executor._clean_symbol(symbol)

                # Fast filters
                if clean_base in open_bases:                                          return None
                if clean_base in ('BTC', 'ETH'):                                      return None
                if any(x in clean_base for x in ('USD','DAI','BUSD','TUSD','WBTC','WETH')): return None
                if clean_base in _recently_exited:                                    return None
                if clean_base in _repeat_losers:                                      return None

                pump_sc = float(coin.get('pump_score', 0))
                dump_sc = float(coin.get('dump_score', 0))
                best_sc = max(pump_sc, dump_sc)
                if best_sc < MIN_PUMP_SCORE:
                    return None

                # Heavy indicators (API calls)
                tech = get_technical_indicators(symbol)
                if not tech: return None

                mark_price = tech.get('mark_price', 0) or float(coin.get('lastPrice', 0))
                rsi       = tech.get('rsi', 50)
                vwap_dist = tech.get('vwap_dist', 0.0)

                side, reason, tech_score = _determine_trade_side(tech, rsi, vwap_dist, market_sentiment)
                combined_score = round((pump_sc * 0.5) + (tech_score * 0.5))

                # APPLY STRICT OFF-HOURS LOGIC
                current_min_momentum = MIN_MOMENTUM_SCORE
                current_min_tech = MIN_TECH_SCORE
                
                if off_hours:
                    current_min_momentum = 65  # Sangat ketat (Mei 6: 60)
                    current_min_tech = 45      # Tech harus solid
                    
                    # Syarat tambahan: Harus ada sinyal institusi yang kuat
                    has_whale = tech.get('whale_signal') in ('WHALE_BUY', 'WHALE_SELL')
                    has_liq = tech.get('liquidity_grab', {}).get('bullish_grab') or tech.get('liquidity_grab', {}).get('bearish_grab')
                    has_hunt = tech.get('bull_stop_hunt') or tech.get('bear_stop_hunt')
                    
                    if not (has_whale or has_liq or has_hunt):
                        return None

                if side is None or combined_score < current_min_momentum or tech_score < current_min_tech:
                    return None

                # BTC correlation filter
                btc_signal = btc_ctx.get("signal", "NEUTRAL")
                if (btc_signal == "AVOID_LONG" and side == "buy") or (btc_signal == "AVOID_SHORT" and side == "sell"):
                    return None

                return {
                    "symbol": symbol, "clean_base": clean_base, "side": side,
                    "reason": reason, "score": combined_score, "tech": tech,
                    "mark_price": mark_price, "rsi": rsi, "vwap_dist": vwap_dist
                }

            # Run parallel evaluation
            results = []
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = [pool.submit(evaluate_coin, c, is_off_hours) for c in candidates[:20]]
                for f in as_completed(futures):
                    res = f.result()
                    if res: results.append(res)

            # Sort by score and execute the best one
            if results:
                results.sort(key=lambda x: x['score'], reverse=True)
                top = results[0]
                
                clean_base = top['clean_base']
                symbol     = top['symbol']
                side       = top['side']
                combined_score = top['score']
                reason     = top['reason']
                mark_price = top['mark_price']
                tech       = top['tech']
                rsi        = top['rsi']
                vwap_dist  = top['vwap_dist']

                # Hitung TP/SL
                tp, sl = _calc_tp_sl(mark_price, side, tech)

                # Hitung size
                amount = executor.get_max_available(symbol, leverage=LEVERAGE)
                if amount > 0:
                    print(f"\n{'='*60}")
                    print(f"[SCALPER v5.1] {clean_base} {side.upper()} | Score: {combined_score}/100")
                    print(f"  Reason : {reason}")
                    print(f"  Price  : {mark_price} | RSI: {rsi} | VWAP: {vwap_dist}%")
                    print(f"  TP: {tp} | SL: {sl} | Amount: {amount}")
                    print(f"{'='*60}\n")

                    success, order = executor.place_order(symbol, side, amount, tp=tp, sl=sl, leverage=LEVERAGE)
                    if success:
                        from database import log_trade
                        log_trade(symbol, mark_price, tp, sl, side=side, score=combined_score, reason=reason)
                        last_exec_time = time.time()
                        _consec_losses = 0
                        print(f"[TRADE LOGGED] {clean_base} {side.upper()} @ {mark_price}")
                    else:
                        print(f"[ORDER FAILED] {clean_base}: {order}")
                else:
                    print(f"[MARGIN GUARD] Insufficient margin for {clean_base}.")

            time.sleep(SCAN_INTERVAL)

        except Exception as e:
            print(f"[ENGINE ERROR] {e}")
            time.sleep(30)
