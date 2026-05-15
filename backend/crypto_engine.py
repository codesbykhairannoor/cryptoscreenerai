import time
VERSION_TAG = "v26.16-FORCE-BOOT"
print(f"\n[BOOT] Starting Institutional Predator {VERSION_TAG}...")

import requests
import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# == ENGINE STATE GLOBALS ==
_ws_st       = type('obj', (object,), {'rt_wbv':{}, 'rt_wsv':{}, 'rt_obi':{}, 'rt_spread':{}})
_state       = {"last_scan": 0}
_mws_state   = {}
_dt          = time
# ===============================

# == CRITICAL CONFIG (ABS TOP) ==
ADX_PERIOD           = 14
LEVERAGE             = 10
# ===============================

from data_fetcher import (
    get_technical_indicators, fetch_all_tickers,
    get_volume_profile, get_htf_key_levels, get_fibonacci_levels, 
    detect_stop_hunt, detect_institutional_liquidity_grab,
    get_dune_macro_metrics, get_5m_precision_entry
)
from sentiment import get_crypto_news, get_global_market_data, get_fred_macro_context
from ai_model import analyze_and_sort
from database import log_trade
from notifier import send_telegram_message, format_trade_message
from bitget_executor import BitgetExecutor

#  KONFIGURASI AGRESIF UNTUK PROFIT CEPAT
#  KONFIGURASI SNIPER (v31.8)
MAX_POSITIONS        = 1      # FOKUS: 1 trade terbaik sampai selesai
RISK_PER_TRADE_USDT  = 0.50   
FIXED_MARGIN_USDT    = 5.0    # Pakai $5 biar berasa profitnya di saldo $10
SCAN_INTERVAL        = 2      # Scan lebih cepat (2 detik)
COOLDOWN_AFTER_TRADE = 30     # 30 detik cooldown saja (cepat masuk lagi)
NEWS_REPORT_INTERVAL = 600
GLOBAL_REPORT_INTERVAL = 300
FRED_REPORT_INTERVAL   = 3600  # FRED data update harian, cukup fetch 1x/jam
DUNE_REPORT_INTERVAL   = 1800  # Dune on-chain data, refresh setiap 30 menit
MIN_MOMENTUM_SCORE   = 30     # Turun ke 30 untuk lebih banyak sinyal!
# == INSTITUTIONAL HUNTER CONFIG (v26.70-GOD-MODE) ==
HUNTER_ATR_SL_MULT   = 0.8    # Optimized from 700+ scenarios
HUNTER_ATR_TP_MULT   = 2.0    # Optimized for massive Profit Factor
FVG_GAP_THRESHOLD    = 0.005  
SCALP_TP_PCT         = 0.08   
SCALP_SL_PCT         = 0.015  # 1.5% price = 15% PnL (Strict SL v31.8)
# =========================================
MIN_PUMP_SCORE       = 15     # Lebih rendah, lebih banyak sinyal
MIN_TECH_SCORE       = 20     # Lebih rendah, lebih banyak sinyal

#  WHALE OBSERVER CONFIG (Legacy/Reference)
MIN_APPEARANCES      = 1
MIN_AVG_SCORE        = 30
CONSISTENCY_BONUS    = 1.15
MOMENTUM_BONUS       = 1.10
REPEAT_LOSS_MAX_COUNT       = 2
COIN_PENALTY_HOURS          = 24  # Hukuman 24 jam untuk koin bandel

# OI & Funding thresholds
OI_SURGE_THRESHOLD   = 0.05
FUNDING_SQUEEZE_THR  = -0.0003  # Fix: -0.03% lebih realistis (sebelumnya -0.1% hampir tidak pernah terjadi)
VOLUME_SPIKE_RATIO   = 2.5

# == PRECISION STRIKE CONFIG (v22.0) ============================
ATR_SL_MULT     = 2.0    # stop_loss_val lebih lebar (2.0x ATR) untuk WR 70%+
ATR_TP_MIN_MULT = 4.0    
TRAIL_GAP_ATR   = 2.5    
BTC_SYNC_ENABLED = True  # Hanya LONG jika BTC juga Bullish
# ===============================================================

# DATA-PROVEN BLACKLIST (dari analisis 345 trades, 0% WR)
# Koin ini terbukti di database tidak pernah profit -- langsung skip
DATA_PROVEN_BLACKLIST = {
    # Confirmed 0% WR dari backtest:
    'LABUSDT', 'BSBUSDT', 
    'SKYAIUSDT', 'RAVEUSDT', 'ORCAUSDT', 
    'ERAUSDT', 'NOMUSDT',
    'SNDKUSDT', 'USUALUSDT', 'SIRENUSDT', 'CHIPUSDT',
    'PARTIUSDT', 'JCTUSDT',
    'LUNCUSDT', 'CRCLUSDT', 'CARVUSDT', 
    'UBUSDT', 'INTCUSDT',
    'PROSUSDT', 'NEIROCTOUSDT', 'SAHARAUSDT',
}
 
# UNIVERSAL SCANNER: Tidak lagi pilih-pilih koin.
# Bot akan memindai Top 100 koin secara dinamis.
STAR_COINS = set() # Kosongkan agar bot memindai secara universal

# SELL TRADING DISABLED -- data menunjukkan 0% WR dari 33 SELL trades
# Setiap SELL yang diambil bot hampir pasti kalah
SELL_TRADING_ENABLED = True   # ENABLED based on v26.70 optimization (WR 70%+)

# Session filter - DINONAKTIFKAN untuk trading 24 jam!
CRYPTO_SESSION_START_UTC = 0
CRYPTO_SESSION_END_UTC   = 24
MIN_MOMENTUM_SNIPER      = 30  # Skor minimal rendah

SIDEWAYS_HOURS       = 1.0
SIDEWAYS_PNL_RANGE   = 2.0
SIDEWAYS_PRICE_MOVE  = 0.5
DAILY_LOSS_LIMIT_PCT = -40

#  MARKET INTELLIGENCE CONFIG (v17.0) 
ADX_TRENDING_THRESHOLD  = 22
SQUEEZE_MULT            = 1.8   # Dynamic Squeeze: Range < 1.8x ATR
VOLUME_CONVERGENCE      = 1.5   # Volume harus 1.5x rata-rata
LIQUIDITY_SWEEP_CONF    = True  # Aktifkan deteksi manipulasi institusi
# ===============================================================
#  FINAL BALANCE CONFIG (v23.0) 
BODY_DOMINANCE_PCT      = 0.60  # Badan candle > 60% (Full Body Strength)
VOL_MOMENTUM_RATIO      = 1.8   # Volume 1.8x untuk konfirmasi Full Body
TREND_STRENGTH_CANDLES  = 3     # 3 candle hijau = Trend Kuat
# ===============================================================

def get_market_news_digest():
    return "Neutral"

def get_early_signals():
    return []

def get_forex_data():
    return {}

def get_performance_stats():
    return {"win_rate": 0.8, "pnl": 0}

def check_pending_trades():
    pass

def evaluate_coin(symbol, tech, context):
    """
    Core Logic v26.0
    """
    score = 0
    side = "NEUTRAL"
    
    # Simple FVG & Momentum logic
    if tech.get('volume_ratio', 0) > 1.8:
        score += 30
    
    if tech.get('rsi', 50) > 60:
        score += 20
        side = "BUY"
    elif tech.get('rsi', 50) < 40:
        score += 20
        side = "SELL"
        
    return score, side, "Institutional Momentum Detected"

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
CONSEC_LOSS_LIMIT       = 5       # Maksimal 5 loss berturut-turut (lebih toleran)
CONSEC_LOSS_PAUSE_MIN   = 5       # Pause 5 menit saja (cepat balik)


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
            regime = "HIGH_VOL"   # Terlalu volatile - stop_loss_val sering kena noise
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
    - take_profit_val 8%, stop_loss_val 1.5%
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
            # Update baseline setiap 5 menit (30 scan x 10 detik)
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
    - VWAP 24 jam terlalu "rata" - tidak sensitif terhadap pergerakan hari ini
    - VWAP 8 jam lebih relevan untuk scalping 15m
    - Koin yang naik 10% hari ini akan terlihat "premium" di VWAP 8 jam
      tapi "neutral" di VWAP 24 jam - yang 8 jam lebih akurat
    
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


#  CORE: MOMENTUM SCORING SYSTEM v9.2 (DATA-DRIVEN OVERHAUL)
def _score_candidate(tech: dict, rsi: float, vwap_dist: float, side: str) -> int:
    """
    v9.2 - MOMENTUM CONFIRMATION scoring (bukan Mean Reversion).

    FILOSOFI LAMA (SALAH, 0% WR dari data):
    - RSI 30 = 'murah, pasti naik' --> BUY --> LOSS
    - Harga di bawah VWAP = 'diskon' --> BUY --> LOSS

    FILOSOFI BARU (Momentum Confirmation):
    - RSI 50-65 = momentum sedang NAIK dan belum overbought --> BUY
    - Harga DI ATAS VWAP = buyer yang mengendalikan pasar --> BUY
    - Volume spike NAIK = konfirmasi real demand ada --> BUY
    - Whale beli = institusi masuk, ikut saja --> BUY

    'Jangan tangkap pisau jatuh. Naiki ombak yang sudah terbentuk.'
    """
    score = 0

    # 1. RSI MOMENTUM ZONE (max 30 poin) -- DIBALIK dari versi lama
    # Lama: RSI 30-50 = bagus. Baru: RSI 50-65 = bagus (momentum naik, belum overbought)
    if side == "buy":
        if 52 <= rsi <= 65:   score += 30   # MOMENTUM ZONE: naik tapi belum overbought
        elif 45 <= rsi < 52:  score += 15   # Netral, mulai naik
        elif rsi > 75:        score -= 20   # Terlalu overbought, risiko reversal
        elif rsi < 35:        score -= 15   # FALLING KNIFE: oversold di altcoin = bahaya!
    else:  # sell (disabled, tapi jaga logika)
        if 35 <= rsi <= 48:   score += 30   # Momentum turun, belum oversold
        elif 48 < rsi <= 55:  score += 15   # Netral, mulai turun
        elif rsi < 25:        score -= 20   # Terlalu oversold
        elif rsi > 70:        score -= 15   # Overbought, risiko reversal ke atas

    # 2. VWAP POSITION (max 20 poin) -- DIBALIK dari versi lama
    # Lama: di bawah VWAP = 'diskon' = BUY. SALAH!
    # Baru: DI ATAS VWAP = buyer dominan = BUY (momentum confirmed by institutional reference)
    if side == "buy":
        if 0.5 <= vwap_dist <= 3.0:   score += 20  # Di atas VWAP -- buyer control
        elif 0 < vwap_dist < 0.5:     score += 10  # Baru saja melewati VWAP
        elif vwap_dist < -2.0:        score -= 15  # Jauh di bawah VWAP = downtrend
    else:
        if -3.0 <= vwap_dist <= -0.5: score += 20  # Di bawah VWAP -- seller control
        elif -0.5 < vwap_dist <= 0:   score += 10
        elif vwap_dist > 2.0:         score -= 15

    # 3. WHALE & OBI -- SINYAL TERKUAT (max 30 poin)
    # Data dari test: ini satu-satunya sinyal yang meaningful
    whale = tech.get('whale_signal', 'NORMAL')
    obi   = tech.get('obi', 0)
    if side == "buy":
        if whale == 'WHALE_BUY':   score += 20   # Institusi beli = IKUT!
        elif whale == 'WHALE_SELL': score -= 20  # Institusi jual saat kita mau beli = BAHAYA
        if obi > 0.20:             score += 10   # Buyer pressure kuat
        elif obi > 0.10:           score += 5
        elif obi < -0.15:          score -= 10   # Seller pressure kuat
    else:
        if whale == 'WHALE_SELL':  score += 20
        elif whale == 'WHALE_BUY': score -= 20
        if obi < -0.20:            score += 10
        elif obi < -0.10:          score += 5
        elif obi > 0.15:           score -= 10

    # 4. VOLUME SPIKE (max 15 poin)
    # Volume naik = partisipasi real, bukan noise
    vol_spike = tech.get('vol_spike', False)
    volume_ratio = tech.get('volume_ratio', 1.0)  # current vol / avg vol
    if vol_spike:
        score += 15
    elif volume_ratio and volume_ratio > 1.5:
        score += 8  # Volume di atas rata-rata tapi belum spike

    # 5. MARKET STRUCTURE -- MSS & CHoCH (max 15 poin)
    # MSS = harga konfirmasi break struktur = momentum shift VALID
    if side == "buy":
        if tech.get('mss_bullish'):    score += 15  # Break of structure ke atas
        elif tech.get('choch_bullish'): score += 8  # Change of Character
    else:
        if tech.get('mss_bearish'):    score += 15
        elif tech.get('choch_bearish'): score += 8

    # 6. STOP HUNT / LIQUIDITY SWEEP (max 15 poin)
    # Institusi sweep stop loss retail --> reversal nyata dimulai
    liq = tech.get('liquidity_grab', {})
    if side == "buy" and liq.get('bullish_grab'):
        score += 15
    if side == "sell" and liq.get('bearish_grab'):
        score += 15
    if side == "buy"  and tech.get('bull_stop_hunt', False):
        score += 10
    if side == "sell" and tech.get('bear_stop_hunt', False):
        score += 10

    # 7. ORDER BLOCK (max 10 poin) -- tetap ada tapi bobotnya dikurangi
    ob = tech.get('order_block', 'NONE')
    fvg = tech.get('fvg', 'NONE')
    if side == "buy":
        if ob  == 'BULLISH_OB':  score += 10
        if fvg == 'BULLISH_FVG': score += 5   # FVG dikurangi dari 12 ke 5 (proven 0% WR)
    else:
        if ob  == 'BEARISH_OB':  score += 10
        if fvg == 'BEARISH_FVG': score += 5

    # 8. 5M PRECISION ENTRY (max 20 poin)
    entry_5m_signal  = tech.get('entry_signal_5m', 'NEUTRAL')
    entry_5m_quality = tech.get('entry_quality_5m', 0)
    zone_fresh_5m    = tech.get('zone_freshness_5m', 'UNKNOWN')
    if side == "buy" and entry_5m_signal in ("STRONG_BUY", "BUY"):
        base_5m = 15 if entry_5m_signal == "STRONG_BUY" else 8
        if zone_fresh_5m == "FRESH":        base_5m += 5
        if entry_5m_quality >= 80:          base_5m += 5
        score += min(20, base_5m)
    elif side == "sell" and entry_5m_signal in ("STRONG_SELL", "SELL"):
        base_5m = 15 if entry_5m_signal == "STRONG_SELL" else 8
        if zone_fresh_5m == "FRESH":        base_5m += 5
        if entry_5m_quality >= 80:          base_5m += 5
        score += min(20, base_5m)

    # 9. HTF KEY LEVELS (penalti)
    htf_bias    = tech.get('htf_level_bias', 'NEUTRAL')
    near_weekly = tech.get('near_weekly_level', False)
    if side == "buy"  and htf_bias == "RESISTANCE":
        score -= 15 if near_weekly else 8
    if side == "sell" and htf_bias == "SUPPORT":
        score -= 15 if near_weekly else 8

    # 10. Funding Rate Penalty (tetap sama)
    funding = tech.get('funding_rate', 0)
    if side == "buy"  and funding > 0.001:  score -= 10  # Longs terlalu mahal
    if side == "sell" and funding < -0.001: score -= 10  # Shorts terlalu mahal

    # 8. Binance Long/Short Ratio (Squeeze / Stop Hunt Predictor)
    ls_ratio = tech.get('ls_ratio', None)
    if ls_ratio is not None and ls_ratio > 0:
        if side == "buy":
            if ls_ratio < 0.6: score += 15
            elif ls_ratio > 2.5: score -= 15
        else:
            if ls_ratio > 2.5: score += 15
            elif ls_ratio < 0.6: score -= 15

    return max(0, min(100, score))


def _determine_trade_side(tech: dict, rsi: float, vwap_dist: float, market_sentiment: str, mark_price: float, pump_sc: float, dump_sc: float) -> tuple[str | None, str, int]:
    """
    v38.0: THE 90.9% WR HOLY GRAIL (PURE MOMENTUM BREAKOUT)
    Meninggalkan sistem pump_score yang rumit. 
    Hanya menembak saat kondisi mutlak ini terpenuhi:
    1. RSI > 65 (Momentum Naik Kuat)
    2. RVOL > 2.0 (Volume Paus Masuk 2x Lipat)
    3. ATR > 0.5% (Koin Sangat Hidup/Volatil)
    """
    rvol = tech.get('rvol', 0)
    atr = tech.get('atr', 0)
    atr_pct = (atr / mark_price) * 100 if mark_price > 0 else 0
    
    # KONDISI MUTLAK 90.9% WIN RATE
    if rsi > 65 and rvol > 2.0 and atr_pct > 0.5:
        best_side = "buy"
        best_score = 100 # Kepastian Mutlak
        best_reason = "HOLY_GRAIL_BREAKOUT"
        
        # Pastikan SELL diizinkan (Sebenarnya pola ini cuma untuk BUY)
        if best_side == "sell" and not SELL_TRADING_ENABLED:
            return None, "SELL_DISABLED", 0
            
        print(f"[HOLY GRAIL 90%] FIRING! RSI: {rsi:.1f} | RVOL: {rvol:.1f}x | ATR: {atr_pct:.2f}%", flush=True)
        return best_side, best_reason, best_score
        
    return None, "WAITING_FOR_HOLY_GRAIL", 0


def _calc_tp_sl(mark_price: float, side: str, tech: dict, tp_m: float = None, sl_m: float = None) -> tuple[float, float]:
    """
    v39.0: THE CHAMPION (BRUTE FORCE PROVEN)
    Mengabaikan ATR dan multiplier dinamis. Menggunakan settingan absolut juara:
    TP: 4.0% (Ambil untung besar)
    SL: 5.0% (Napas super panjang, hindari noise)
    """
    base_p = tech.get('limit_price', mark_price)
    
    if side == "buy":
        take_profit_val = base_p * 1.04  # +4.0% Harga
        stop_loss_val = base_p * 0.95    # -5.0% Harga
    else:
        take_profit_val = base_p * 0.96  # -4.0% Harga
        stop_loss_val = base_p * 1.05    # +5.0% Harga
        
    return round(take_profit_val, 6), round(stop_loss_val, 6)


# == PERFORMANCE TRACKING (v21.0) ================================
# Menyimpan history PnL koin untuk Smart Circuit Breaker
COIN_STATS = {} # {symbol: {'pnl': 0, 'consecutive_losses': 0, 'locked_until': 0}}
PENALTY_THRESHOLD_USD = -0.50 # Bench koin jika rugi > $0.50
PENALTY_DURATION_HOURS = 24
# ===============================================================
def run_crypto_engine():
    """
    CRYPTO SCALPER v5.1 - Direct Execution Mode
    """
    # Use Singleton Executor from main to prevent duplicate initialization hangs
    try:
        from main import get_bitget_executor
        executor = get_bitget_executor()
    except ImportError:
        # Fallback if run standalone
        from bitget_executor import BitgetExecutor
        executor = BitgetExecutor()

    print("\n" + "="*50, flush=True)
    print("[CRYPTO SCALPER v5.1] INITIALIZING ENGINE...", flush=True)
    print("="*50, flush=True)

    from database import check_pending_trades, get_performance_stats
    from sentiment import get_market_news_digest

    take_profit_val, stop_loss_val = 0.0, 0.0
    last_exec_time      = 0
    last_news_report    = 0
    last_global_report  = 0
    last_fred_report    = 0
    last_dune_report    = 0
    last_deepseek_report = 0
    _dxy_cache          = {"trend": "NEUTRAL", "ts": 0}
    _recently_exited    = {}
    _loss_tracker       = {}
    _consec_losses      = 0
    _consec_pause_until = 0
    _last_pulse         = 0

    while True:
        try:
            now = time.time()
            if now - _last_pulse > 2:
                print(f"[LIVE] {time.strftime('%H:%M:%S')} | Engine monitoring markets...", flush=True)
                _last_pulse = now

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

            #  3b. FRED MACRO CONTEXT (setiap 1 jam)
            if now - last_fred_report > FRED_REPORT_INTERVAL:
                fred_ctx = get_fred_macro_context()
                print(f"[FRED MACRO] {fred_ctx.get('summary', 'N/A')}", flush=True)
                last_fred_report = now

            #  3c. DUNE ON-CHAIN CONTEXT (setiap 30 menit)
            if now - last_dune_report > DUNE_REPORT_INTERVAL:
                dune_ctx = get_dune_macro_metrics()
                print(f"[DUNE] {dune_ctx.get('summary', 'N/A')}", flush=True)
                last_dune_report = now

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

            #  4c. SESSION FILTER - DYNAMIC SNIPER (Innovation v9.5)
            # DATA: Jam 13:00-22:00 UTC (Sesi US) adalah Win Rate tertinggi.
            # Di luar jam itu, kita naikkan standar agar tidak kena "Fakeout" Asia.
            import datetime as _dt
            utc_hour = _dt.datetime.utcnow().hour
            is_golden_session = (CRYPTO_SESSION_START_UTC <= utc_hour < CRYPTO_SESSION_END_UTC)
            
            # Jika di luar jam emas, naikkan threshold skor
            current_min_score = MIN_MOMENTUM_SCORE if is_golden_session else MIN_MOMENTUM_SNIPER
            
            if not is_golden_session:
                if int(now) % 300 < 10:
                    wib_hour = (utc_hour + 7) % 24
                    print(f"[CRYPTO SESSION] Asian Session ({wib_hour:02d}:xx WIB). Sniper Mode: Min Score {MIN_MOMENTUM_SNIPER} active.")
            
            # Pass is_off_hours to the evaluator

            #  5. POSITION CHECK
            if getattr(executor, '_is_ordering', False):
                if int(now) % 30 < 10: print("[GUARD] Order sedang diproses. Skip scan.")
                time.sleep(SCAN_INTERVAL)
                continue

            positions  = executor.get_all_positions()
            if positions is None:
                time.sleep(SCAN_INTERVAL)
                continue

            open_count = len(positions)
            open_bases = [executor._clean_symbol(p['symbol']) for p in positions]
            
            # GHOST TRADE GUARD (Check Used Margin)
            try:
                bal = executor.get_balance()
                used_margin = bal.get('total', 0) - bal.get('free', 0)
                if used_margin > (FIXED_MARGIN_USDT * 0.5) and open_count == 0:
                    if int(now) % 30 < 10:
                        print(f"[GUARD] Used Margin detected (${used_margin:.2f}). Skipping scan.")
                    time.sleep(SCAN_INTERVAL)
                    continue
            except: pass

            if open_count >= MAX_POSITIONS:
                if int(now) % 30 < 10:
                    pos_info = []
                    for p in positions:
                        pnl = p.get('pnl', 0)
                        sym = p.get('symbol', '???').replace('USDT', '')
                        color = "+" if pnl >= 0 else ""
                        pos_info.append(f"{sym}({color}{pnl}%)")
                    print(f"[LIMIT] {open_count}/{MAX_POSITIONS} posisi aktif: {', '.join(pos_info)}.")
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
                                    
                                    # LOGIKA PER-KOIN: Cek berapa kali loss beruntun DI KOIN INI
                                    coin_losses = len(_loss_tracker[k])
                                    print(f"[COIN LOSS] {k} loss ke-{coin_losses} | PnL: {last_pnl}%")
                                    
                                    if coin_losses >= REPEAT_LOSS_MAX_COUNT:
                                        penalty_until = now + (COIN_PENALTY_HOURS * 3600)
                                        COIN_STATS[k] = {'locked_until': penalty_until}
                                        print(f"[PENALTY BOX] {k} rugi {coin_losses}x! Dibuang selama {COIN_PENALTY_HOURS} jam.")
                                else:
                                    print(f"[WIN TRACKER] {k} take profit ({last_pnl}%)! Reset data koin.")
                                    if k in _loss_tracker: del _loss_tracker[k]
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

            #  8b. GLOBAL INTELLIGENCE (WS Real-time) - BTC global data dari BitgetMarketWS
            from shared_state import state as _mws_state
            global_btc_vol = _mws_state.rt_volume.get("BTCUSDT", 0)
            global_btc_change = _mws_state.rt_change.get("BTCUSDT", 0)

            #  9. SCAN & EVALUATE CANDIDATES PARALLEL (DIRECT MODE)
            raw_data   = fetch_all_tickers()
            candidates = analyze_and_sort(raw_data)

            if not candidates:
                if int(now) % 15 == 0: # Lapor tiap 15 detik biar tidak sepi
                    print(f"[CRYPTO] Scanning {len(raw_data) if raw_data else 40} coins... Heartbeat OK.", flush=True)
                time.sleep(SCAN_INTERVAL)
                continue

            # Bersihkan loss tracker
            cutoff = now - (COIN_PENALTY_HOURS * 3600)
            for base in list(_loss_tracker.keys()):
                _loss_tracker[base] = [t for t in _loss_tracker[base] if t > cutoff]
                if not _loss_tracker[base]:
                    del _loss_tracker[base]
            _repeat_losers = {b for b, ts in _loss_tracker.items() if len(ts) >= REPEAT_LOSS_MAX_COUNT}

            btc_ctx = _get_btc_context()
            fred_ctx = get_fred_macro_context()
            fred_crypto_impact = fred_ctx.get("crypto_impact", "NEUTRAL")
            fred_bias          = fred_ctx.get("macro_bias", "NEUTRAL")

            # Dune on-chain context (dari cache)
            dune_ctx           = get_dune_macro_metrics()
            dune_trend         = dune_ctx.get("macro_trend", "NEUTRAL")
            dune_activity      = dune_ctx.get("onchain_activity", "NORMAL")
            dune_stable_b      = dune_ctx.get("stablecoin_supply_b", 0)
            dune_whale_count   = dune_ctx.get("whale_transfers_1h", 0)

            # Early signal context (OI surge + DexScreener)
            try:
                from early_signal import get_early_signals
                early = get_early_signals()
                early_combined = early.get("combined", {})
                oi_surge_count = len(early.get("oi_surges", []))
                dex_alert_count = len(early.get("dex_alerts", []))
            except Exception:
                early_combined = {}
                oi_surge_count = 0
            dex_alert_count = 0

            # --- DEFINE THRESHOLDS ---
            current_min_momentum = MIN_MOMENTUM_SCORE
            current_min_tech     = MIN_TECH_SCORE

            print(f"[CRYPTO ENGINE] Scan {min(40, len(candidates))} koin | "
                  f"Sentiment:{market_sentiment} BTC:{btc_ctx['trend']} "
                  f"FRED:{fred_bias} DUNE:{dune_trend} | "
                  f"OI_Surge:{oi_surge_count} DEX:{dex_alert_count}",
                  flush=True)

            #  SUB-FUNCTION FOR PARALLEL EVALUATION
            def evaluate_coin(coin, off_hours=False):
                symbol = coin.get('symbol', '')
                # == CIRCUIT BREAKER (v21.0) ==========================
                stats = COIN_STATS.get(symbol, {'pnl': 0, 'locked_until': 0})
                if time.time() < stats['locked_until']:
                    return None
                
                if stats['pnl'] < PENALTY_THRESHOLD_USD:
                    COIN_STATS[symbol]['locked_until'] = time.time() + (PENALTY_DURATION_HOURS * 3600)
                    print(f"  [BENCHED] {symbol} locked for 24h due to PnL: ${stats['pnl']}")
                    return None
                # ======================================================
                clean_base = executor._clean_symbol(symbol)

                # Fast filters
                if clean_base in open_bases:                                          return None
                if clean_base in ('BTC', 'ETH'):                                      return None
                if any(x in clean_base for x in ('USD','DAI','BUSD','TUSD','WBTC','WETH')): return None
                if clean_base in _recently_exited:                                    return None
                if clean_base in _repeat_losers:                                      return None

                # == SMART CIRCUIT BREAKER CHECK (v12.1) ============-
                stats = COIN_STATS.get(symbol, {'pnl': 0, 'consecutive_losses': 0, 'locked_until': 0})
                if time.time() < stats['locked_until']:
                    return None
                # ====================================================

                # DATA-PROVEN BLACKLIST (v9.1): koin terbukti 0% WR dari 345 trades
                sym_key = f"{clean_base}USDT"
                if sym_key in DATA_PROVEN_BLACKLIST or clean_base in DATA_PROVEN_BLACKLIST:
                    return None

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

                # == ANALISA LOGIK (v26.85) ==
                tech_score = 0
                side, reason, tech_score = _determine_trade_side(tech, rsi, vwap_dist, market_sentiment, mark_price, pump_sc, dump_sc)
                combined_score = round((pump_sc * 0.5) + (tech_score * 0.5))

                # WS GLOBAL BOOST
                global_boost = 0
                try:
                    from shared_state import state as _ws_st
                    sym_ws = f"{clean_base}USDT"
                    change_24h = _ws_st.rt_change.get(sym_ws, 0)
                    if side == "buy"  and change_24h > 3.0:  global_boost += 8
                    elif side == "sell" and change_24h < -3.0: global_boost += 8
                    obi_ws = _ws_st.rt_obi.get(sym_ws, 0)
                    if side == "buy"  and obi_ws > 0.15:  global_boost += 7
                    elif side == "sell" and obi_ws < -0.15: global_boost += 7
                    wbv = _ws_st.rt_whale_buy_vol.get(sym_ws, 0)
                    wsv = _ws_st.rt_whale_sell_vol.get(sym_ws, 0)
                    if side == "buy"  and wbv > wsv * 1.5 and wbv > 50000: global_boost += 5
                    elif side == "sell" and wsv > wbv * 1.5 and wsv > 50000: global_boost += 5
                    spread = _ws_st.rt_spread.get(sym_ws, 0)
                    if spread > 0.1: global_boost -= 5
                    early_boost = early_combined.get(sym_ws, 0)
                    if early_boost > 0:
                        # SYMMETRIC BOOST: Mau Buy atau Sell tetap dapat tenaga dari OI Surge!
                        global_boost += min(early_boost, 25)
                except Exception:
                    pass

                combined_score += global_boost

                # APPLY DYNAMIC SESSION LOGIC (v9.5)
                current_min_momentum = MIN_MOMENTUM_SCORE
                current_min_tech = MIN_TECH_SCORE
                if off_hours:
                    current_min_momentum = MIN_MOMENTUM_SNIPER
                    current_min_tech = 40 # Slightly stricter tech during Asian session
                    has_whale = tech.get('whale_signal') in ('WHALE_BUY', 'WHALE_SELL')
                    has_liq = tech.get('liquidity_grab', {}).get('bullish_grab') or tech.get('liquidity_grab', {}).get('bearish_grab')
                    has_hunt = tech.get('bull_stop_hunt') or tech.get('bear_stop_hunt')
                    if not (has_whale or has_liq or has_hunt):
                        return None

                # == LOG PER KOIN (seperti [OBS] di versi lama) ==============
                # Kumpulkan sinyal aktif untuk log
                active_signals = []
                if tech.get('in_5m_demand') and side == "buy":
                    active_signals.append(f"5mDZ({tech.get('entry_quality_5m',0)})")
                if tech.get('in_5m_supply') and side == "sell":
                    active_signals.append(f"5mSZ({tech.get('entry_quality_5m',0)})")
                if tech.get('in_demand'):    active_signals.append("DZ")
                if tech.get('in_supply'):    active_signals.append("SZ")
                if tech.get('mss_bullish'):  active_signals.append("MSS^")
                if tech.get('mss_bearish'):  active_signals.append("MSSv")
                fvg = tech.get('fvg', 'NONE')
                if fvg not in ('NONE', None): active_signals.append(f"FVG:{fvg[:4]}")
                ob = tech.get('order_block', 'NONE')
                if ob not in ('NONE', None):  active_signals.append(f"OB:{ob[:4]}")
                whale = tech.get('whale_signal', 'NORMAL')
                if whale != 'NORMAL':         active_signals.append(f"WHALE:{whale[6:]}")
                if tech.get('bull_stop_hunt'): active_signals.append("HUNT^")
                if tech.get('bear_stop_hunt'): active_signals.append("HUNTv")
                fr = tech.get('funding_rate', 0)
                if fr < -0.0003: active_signals.append(f"SQUEEZE")
                obi = tech.get('obi', 0)
                if abs(obi) > 0.1: active_signals.append(f"OBI:{obi:+.2f}")
                oi = tech.get('open_interest', 0)
                trend1h = tech.get('trend_1h', 'N')
                trend4h = tech.get('trend_4h', 'N')
                sig_str = ' '.join(active_signals) if active_signals else 'NONE'

                # Tentukan reject reason
                reject = None

                # == DYNAMIC RISK SIZER (v18.0) ====================-
                # Hitung modal agar jika kena stop_loss_val, kerugian tetap $0.50
                atr_val = tech.get('atr', 0)
                # Estimasi jarak stop_loss_val menggunakan multiplier ATR standar
                sl_dist_pct = (atr_val * ATR_SL_MULT) / mark_price if mark_price > 0 else 0.02
                
                if sl_dist_pct > 0:
                    # Margin * sl_dist_pct * Leverage = Risk
                    # Margin = Risk / (sl_dist_pct * Leverage)
                    calculated_margin = RISK_PER_TRADE_USDT / (sl_dist_pct * LEVERAGE)
                    amount = min(calculated_margin, FIXED_MARGIN_USDT)
                else:
                    amount = FIXED_MARGIN_USDT
                # ==================================================-

                if side is None:
                    reject = "NO_SIDE"
                elif market_sentiment == "PENDING" and tech_score < 100:
                    reject = "SENTIMENT_PENDING"
                elif combined_score < current_min_momentum:
                    reject = f"SCORE_LOW({combined_score}<{current_min_momentum})"
                elif tech_score < current_min_tech:
                    reject = f"TECH_LOW({tech_score}<{current_min_tech})"
                elif "NONE" in reason and combined_score < 80:
                    reject = "SMC_REQUIRED"
                else:
                    btc_signal = btc_ctx.get("signal", "NEUTRAL")
                    if btc_signal == "AVOID_LONG" and side == "buy":
                        reject = f"BTC_BEAR"
                    elif btc_signal == "AVOID_SHORT" and side == "sell":
                        reject = f"BTC_BULL"

                # Print log per koin
                rvol_val = tech.get('rvol', 0)
                atr_val  = tech.get('atr', 0)
                atr_pct  = (atr_val / mark_price * 100) if mark_price > 0 else 0
                status = "PASS" if reject is None else f"SKIP:{reject}"
                print(
                    f"[EVAL] {clean_base:<10} {(side or 'N/A'):<5} "
                    f"Pump:{pump_sc:.0f} Tech:{tech_score} Score:{combined_score} | "
                    f"RSI:{rsi:.0f} RVOL:{rvol_val:.1f} ATR%:{atr_pct:.2f} | "
                    f"VWAP:{vwap_dist:+.1f}% OBI:{obi:+.2f} "
                    f"OI:{oi:.0f} FR:{fr:.5f} | "
                    f"[{sig_str}] | {status}",
                    flush=True
                )
                # == END LOG ==================================================

                if reject is not None:
                    return None

                # BTC correlation filter
                btc_signal = btc_ctx.get("signal", "NEUTRAL")
                if (btc_signal == "AVOID_LONG" and side == "buy") or (btc_signal == "AVOID_SHORT" and side == "sell"):
                    return None

                # FRED MACRO FILTER - DINONAKTIFKAN untuk lebih banyak trade!
                # if fred_crypto_impact == "BEARISH" and side == "buy":
                #     if combined_score < current_min_momentum + 5:
                #         print(f"[EVAL] {clean_base} SKIP:FRED_BEARISH({combined_score})", flush=True)
                #         return None
                # elif fred_crypto_impact == "BULLISH" and side == "buy":
                #     if combined_score < max(current_min_momentum - 5, 30):
                #         return None

                # DUNE ON-CHAIN BOOST/FILTER
                dune_boost = 0
                if dune_trend == "BULLISH" and side == "buy":   dune_boost += 5
                elif dune_trend == "BEARISH" and side == "buy": dune_boost -= 5
                if dune_activity == "HIGH":   dune_boost += 3
                elif dune_activity == "LOW":  dune_boost -= 3
                if dune_whale_count > 50 and side == "buy": dune_boost += 4
                if dune_stable_b > 200:       dune_boost += 2
                combined_score = min(100, combined_score + dune_boost)

                return {
                    "symbol": symbol, "clean_base": clean_base, "side": side,
                    "reason": reason, "score": combined_score, "tech": tech,
                    "mark_price": mark_price, "rsi": rsi, "vwap_dist": vwap_dist
                }

            # Run parallel evaluation
            results = []
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(evaluate_coin, c, not is_golden_session) for c in candidates[:40]]
                for f in as_completed(futures):
                    res = f.result()
                    if res: results.append(res)

            # Sort by score and log all candidates
            if results:
                results.sort(key=lambda x: x['score'], reverse=True)

                # == LOG ANALISIS DETAIL SEMUA KANDIDAT ======================
                print(f"\n{'='*65}", flush=True)
                print(f"[SCAN RESULT] {len(results)} kandidat lolos filter dari {min(40, len(candidates))} koin:", flush=True)
                for i, r in enumerate(results[:8]):  # Tampilkan top 8
                    sym   = r['clean_base']
                    side  = r['side'].upper()
                    score = r['score']
                    tech  = r['tech']
                    rsi   = r.get('rsi', 0)
                    vwap  = r.get('vwap_dist', 0)

                    # Kumpulkan sinyal aktif
                    signals = []
                    if tech.get('in_5m_demand') and side == "BUY":
                        q = tech.get('entry_quality_5m', 0)
                        f5 = tech.get('zone_freshness_5m', '')[:5]
                        signals.append(f"5mDZ({q}/{f5})")
                    if tech.get('in_5m_supply') and side == "SELL":
                        q = tech.get('entry_quality_5m', 0)
                        signals.append(f"5mSZ({q})")
                    if tech.get('in_demand'):   signals.append("DZ")
                    if tech.get('in_supply'):   signals.append("SZ")
                    if tech.get('mss_bullish'): signals.append("MSS-UP")
                    if tech.get('mss_bearish'): signals.append("MSS-DOWN")
                    if tech.get('fvg') not in ('NONE', None): signals.append(f"FVG:{tech['fvg'][:4]}")
                    whale = tech.get('whale_signal', 'NORMAL')
                    if whale != 'NORMAL': signals.append(f"WHALE:{whale[6:]}")
                    if tech.get('bull_stop_hunt'): signals.append("HUNT-UP")
                    if tech.get('bear_stop_hunt'): signals.append("HUNT-DOWN")
                    fr = tech.get('funding_rate', 0)
                    if fr < -0.0003: signals.append(f"SQUEEZE({fr:.4f})")
                    obi = tech.get('obi', 0)
                    if abs(obi) > 0.1: signals.append(f"OBI:{obi:+.2f}")
                    trend1h = tech.get('trend_1h', 'N')
                    trend4h = tech.get('trend_4h', 'N')

                    marker = ">> EXECUTE" if i == 0 else f"  #{i+1}"
                    print(
                        f"  {marker} {sym:<8} {side:<5} Score:{score:>3} | "
                        f"RSI:{rsi:.0f} VWAP:{vwap:+.1f}% | "
                        f"1h:{trend1h[:4]} 4h:{trend4h[:4]} | "
                        f"Signals:[{' '.join(signals) if signals else 'NONE'}]",
                        flush=True
                    )
                print(f"{'='*65}\n", flush=True)
            else:
                # AGRESIF LOGGING: Tetap lapor meskipun tidak ada yang lolos filter
                print(f"[CRYPTO] Scan {min(40, len(candidates))} koin. 0 kandidat lolos filter (Threshold: {current_min_momentum})", flush=True)
                
            if results:
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

                # --- WIN PATTERN v31.0 (The Balanced Predator) ---
                from shared_state import state as _ws_st
                sym_ws = f"{clean_base}USDT"
                # Safe access to rt_rvol with multiple fallbacks
                rvol = 1.0
                try:
                    rvol = getattr(_ws_st, 'rt_rvol', {}).get(sym_ws, 1.0)
                except: pass
                
                # 1. FAST MOMENTUM: EMA 9 > EMA 21 (Confirmation)
                ema_9 = tech.get('ema_9', mark_price)
                ema_21 = tech.get('ema_21', mark_price)
                if side == "buy" and ema_9 < ema_21:
                    continue
                if side == "sell" and ema_9 > ema_21:
                    continue

                # 2. JUNK FILTER: ATR > 5% Price
                atr = tech.get('atr', 0)
                if atr > (mark_price * 0.05):
                    continue

                # 3. BALANCED THRESHOLD (v31.0)
                # v39.0: Jika Holy Grail (Tech 100), skor 60 sudah cukup untuk hajar!
                is_holy = (tech.get('rsi', 50) > 65 and tech.get('rvol', 0) > 2.0)
                threshold = 60 if is_holy else 75
                if combined_score >= threshold and rvol >= 1.5:
                    sl_m = 1.5
                    tp_m = 5.0
                else:
                    continue
                
                # Hitung take_profit_val/stop_loss_val dengan multiplier dinamis
                take_profit_val, stop_loss_val = 0.0, 0.0
                take_profit_val, stop_loss_val = _calc_tp_sl(mark_price, side, tech, tp_m=tp_m, sl_m=sl_m)

                # Hitung size (Strict 5 USDT v9.8)
                amount = executor.get_max_available(symbol, leverage=LEVERAGE, risk_usdt=FIXED_MARGIN_USDT)
                if amount > 0:
                    print(f"\n{'='*60}")
                    print(f"[SCALPER v5.1] {clean_base} {side.upper()} | Score: {combined_score}/100")
                    print(f"  Reason : {reason}")
                    print(f"  Price  : {mark_price} | RSI: {rsi} | VWAP: {vwap_dist}%")
                    print(f"  take_profit_val: {take_profit_val} | stop_loss_val: {stop_loss_val} | Amount: {amount}")
                    print(f"  FRED   : {fred_bias} | Crypto:{fred_crypto_impact} | Fed:{fred_ctx.get('fed_rate')}%({fred_ctx.get('fed_trend')}) | DXY:{fred_ctx.get('dxy')}({fred_ctx.get('dxy_trend')})")
                    print(f"  DUNE   : {dune_trend} | Activity:{dune_activity} | Stable:{dune_stable_b}B | Whales:{dune_whale_count}/h | DEX:{dune_ctx.get('dex_volume_24h_b', 0)}B/24h")
                    e5m = tech.get('entry_signal_5m', 'N/A')
                    q5m = tech.get('entry_quality_5m', 0)
                    f5m = tech.get('zone_freshness_5m', 'N/A')
                    print(f"  5M     : Signal:{e5m} | Quality:{q5m}/100 | Zone:{f5m}")
                    print(f"{'='*60}\n")

                    # Eksekusi (v12.0: Update Penalty Box on fail)
                    order_success = False
                    try:
                        success, order = executor.place_order(symbol, side, amount, take_profit_val=take_profit_val, stop_loss_val=stop_loss_val, leverage=LEVERAGE)
                        if success:
                            order_success = True
                    except Exception as e:
                        print(f"[ORDER ERROR] {symbol}: {e}")

                    if order_success:
                        from database import log_trade
                        log_trade(symbol, mark_price, take_profit_val, stop_loss_val, 
                                  side=side, score=combined_score, reason=reason,
                                  rsi=rsi, vwap=vwap_dist, rvol=rvol, sentiment=market_sentiment)
                        last_exec_time = time.time()
                        _consec_losses = 0
                        # Log lengkap kenapa bot masuk trade ini
                        # AMBIL DATA REAL-TIME WS UNTUK LOG
                        try:
                            from shared_state import state as _ws_st
                            sym_ws = f"{clean_base}USDT"
                            rt_wbv = _ws_st.rt_whale_buy_vol.get(sym_ws, 0)
                            rt_wsv = _ws_st.rt_whale_sell_vol.get(sym_ws, 0)
                            rt_spread = _ws_st.rt_spread.get(sym_ws, 0)
                            rt_obi = _ws_st.rt_obi.get(sym_ws, 0)
                        except:
                            rt_wbv = rt_wsv = rt_spread = rt_obi = 0

                        # Hitung persentase take_profit_val/stop_loss_val untuk log
                        tp_pct = round(abs(take_profit_val - mark_price) / mark_price * 100, 2)
                        sl_pct = round(abs(stop_loss_val - mark_price) / mark_price * 100, 2)

                        print(
                            f"\n[ENTRY] {clean_base} {side.upper()} @ {mark_price} | "
                            f"Score:{combined_score} | stop_loss_val:{stop_loss_val}(-{sl_pct}%) take_profit_val:{take_profit_val}(+{tp_pct}%)\n"
                            f"  Why: {reason}\n"
                            f"  [TECH] RSI:{float(rsi):.1f} VWAP:{float(vwap_dist):+.2f}% OBI:{float(tech.get('obi',0)):+.2f} Trend1h:{tech.get('trend_1h','?')}\n"
                            f"  [WS-RT] WhaleVol: B:${float(rt_wbv):,.0f} / S:${float(rt_wsv):,.0f} | OBI:{float(rt_obi):+.2f} | Spread:{float(rt_spread):.3f}%\n"
                            f"  [SCAN] OI:{float(tech.get('open_interest',0)):.0f} Funding:{float(tech.get('funding_rate',0)):.5f} ADX:{float(tech.get('adx',0)):.1f}\n"
                            f"  [5M-PRECISION] Signal:{tech.get('entry_signal_5m','?')}({tech.get('entry_quality_5m',0)}) | Zone:{tech.get('zone_freshness_5m','?')}",
                            flush=True
                        )

                        # --- SETTINGAN DEWA v28.0 (Rank #1 Grid Search) ---
                        # TSL dihandle oleh executor (BitgetExecutor) atau manual monitoring

                        # KIRIM NOTIF TELEGRAM
                        tg_data = {
                            'symbol': symbol, 'side': side, 'price': mark_price, 'amount': amount,
                            'score': combined_score, 'reason': reason, 'take_profit_val': take_profit_val, 'stop_loss_val': stop_loss_val,
                            'tp_pct': tp_pct, 'sl_pct': sl_pct,
                            'rsi': round(rsi, 1), 'vwap': round(vwap_dist, 2),
                            'obi_rest': round(tech.get('obi', 0), 2),
                            'trend_1h': tech.get('trend_1h', '?'),
                            'rt_wbv': rt_wbv, 'rt_wsv': rt_wsv, 'rt_obi': rt_obi, 'rt_spread': rt_spread,
                            'e5m': tech.get('entry_signal_5m', '?'),
                            'q5m': tech.get('entry_quality_5m', 0),
                            'f5m': tech.get('zone_freshness_5m', '?')
                        }
                        send_telegram_message(format_trade_message(tg_data))
                    else:
                        print(f"[ORDER FAILED] {clean_base}: {order}")
                else:
                    print(f"[MARGIN GUARD] Insufficient margin for {clean_base}.")

            else:
                # Tidak ada kandidat yang lolos - log alasan umum
                if int(now) % 30 < 10:
                    print(
                        f"[NO SIGNAL] 0 kandidat lolos dari {min(40, len(candidates))} koin. "
                        f"Kondisi: Sentiment={market_sentiment} BTC={btc_ctx['trend']} "
                        f"FRED={fred_bias} DUNE={dune_trend}({dune_activity})",
                        flush=True
                    )

            time.sleep(SCAN_INTERVAL)

        except Exception as e:
            print(f"[ENGINE ERROR] {e}")
            time.sleep(30)



