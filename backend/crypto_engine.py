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
    get_retail_sentiment, detect_institutional_flow,
    detect_institutional_liquidity_grab
)
from sentiment import get_crypto_news, get_global_market_data
from ai_model import analyze_and_sort
from database import log_trade
from bitget_executor import BitgetExecutor

#  KONFIGURASI 
MAX_POSITIONS        = 1      # FOKUS: 1 trade saja
SCAN_INTERVAL        = 10     # Scan setiap 10 detik
COOLDOWN_AFTER_TRADE = 60     # INSTANT SNIPER: Hanya 1 menit cooldown setelah trade tutup
NEWS_REPORT_INTERVAL = 600
GLOBAL_REPORT_INTERVAL = 300
LEVERAGE             = 10
MIN_MOMENTUM_SCORE   = 60     # NAIK DRASTIS: Hanya ambil setup A+
MIN_TECH_SCORE       = 45     # NAIK DRASTIS
MIN_PUMP_SCORE       = 35     # NAIK DRASTIS

#  WHALE OBSERVER CONFIG 
MIN_APPEARANCES      = 1      # EKSEKUSI INSTAN: Begitu lolos filter ketat, langsung sikat
MIN_AVG_SCORE        = 60     # NAIK DRASTIS
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
        Setiap 10 detik selama 15 menit, data terbaru disimpan.
        Di akhir cooldown, semua data ini dianalisis untuk pilih yang terbaik.
        """
        now = time.time()
        entry = (now, combined_score, tech_score, side, tech, adx, ev, vol_regime)
        self._watchlist[clean_base].append(entry)

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

            # Ambil tech dari observasi terakhir
            latest_tech = side_entries[-1][4]
            avg_tech_score = sum(e[2] for e in side_entries) / len(side_entries)

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
    ls_ratio = tech.get('ls_ratio', 1.0)
    if ls_ratio > 0:
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

    # Anti-falling-knife: jangan BUY kalau 4h bearish KECUALI ada reversal signal kuat
    # Reversal signal kuat = stop hunt + demand zone + whale buy
    has_strong_reversal_buy = (
        tech.get('bull_stop_hunt', False) or
        tech.get('in_demand', False) or
        whale == 'WHALE_BUY'
    )
    has_strong_reversal_sell = (
        tech.get('bear_stop_hunt', False) or
        tech.get('in_supply', False) or
        whale == 'WHALE_SELL'
    )

    # Cek Kondisi Candle Saat Ini (Mencegah beli di tengah terjun bebas)
    falling_knife = tech.get('falling_knife', False)
    flying_rocket = tech.get('flying_rocket', False)

    #  SMC PROTECTION (HARAM RULE) 
    # Jangan pernah ngeshort di area Demand (Support) karena pasti mantul
    # Jangan pernah ngelong di area Supply (Resistance) karena pasti rontok
    in_demand = tech.get('in_demand', False)
    in_supply = tech.get('in_supply', False)

    # Kalau 4h bearish dan tidak ada reversal signal = skip BUY
    # ATAU kalau harga masih terjun bebas (pisau jatuh) = HARAM BUY!
    # ATAU harga nyentuh Supply Zone = HARAM BUY!
    block_buy  = (trend_4h == 'BEARISH' and not has_strong_reversal_buy) or falling_knife or in_supply
    
    # Kalau 4h bullish dan tidak ada reversal signal = skip SELL
    # ATAU kalau harga masih meroket = HARAM SELL!
    # ATAU harga nyentuh Demand Zone = HARAM SELL!
    block_sell = (trend_4h == 'BULLISH' and not has_strong_reversal_sell) or flying_rocket or in_demand

    # Kalau 1h juga berlawanan = block lebih ketat
    if trend_1h == 'BEARISH' and trend_4h == 'BEARISH':
        block_buy = True   # Double bearish = tidak ada BUY sama sekali
    if trend_1h == 'BULLISH' and trend_4h == 'BULLISH':
        block_sell = True  # Double bullish = tidak ada SELL sama sekali

    #  LONG SETUPS 
    long_candidates = []

    if block_buy:
        # Skip semua long setup kalau 4h bearish tanpa reversal signal
        pass
    else:
        # Setup 1: Whale Accumulation + Discount Zone
        if whale == 'WHALE_BUY' and vwap_dist < 0.5:
            s = _score_candidate(tech, rsi, vwap_dist, "buy")
            long_candidates.append((s, "WHALE ACCUMULATION + DISCOUNT ZONE"))

    # Setup 2: Bullish FVG Re-entry
    if not block_buy and fvg == 'BULLISH_FVG' and rsi < 60:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "BULLISH FVG RE-ENTRY"))

    # Setup 3: MSS Bullish Breakout
    if not block_buy and mss_b and obi > 0.05:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "MSS BULLISH BREAKOUT"))

    # Setup 4: CHoCH + Liquidity Sweep
    if not block_buy and choch_b and liq and rsi < 55:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "CHoCH REVERSAL + LIQUIDITY SWEEP"))

    # Setup 5: Bullish OB + Oversold RSI
    if not block_buy and ob == 'BULLISH_OB' and rsi < 45:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "BULLISH ORDER BLOCK + OVERSOLD RSI"))

    # Setup 6: RSI Oversold Recovery  HANYA kalau 1h tidak bearish
    # Ini yang bikin SKYAI masuk  RSI oversold tapi 4h bearish
    if not block_buy and 28 <= rsi <= 42 and vwap_dist < 2.0 and trend_1h != 'BEARISH':
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "RSI OVERSOLD RECOVERY"))

    # Setup 7: Momentum Breakout
    if not block_buy and -3.0 <= vwap_dist <= -0.3 and (choch_b or mss_b or fvg == 'BULLISH_FVG'):
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "MOMENTUM BREAKOUT FROM DISCOUNT"))

    # Setup 8: Demand Zone Entry  boleh masuk meski 4h bearish kalau zona kuat
    if tech.get('in_demand', False):
        dz = tech.get('demand_zone', {})
        # Kalau 4h bearish, butuh zona yang lebih kuat (strength >= 3)
        min_strength = 3 if trend_4h == 'BEARISH' else 1
        if dz.get('strength', 0) >= min_strength:
            s = _score_candidate(tech, rsi, vwap_dist, "buy")
            long_candidates.append((s, f"DEMAND ZONE ENTRY (strength:{dz.get('strength',0)})"))

    #  SHORT SETUPS 
    short_candidates = []

    # Setup 1: Whale Distribution + Premium Zone
    if not block_sell and whale == 'WHALE_SELL' and vwap_dist > 0.5:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "WHALE DISTRIBUTION + PREMIUM ZONE"))

    # Setup 2: Bearish FVG Rejection
    if not block_sell and fvg == 'BEARISH_FVG' and rsi > 45:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "BEARISH FVG REJECTION"))

    # Setup 3: MSS Bearish Breakdown
    if not block_sell and mss_s and obi < -0.05:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "MSS BEARISH BREAKDOWN"))

    # Setup 4: CHoCH + Liquidity Sweep Bearish
    if not block_sell and choch_s and liq and rsi > 50:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "CHoCH BEARISH + LIQUIDITY SWEEP"))

    # Setup 5: Bearish OB + Overbought RSI
    if not block_sell and ob == 'BEARISH_OB' and rsi > 60:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "BEARISH ORDER BLOCK + OVERBOUGHT RSI"))

    # Setup 6: RSI Overbought Rejection  HANYA kalau 1h tidak bullish
    if not block_sell and 68 <= rsi <= 85 and vwap_dist > 1.0 and trend_1h != 'BULLISH':
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "RSI OVERBOUGHT REJECTION"))

    # Setup 7: Bearish Momentum
    if not block_sell and 1.0 <= vwap_dist <= 5.0 and (choch_s or mss_s or fvg == 'BEARISH_FVG'):
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "BEARISH MOMENTUM FROM PREMIUM"))

    # Setup 8: Supply Zone Entry  boleh masuk meski 4h bullish kalau zona kuat
    if tech.get('in_supply', False):
        sz = tech.get('supply_zone', {})
        min_strength = 3 if trend_4h == 'BULLISH' else 1
        if sz.get('strength', 0) >= min_strength:
            s = _score_candidate(tech, rsi, vwap_dist, "sell")
            short_candidates.append((s, f"SUPPLY ZONE ENTRY (strength:{sz.get('strength',0)})"))

    #  PILIH SETUP TERBAIK 
    all_candidates = [("buy", s, r) for s, r in long_candidates] + \
                     [("sell", s, r) for s, r in short_candidates]

    if not all_candidates:
        # Log kenapa tidak ada setup
        if block_buy and block_sell:
            pass  # Kedua arah di-block
        elif block_buy:
            pass  # BUY di-block karena 4h bearish
        elif block_sell:
            pass  # SELL di-block karena 4h bullish
        return None, "", 0

    # Sort by score descending
    all_candidates.sort(key=lambda x: x[1], reverse=True)
    best_side, best_score, best_reason = all_candidates[0]

    # Sentiment alignment bonus/penalty
    if best_side == "buy"  and market_sentiment == "BULLISH":  best_score = min(100, best_score + 5)
    if best_side == "sell" and market_sentiment == "BEARISH":  best_score = min(100, best_score + 5)
    if best_side == "buy"  and market_sentiment == "BEARISH":  best_score = max(0,   best_score - 8)
    if best_side == "sell" and market_sentiment == "BULLISH":  best_score = max(0,   best_score - 8)

    # HTF alignment bonus
    if best_side == "buy"  and trend_4h == "BULLISH": best_score = min(100, best_score + 8)
    if best_side == "sell" and trend_4h == "BEARISH": best_score = min(100, best_score + 8)
    if best_side == "buy"  and trend_1h == "BULLISH": best_score = min(100, best_score + 5)
    if best_side == "sell" and trend_1h == "BEARISH": best_score = min(100, best_score + 5)

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
    [CRYPTO SCALPER v9.0] - Whale Observer Mode.

    FLOW:
    
      FASE OBSERVASI (15 menit setelah trade / startup)      
       Setiap 10 detik:                                     
        - Scan top 20 koin                                   
        - Evaluasi setiap koin (pump + SMC + future signals) 
        - Catat ke WhaleObserver watchlist                   
       Di akhir 15 menit:                                   
        - Pilih koin dengan final_score tertinggi            
        - Eksekusi dengan full confidence                    
    
    """
    executor = BitgetExecutor()
    observer  = WhaleObserver()

    from database import check_pending_trades, get_performance_stats
    from sentiment import get_market_news_digest

    print("[CRYPTO SCALPER v9.0] Whale Observer Mode AKTIF!", flush=True)
    print(f"  Strategy : 1 trade terbaik | {LEVERAGE}x leverage", flush=True)
    print(f"  Cooldown : {COOLDOWN_AFTER_TRADE//60} menit observasi aktif", flush=True)
    print(f"  Min appear: {MIN_APPEARANCES}x dalam cooldown window", flush=True)

    last_exec_time      = 0
    last_news_report    = 0
    last_global_report  = 0
    last_deepseek_report = 0   # DeepSeek analysis setiap 15 menit
    _dxy_cache          = {"trend": "NEUTRAL", "ts": 0}
    _recently_exited    = {}  # {clean_base: exit_timestamp}
    _loss_tracker       = {}  # {clean_base: [timestamps]}
    _consec_losses      = 0
    _consec_pause_until = 0

    # Mulai observasi langsung dari startup
    observer.reset()

    while True:
        try:
            #  1. MANAGE EXISTING POSITIONS 
            executor.manage_open_positions()
            check_pending_trades()

            now = time.time()

            #  2. NEWS VELOCITY (setiap 10 menit) 
            if now - last_news_report > NEWS_REPORT_INTERVAL:
                digest = get_market_news_digest()
                print(f"[NEWS VELOCITY] Sentiment: {digest['sentiment']} | "
                      f"Top: {digest['crypto_top']}", flush=True)
                last_news_report = now

            #  2b. DEEPSEEK AI ANALYSIS (setiap 15 menit) 
            if now - last_deepseek_report > 900:
                try:
                    from ai_model import analyze_market_data
                    raw_data    = fetch_all_tickers()
                    candidates  = analyze_and_sort(raw_data)
                    top5        = candidates[:5] if candidates else []
                    if top5:
                        top5_simple = [{
                            "symbol":  c.get("symbol"),
                            "change":  round(float(c.get("priceChangePercent", 0)), 2),
                            "volume":  round(float(c.get("quoteVolume", 0)) / 1_000_000, 1),
                            "pump":    round(float(c.get("pump_score", 0)), 1),
                            "dump":    round(float(c.get("dump_score", 0)), 1),
                        } for c in top5]
                        print("[DEEPSEEK] Requesting AI analysis...", flush=True)
                        result = analyze_market_data(str(top5_simple))
                        print("[DEEPSEEK ANALYSIS]", flush=True)
                        for line in str(result).split("\n"):
                            if line.strip():
                                print(f"  {line}", flush=True)
                except Exception as e:
                    print(f"[DEEPSEEK ERROR] {e}", flush=True)
                last_deepseek_report = now

            #  3. GLOBAL CONTEXT (setiap 5 menit) 
            if now - last_global_report > GLOBAL_REPORT_INTERVAL:
                global_ctx = get_global_market_data()
                print(f"[GLOBAL] {global_ctx}")
                last_global_report = now

            #  4. CIRCUIT BREAKER 
            stats     = get_performance_stats('crypto')
            daily_pnl = stats.get('daily_pnl', 0)
            if daily_pnl < DAILY_LOSS_LIMIT_PCT:
                print(f"[CIRCUIT BREAKER] Daily loss {daily_pnl}% melewati limit "
                      f"{DAILY_LOSS_LIMIT_PCT}%. Standby 30 menit.")
                time.sleep(1800)
                continue

            #  4c. CONSECUTIVE LOSS PAUSE 
            # Kalau kalah 2x berturut-turut, pause 30 menit
            # Ini mencegah bot terus masuk saat kondisi market sedang tidak favorable
            if now < _consec_pause_until:
                remaining = round((_consec_pause_until - now) / 60, 1)
                if int(now) % 60 < 10:
                    print(f"[CONSEC LOSS] Pause aktif. {remaining} menit lagi. "
                          f"({_consec_losses}x loss berturut-turut)")
                time.sleep(SCAN_INTERVAL)
                continue

            # NEWS CALENDAR CHECK
            _news_cal_block = False
            try:
                from news_sniper import get_upcoming_high_impact_events
                cal = get_upcoming_high_impact_events()
                if cal.get("recommendation") == "AVOID_NEW_TRADES":
                    _news_cal_block = True
                    if int(now) % 60 < 10:
                        events = cal.get("events", [])
                        ev_str = events[0]["title"] if events else "Unknown"
                        print(f"[NEWS CALENDAR] '{ev_str}' dalam 30 menit! Observasi jalan, eksekusi di-block.", flush=True)
            except Exception:
                pass


            #  4b. SESSION FILTER  off-hours diperketat, bukan di-skip 
            import datetime as _dt
            utc_hour = _dt.datetime.utcnow().hour
            wib_hour = (utc_hour + 7) % 24
            _is_active_session = (CRYPTO_SESSION_START_UTC <= utc_hour < CRYPTO_SESSION_END_UTC)

            if _is_active_session:
                # JAM AKTIF (08:00-22:00 WIB): syarat normal
                _session_min_score    = MIN_MOMENTUM_SCORE
                _session_min_avg      = MIN_AVG_SCORE
                _session_min_ev       = MIN_EXPECTED_VALUE
                _session_need_signal  = True                     # WAJIB ada sinyal institusi (Whale/OBI/Funding)
                _session_min_appear   = MIN_APPEARANCES          # 1x
            else:
                # JAM OFF-HOURS (22:00-08:00 WIB): syarat SANGAT KETAT
                # Volume rendah, spread tinggi, sinyal palsu banyak
                _session_min_score    = 70    # Sangat ketat
                _session_min_avg      = 70    # Sangat ketat
                _session_min_ev       = 0.025 # EV harus sangat tinggi
                _session_need_signal  = True  # WAJIB ada whale/OI/funding signal
                _session_min_appear   = 1     # Instan
                if int(now) % 300 < 10:
                    print(f"[CRYPTO SESSION] Off-hours ({wib_hour:02d}:xx WIB). "
                          f"Syarat diperketat: score>={_session_min_score} "
                          f"EV>={_session_min_ev} wajib_signal={_session_need_signal}")

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
            # ADAPTIVE COOLDOWN: lebih pendek saat trending kuat, lebih panjang saat ranging
            # ADX tinggi = trending = banyak setup bagus = cooldown lebih pendek
            # ADX rendah = ranging = sedikit setup = cooldown lebih panjang
            try:
                # Karena kita ganti ke instant sniper, adaptive cooldown maksimal 2 menit
                from data_fetcher import fetch_all_tickers as _ft
                btc_ctx_now = _get_btc_context()
                btc_change  = abs(btc_ctx_now.get('change_1h', 0))
                if btc_change > 3.0:
                    adaptive_cooldown = 30  # Sangat volatile, cooldown 30 detik
                elif btc_change > 1.5:
                    adaptive_cooldown = 60  # Cooldown 1 menit
                else:
                    adaptive_cooldown = 120 # Market ranging, cooldown 2 menit
            except Exception:
                adaptive_cooldown = COOLDOWN_AFTER_TRADE

            cooldown_remaining  = adaptive_cooldown - elapsed_since_trade
            in_cooldown         = cooldown_remaining > 0

            if in_cooldown and int(now) % 60 < 10:
                print(f"[COOLDOWN] {round(cooldown_remaining/60,1)} menit lagi "
                      f"(adaptive: {adaptive_cooldown//60} menit | BTC: {btc_ctx_now.get('change_1h',0):+.1f}%/1h)")

            #  7. BERSIHKAN recently_exited + TRACK LOSSES 
            _recently_exited = {k: v for k, v in _recently_exited.items()
                                 if now - v < 1800}
            try:
                from shared_state import state as _state
                if hasattr(_state, 'recently_exited'):
                    for k, v in list(_state.recently_exited.items()):
                        if now - v < 1800:
                            # Koin baru di-exit - cek apakah profit atau loss
                            if k not in _recently_exited:
                                last_pnl = getattr(_state, 'exit_pnl', {}).get(k, -1.0)
                                
                                if last_pnl < 0:
                                    if k not in _loss_tracker:
                                        _loss_tracker[k] = []
                                    _loss_tracker[k].append(v)
                                    loss_count = len([t for t in _loss_tracker[k]
                                                      if t > now - REPEAT_LOSS_BLACKLIST_HOURS * 3600])
                                    if loss_count >= REPEAT_LOSS_MAX_COUNT:
                                        print(f"[LOSS TRACKER] {k} kena SL {loss_count}x dalam "
                                              f"{REPEAT_LOSS_BLACKLIST_HOURS}h. Blacklist sementara.")

                                    #  CONSECUTIVE LOSS TRACKING 
                                    _consec_losses += 1
                                    print(f"[CONSEC LOSS] Loss ke-{_consec_losses} ({k}) | PnL: {last_pnl}%. "
                                          f"Limit: {CONSEC_LOSS_LIMIT}x")
                                    if _consec_losses >= CONSEC_LOSS_LIMIT:
                                        _consec_pause_until = now + (CONSEC_LOSS_PAUSE_MIN * 60)
                                        print(f"[CONSEC LOSS] {_consec_losses}x loss berturut-turut! "
                                              f"Pause {CONSEC_LOSS_PAUSE_MIN} menit. "
                                              f"Market sedang tidak favorable.")
                                        _consec_losses = 0  # Reset counter setelah pause
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

            #  9. SCAN & OBSERVASI 
            raw_data   = fetch_all_tickers()
            candidates = analyze_and_sort(raw_data)

            if not candidates:
                if int(now) % 60 < 10:
                    print(f"[CRYPTO WARNING] Tidak ada kandidat (API Bitget rate limit/kosong). Retrying...")
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

            #  9a. SCAN SEMUA KANDIDAT & CATAT KE OBSERVER 
            # Log ringkas: berapa koin yang di-scan dan berapa yang lolos
            top_candidates = candidates[:20]
            btc_ctx = _get_btc_context()
            print(f"[CRYPTO ENGINE] Scan {len(top_candidates)} koin | "
                  f"Watchlist: {len(observer._watchlist)} | "
                  f"Obs: {round((now - observer._obs_start)/60, 1)}m | "
                  f"Sentiment: {market_sentiment} | DXY: {dxy_trend} | "
                  f"BTC: {btc_ctx['trend']} ({btc_ctx['change_1h']:+.1f}%/1h)")

            scan_count   = 0
            skip_reasons = {}  # track kenapa koin di-skip
            for coin in top_candidates:
                symbol     = coin.get('symbol', '')
                clean_base = executor._clean_symbol(symbol)

                # Filter dasar
                if clean_base in open_bases:                          continue
                if clean_base in ('BTC', 'ETH'):                      continue
                if any(x in clean_base for x in ('USD','DAI','BUSD','TUSD','WBTC','WETH')): continue
                if clean_base in _recently_exited:                    continue
                if clean_base in _repeat_losers:                      continue

                pump_sc = float(coin.get('pump_score', 0))
                dump_sc = float(coin.get('dump_score', 0))
                best_sc = max(pump_sc, dump_sc)
                if best_sc < MIN_PUMP_SCORE:
                    skip_reasons['low_pump'] = skip_reasons.get('low_pump', 0) + 1
                    continue
                # Ambil indikator teknikal
                tech = get_technical_indicators(symbol)
                if not tech:
                    skip_reasons['no_tech'] = skip_reasons.get('no_tech', 0) + 1
                    continue

                mark_price = tech.get('mark_price', 0) or float(coin.get('lastPrice', 0))
                if mark_price == 0:                                    continue

                rsi       = tech.get('rsi', _calc_rsi(symbol))
                vwap_dist = _calc_vwap_dist(mark_price, symbol)

                side, reason, tech_score = _determine_trade_side(
                    tech, rsi, vwap_dist, market_sentiment
                )

                combined_score = round(
                    ((dump_sc if side == "sell" else pump_sc) * 0.5) + (tech_score * 0.5)
                )
                if side is None or combined_score < MIN_MOMENTUM_SCORE or tech_score < MIN_TECH_SCORE:
                    skip_reasons['low_score'] = skip_reasons.get('low_score', 0) + 1

                #  MARKET REGIME FILTER (ADX) 
                adx = _calc_adx(symbol)
                if adx < ADX_RANGING_THRESHOLD:
                    skip_reasons['ranging'] = skip_reasons.get('ranging', 0) + 1
                    continue
                regime_label = "TRENDING" if adx >= ADX_TRENDING_THRESHOLD else "WEAK_TREND"

                #  VOLATILITY REGIME FILTER 
                vol_data = _calc_volatility_regime(symbol)
                vol_regime = vol_data.get("regime", "NORMAL")
                if vol_regime == "HIGH_VOL":
                    skip_reasons['high_vol'] = skip_reasons.get('high_vol', 0) + 1
                    continue
                if vol_regime == "LOW_VOL":
                    skip_reasons['low_vol'] = skip_reasons.get('low_vol', 0) + 1
                    continue

                #  EXPECTED VALUE CHECK 
                # Hitung EV sebelum entry. Kalau EV terlalu kecil, tidak worth it.
                ev = _calc_expected_value(side, tech, combined_score) if side else 0
                if ev < MIN_EXPECTED_VALUE:
                    skip_reasons['low_ev'] = skip_reasons.get('low_ev', 0) + 1
                    continue

                # DXY override
                is_dxy_active = abs(dxy_change) > 0.0001
                if is_dxy_active and side == "buy" and dxy_trend == "BULLISH" and dxy_change > 0.2:
                    continue

                #  BTC CORRELATION FILTER 
                # BTC adalah market leader. Kalau BTC bearish kuat, jangan LONG altcoin.
                # Kalau BTC bullish kuat, jangan SHORT altcoin.
                btc_ctx = _get_btc_context()
                btc_signal = btc_ctx.get("signal", "NEUTRAL")
                if btc_signal == "AVOID_LONG" and side == "buy":
                    skip_reasons['btc_bear'] = skip_reasons.get('btc_bear', 0) + 1
                    continue
                if btc_signal == "AVOID_SHORT" and side == "sell":
                    skip_reasons['btc_bull'] = skip_reasons.get('btc_bull', 0) + 1
                    continue

                # Order book confirmation
                from data_fetcher import get_order_book_details
                ob_data  = get_order_book_details(symbol)
                ob_ratio = ob_data.get('ratio', 0)
                if side == "buy"  and ob_ratio < -0.1: continue
                if side == "sell" and ob_ratio > 0.1:  continue

                # Lolos semua filter - catat ke observer
                if side is not None and combined_score >= _session_min_score and tech_score >= MIN_TECH_SCORE:
                    # Off-hours: cek EV lebih ketat
                    if ev < _session_min_ev:
                        skip_reasons['low_ev'] = skip_reasons.get('low_ev', 0) + 1
                        continue
                    observer.record(clean_base, combined_score, tech_score, side, tech,
                                    adx=adx, ev=ev, vol_regime=vol_regime)
                    scan_count += 1
                    print(f"[OBS] {clean_base:8s} {side:4s} | Pump:{pump_sc:.0f} Dump:{dump_sc:.0f} "
                          f"Tech:{tech_score} Combined:{combined_score} | "
                          f"RSI:{rsi} VWAP:{vwap_dist}% | "
                          f"1h:{tech.get('trend_1h','?')} 4h:{tech.get('trend_4h','?')} | "
                          f"ADX:{adx} {regime_label} | Vol:{vol_regime} | EV:{ev:.3f} | "
                          f"OI:{tech.get('open_interest',0):.0f} "
                          f"Fund:{tech.get('funding_rate',0):.4f}")

            # Summary scan cycle
            skip_str = " | ".join(f"{k}:{v}" for k, v in skip_reasons.items()) if skip_reasons else "none"
            print(f"[SCAN] {scan_count} masuk watchlist | Skip: {skip_str} | "
                  f"Cooldown: {'YA ' + str(round(cooldown_remaining))+'s' if in_cooldown else 'TIDAK - SIAP ENTRY'}", flush=True)

            #  10. KEPUTUSAN ENTRY 
            if in_cooldown:
                # Masih dalam cooldown - terus observasi, jangan entry
                mins_left = round(cooldown_remaining / 60, 1)
                print(f"[OBSERVER] Observasi aktif. {mins_left} menit lagi sebelum entry. "
                      f"Watchlist: {len(observer._watchlist)} koin.")
                time.sleep(SCAN_INTERVAL)
                continue

            # Cooldown selesai - pilih kandidat terbaik dari observasi
            # Tapi kalau ada event high-impact dalam 30 menit, tunda eksekusi
            if _news_cal_block:
                print(f"[NEWS CALENDAR] Cooldown selesai tapi ada event high-impact. "
                      f"Tunda eksekusi, lanjut observasi.")
                time.sleep(SCAN_INTERVAL)
                continue

            best = observer.get_best_candidate(
                open_bases, _recently_exited,
                min_appearances=_session_min_appear,
                require_signal=_session_need_signal,
                min_avg_score=_session_min_avg,
            )

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
            # JANGAN masuk paksa  reset dan tunggu siklus baru yang lebih baik.
            # Lebih baik tidak trade daripada masuk dengan sinyal lemah.
            if not best.get('has_predictive_signal', True):
                obs_duration = time.time() - observer._obs_start
                print(f"[ENGINE] {best['clean_base']} tidak ada sinyal prediktif "
                      f"(Future:0, Rising:False, Whale:NORMAL) setelah {round(obs_duration/60,1)} menit. "
                      f"Reset dan cari kandidat baru.")
                observer.reset()
                time.sleep(SCAN_INTERVAL)
                continue

            #  11. EKSEKUSI KANDIDAT TERBAIK 
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

            # Ambil harga terbaru + data institusional lengkap untuk entry
            fresh_tech = get_technical_indicators(symbol)
            if fresh_tech:
                tech = fresh_tech  # Pakai data fresh untuk eksekusi

            # Tambahkan Volume Profile, HTF Levels, Fibonacci, Stop Hunt
            # Hanya dipanggil saat entry  tidak saat scan (terlalu banyak API call)
            try:
                from data_fetcher import (
                    get_volume_profile, get_htf_key_levels,
                    get_fibonacci_levels, detect_stop_hunt
                )
                vp   = get_volume_profile(symbol)
                htf  = get_htf_key_levels(symbol)
                fib  = get_fibonacci_levels(symbol)
                hunt = detect_stop_hunt(symbol)
                tech.update({
                    "poc":              vp.get("poc", 0),
                    "price_vs_poc":     vp.get("price_vs_poc", "UNKNOWN"),
                    "poc_distance_pct": vp.get("poc_distance_pct", 0),
                    "daily_high":       htf.get("daily_high", 0),
                    "daily_low":        htf.get("daily_low", 0),
                    "near_daily_level": htf.get("near_daily_level", False),
                    "near_weekly_level":htf.get("near_weekly_level", False),
                    "htf_level_bias":   htf.get("level_bias", "NEUTRAL"),
                    "fib_382":          fib.get("fib_382", 0),
                    "fib_618":          fib.get("fib_618", 0),
                    "at_fib_support":   fib.get("at_fib_support", False),
                    "at_fib_resistance":fib.get("at_fib_resistance", False),
                    "current_fib_level":fib.get("current_fib_level", "NONE"),
                    "bull_stop_hunt":   hunt.get("bull_stop_hunt", False),
                    "bear_stop_hunt":   hunt.get("bear_stop_hunt", False),
                    "hunt_strength":    hunt.get("hunt_strength", 0),
                })
                print(f"[ENTRY INTEL] {clean_base} | POC:{vp.get('price_vs_poc','?')} "
                      f"| HTF:{htf.get('level_bias','?')} "
                      f"| Fib:{fib.get('current_fib_level','NONE')} "
                      f"| Hunt:{'YES' if hunt.get('bull_stop_hunt') or hunt.get('bear_stop_hunt') else 'NO'}")
            except Exception as _e:
                pass  # Kalau gagal, lanjut dengan data yang ada

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

            #  EKSEKUSI 
            print(f"\n{'='*65}")
            print(f"[WHALE OBSERVER] ENTRY: {clean_base} {side.upper()}")
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
                # Trade berhasil masuk = reset consecutive loss counter
                # (loss counter hanya naik saat exit, bukan saat entry)
                _consec_losses = 0
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
