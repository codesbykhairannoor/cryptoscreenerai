"""
CRYPTO SCALPER ENGINE v5.0 — ONE TRADE ALL-IN DAILY SCALPER
============================================================
Filosofi: 1 trade terbaik per hari, pakai semua modal, scalp cepat.

- MAX_POSITIONS: 1  (fokus total, satu koin terbaik)
- SCAN_INTERVAL: 8s
- COOLDOWN: 30s setelah trade tutup
- LEVERAGE: 10x
- MIN_SCORE: 45 (berani tapi tidak asal)
- TP: 1.5% price (15% PnL di 10x) — scalp cepat
- SL: 0.8% price (8% PnL di 10x) — cut loss cepat
- Skip BTC/ETH, fokus altcoin volatile mid-cap
- Pakai 95% modal untuk satu trade
"""

import time
import requests
from data_fetcher import (
    fetch_all_tickers, get_technical_indicators,
    get_retail_sentiment, detect_institutional_flow
)
from sentiment import get_crypto_news, get_global_market_data
from ai_model import analyze_and_sort
from database import log_trade
from bitget_executor import BitgetExecutor

# ─── KONFIGURASI: ONE TRADE ALL-IN ────────────────────────────────────────────
MAX_POSITIONS        = 1      # SATU trade terbaik, semua modal
SCAN_INTERVAL        = 8      # Scan setiap 8 detik
COOLDOWN_AFTER_TRADE = 30     # Cooldown 30 detik setelah trade selesai
NEWS_REPORT_INTERVAL = 600
GLOBAL_REPORT_INTERVAL = 300
LEVERAGE             = 10     # 10x leverage
MIN_MOMENTUM_SCORE   = 45     # Threshold — berani tapi tidak asal
DAILY_LOSS_LIMIT_PCT = -40    # Circuit breaker

# Scalp target — TP 50% PnL, SL 12% PnL di 10x leverage
# 10x leverage: 1% price move = 10% PnL
# TP 50% PnL = 5% price move
# SL 12% PnL = 1.2% price move
SCALP_TP_PCT         = 0.05   # TP 5% price move  (= 50% PnL di 10x) ✅
SCALP_SL_PCT         = 0.012  # SL 1.2% price move (= 12% PnL di 10x) ✅
# ATR multiplier kalau ATR tersedia
SCALP_TP_ATR         = 4.0    # TP = 4x ATR
SCALP_SL_ATR         = 1.0    # SL = 1x ATR (tight)

# ─── HELPER: HITUNG VWAP ──────────────────────────────────────────────────────
def _calc_vwap_dist(mark_price: float, symbol: str) -> float:
    """Hitung jarak harga dari VWAP dalam persen menggunakan candle 15m."""
    try:
        url = (
            f"https://api.bitget.com/api/v2/mix/market/history-candles"
            f"?symbol={symbol}&granularity=15m&limit=96&productType=USDT-FUTURES"
        )
        r = requests.get(url, timeout=5, verify=False)
        if r.status_code != 200:
            return 0.0
        data = r.json().get('data', [])
        if not data:
            return 0.0

        cum_pv = 0.0
        cum_v  = 0.0
        for c in data:
            # [ts, open, high, low, close, vol, vol_usd]
            typical = (float(c[2]) + float(c[3]) + float(c[4])) / 3
            vol     = float(c[5])
            cum_pv += typical * vol
            cum_v  += vol

        if cum_v == 0:
            return 0.0
        vwap = cum_pv / cum_v
        dist = ((mark_price - vwap) / vwap) * 100
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
        if 30 <= rsi <= 50:   score += 25   # Oversold recovery — ideal
        elif 50 < rsi <= 60:  score += 15   # Momentum building
        elif 20 <= rsi < 30:  score += 10   # Terlalu oversold, risky
        elif rsi > 70:        score -= 10   # Overbought, skip
    else:  # sell
        if 50 <= rsi <= 70:   score += 25   # Overbought rejection — ideal
        elif 40 <= rsi < 50:  score += 15   # Momentum bearish
        elif rsi > 80:        score += 10   # Terlalu overbought, risky
        elif rsi < 30:        score -= 10   # Oversold, skip short

    # 2. VWAP Distance (max 20 poin)
    if side == "buy":
        if -3.0 <= vwap_dist <= -0.5:  score += 20  # Di bawah VWAP — discount zone
        elif -0.5 < vwap_dist <= 0.5:  score += 10  # Dekat VWAP
        elif vwap_dist > 3.0:          score -= 10  # Terlalu jauh di atas VWAP
    else:
        if 0.5 <= vwap_dist <= 3.0:    score += 20  # Di atas VWAP — premium zone
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
        long_candidates.append((s, "BULLISH FVG RE-ENTRY (INSTITUTIONAL DISCOUNT)"))

    # Setup 3: MSS Bullish Breakout
    if mss_b and obi > 0.05:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "MARKET STRUCTURE SHIFT BULLISH (MSS BREAKOUT)"))

    # Setup 4: CHoCH + Liquidity Sweep (Reversal)
    if choch_b and liq and rsi < 55:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "CHoCH REVERSAL + LIQUIDITY SWEEP"))

    # Setup 5: Bullish OB + Oversold RSI
    if ob == 'BULLISH_OB' and rsi < 45:
        s = _score_candidate(tech, rsi, vwap_dist, "buy")
        long_candidates.append((s, "BULLISH ORDER BLOCK + OVERSOLD RSI"))

    # ── SHORT SETUPS ─────────────────────────────────────────────────────────
    short_candidates = []

    # Setup 1: Whale Distribution + Premium Zone
    if whale == 'WHALE_SELL' and vwap_dist > 0.5:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "WHALE DISTRIBUTION + PREMIUM ZONE"))

    # Setup 2: Bearish FVG Rejection
    if fvg == 'BEARISH_FVG' and rsi > 45:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "BEARISH FVG REJECTION (INSTITUTIONAL PREMIUM)"))

    # Setup 3: MSS Bearish Breakdown
    if mss_s and obi < -0.05:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "MARKET STRUCTURE SHIFT BEARISH (MSS BREAKDOWN)"))

    # Setup 4: CHoCH + Liquidity Sweep (Bearish Reversal)
    if choch_s and liq and rsi > 50:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "CHoCH BEARISH REVERSAL + LIQUIDITY SWEEP"))

    # Setup 5: Bearish OB + Overbought RSI
    if ob == 'BEARISH_OB' and rsi > 60:
        s = _score_candidate(tech, rsi, vwap_dist, "sell")
        short_candidates.append((s, "BEARISH ORDER BLOCK + OVERBOUGHT RSI"))

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


# ─── CORE: HITUNG TP/SL BERBASIS ATR ─────────────────────────────────────────
def _calc_tp_sl(mark_price: float, side: str, tech: dict) -> tuple[float, float]:
    """
    Scalp TP/SL: ambil profit cepat, cut loss cepat.
    ATR-based kalau tersedia, fallback ke fixed %.
    """
    atr = tech.get('atr', 0)
    if atr and atr > 0:
        sl_dist = atr * SCALP_SL_ATR
        tp_dist = atr * SCALP_TP_ATR
    else:
        sl_dist = mark_price * SCALP_SL_PCT
        tp_dist = mark_price * SCALP_TP_PCT

    if side == "buy":
        return round(mark_price + tp_dist, 6), round(mark_price - sl_dist, 6)
    else:
        return round(mark_price - tp_dist, 6), round(mark_price + sl_dist, 6)


# ─── MAIN ENGINE ──────────────────────────────────────────────────────────────
def run_crypto_engine():
    """
    [CRYPTO SCALPER v5.0] — One Trade All-In Daily Scalper.
    Satu koin terbaik, semua modal, scalp cepat, repeat.
    """
    executor = BitgetExecutor()
    from database import check_pending_trades, get_performance_stats
    from sentiment import get_market_news_digest

    print("[CRYPTO SCALPER v5.0] One Trade All-In Mode AKTIF!")
    print(f"  Strategy: 1 trade terbaik | {LEVERAGE}x leverage | TP {SCALP_TP_PCT*100}% | SL {SCALP_SL_PCT*100}%")

    last_exec_time    = 0
    last_news_report  = 0
    last_global_report = 0
    _dxy_cache        = {"trend": "NEUTRAL", "ts": 0}

    while True:
        try:
            # ── 1. MANAGE EXISTING POSITIONS ─────────────────────────────────
            executor.manage_open_positions()
            check_pending_trades()

            # ── 2. NEWS VELOCITY (setiap 10 menit) ───────────────────────────
            now = time.time()
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
            daily_pnl = stats.get('win_rate', 0)
            if daily_pnl < DAILY_LOSS_LIMIT_PCT:
                print(f"[CIRCUIT BREAKER] Daily loss limit {DAILY_LOSS_LIMIT_PCT}% reached. "
                      f"Standing down for 30 minutes.")
                time.sleep(1800)
                continue

            # ── 5. POSITION LIMIT CHECK ───────────────────────────────────────
            positions   = executor.get_all_positions()
            open_count  = len(positions) if isinstance(positions, list) else 0
            open_bases  = [executor._clean_symbol(p['symbol']) for p in positions] \
                          if isinstance(positions, list) else []

            print(f"[ENGINE] Open: {open_count}/{MAX_POSITIONS} | "
                  f"Bases: {open_bases if open_bases else 'None'}")

            if open_count >= MAX_POSITIONS:
                print(f"[LIMIT] Max {MAX_POSITIONS} positions reached. Managing existing trades.")
                time.sleep(SCAN_INTERVAL)
                continue

            # ── 6. SCAN CANDIDATES ────────────────────────────────────────────
            raw_data   = fetch_all_tickers()
            candidates = analyze_and_sort(raw_data)
            print(f"[SCANNER] {len(candidates)} candidates after basic filter.")

            if not candidates:
                time.sleep(SCAN_INTERVAL)
                continue

            # ── 7. MARKET SENTIMENT ───────────────────────────────────────────
            digest           = get_market_news_digest()
            market_sentiment = digest.get('sentiment', 'NEUTRAL')

            # ── 8. DXY CACHE (update setiap 5 menit) ─────────────────────────
            if now - _dxy_cache["ts"] > 300:
                try:
                    from data_fetcher import get_forex_data
                    dxy = get_forex_data("DXY")
                    _dxy_cache["trend"] = dxy.get('trend', 'NEUTRAL') if dxy else 'NEUTRAL'
                    _dxy_cache["change"] = dxy.get('change', 0) if dxy else 0
                    _dxy_cache["ts"]    = now
                except Exception:
                    pass
            dxy_trend  = _dxy_cache.get("trend", "NEUTRAL")
            dxy_change = _dxy_cache.get("change", 0)

            # ── 9. SCAN LOOP ──────────────────────────────────────────────────
            traded_this_cycle = False
            for coin in candidates[:25]:
                if traded_this_cycle:
                    break
                if time.time() - last_exec_time < COOLDOWN_AFTER_TRADE:
                    break

                symbol     = coin.get('symbol', '')
                clean_base = executor._clean_symbol(symbol)

                # Skip kalau sudah ada posisi di coin ini
                if clean_base in open_bases:
                    continue

                # Skip BTC dan ETH — terlalu mahal untuk modal kecil, volatilitas rendah
                if clean_base in ('BTC', 'ETH'):
                    continue

                # Skip stablecoin dan wrapped token
                if any(x in clean_base for x in ('USD', 'DAI', 'BUSD', 'TUSD', 'WBTC', 'WETH')):
                    continue

                # ── 9a. AMBIL INDIKATOR TEKNIKAL ─────────────────────────────
                tech = get_technical_indicators(symbol)
                if not tech:
                    continue

                mark_price = tech.get('mark_price', 0)
                if mark_price == 0:
                    mark_price = float(coin.get('lastPrice', 0))
                if mark_price == 0:
                    continue

                # ── 9b. HITUNG RSI & VWAP DIST ───────────────────────────────
                rsi       = _calc_rsi(symbol)
                vwap_dist = _calc_vwap_dist(mark_price, symbol)

                # ── 9c. TENTUKAN SIDE & SCORE ─────────────────────────────────
                side, reason, score = _determine_trade_side(
                    tech, rsi, vwap_dist, market_sentiment
                )

                if side is None or score < MIN_MOMENTUM_SCORE:
                    continue

                # ── 9d. DXY OVERRIDE (hanya untuk long, bukan short) ──────────
                is_dxy_active = abs(dxy_change) > 0.0001
                if is_dxy_active and side == "buy" and dxy_trend == "BULLISH" and dxy_change > 0.2:
                    print(f"[DXY OVERRIDE] Dollar terlalu kuat, skip {clean_base} Long.")
                    continue

                # ── 9e. ORDER BOOK CONFIRMATION ───────────────────────────────
                from data_fetcher import get_order_book_details
                ob_data = get_order_book_details(symbol)
                ob_ratio = ob_data.get('ratio', 0)
                # Long butuh bid pressure, short butuh ask pressure
                if side == "buy"  and ob_ratio < 0.0:   continue  # Terlalu banyak seller
                if side == "sell" and ob_ratio > 0.0:   continue  # Terlalu banyak buyer

                # ── 9f. HITUNG TP/SL ──────────────────────────────────────────
                tp, sl = _calc_tp_sl(mark_price, side, tech)

                # ── 9g. HITUNG SIZE (20x leverage untuk modal kecil) ──────────
                amount = executor.get_max_available(symbol, leverage=LEVERAGE)
                if amount <= 0:
                    print(f"[MARGIN GUARD] Insufficient margin for {clean_base}.")
                    continue

                # ── 9h. EKSEKUSI ──────────────────────────────────────────────
                print(f"\n{'='*60}")
                print(f"[SCALPER v5.0] 🎯 {clean_base} {side.upper()} | Score: {score}/100")
                print(f"  Reason : {reason}")
                print(f"  Price  : {mark_price} | RSI: {rsi} | VWAP: {vwap_dist}%")
                print(f"  TP     : {tp} (+{round((tp/mark_price-1)*100,2)}%) | SL: {sl} (-{round((1-sl/mark_price)*100,2)}%)" if side=="buy" else f"  TP: {tp} | SL: {sl}")
                print(f"  Leverage: {LEVERAGE}x | Sentiment: {market_sentiment}")
                print(f"{'='*60}\n")

                success, order = executor.place_order(symbol, side, amount, tp=tp, sl=sl, leverage=LEVERAGE)
                if success:
                    log_trade(symbol, mark_price, tp, sl)
                    last_exec_time    = time.time()
                    traded_this_cycle = True
                    open_count       += 1
                    open_bases.append(clean_base)
                    print(f"[TRADE LOGGED] {clean_base} {side.upper()} @ {mark_price}")
                else:
                    print(f"[ORDER FAILED] {clean_base}: {order}")

            time.sleep(SCAN_INTERVAL)

        except Exception as e:
            print(f"[ENGINE ERROR] {e}")
            time.sleep(30)
