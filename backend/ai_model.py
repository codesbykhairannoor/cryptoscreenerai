"""
PUMP PREDICTOR ENGINE v1.0
===========================
Deteksi koin yang AKAN pump sebelum pump terjadi.

Sinyal pump yang valid (berdasarkan market microstructure):
1. OI naik + harga naik = fresh longs masuk → bullish
2. OI naik + harga turun = fresh shorts masuk → bearish (short squeeze candidate)
3. Funding rate negatif + OI tinggi = short squeeze imminent
4. Volume spike 3x+ dari rata-rata = institutional accumulation
5. Bid/Ask imbalance > 0.2 = buyer dominance
6. Harga baru breakout dari range 4 jam terakhir = momentum entry
7. Whale buy > $100k dalam 5 menit = smart money masuk
"""

import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

# Gemini client (opsional, tidak dipakai untuk coin selection)
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None


def analyze_and_sort(raw_data):
    """
    SPREAD-AWARE COIN SELECTOR v4.0
    =================================
    Fix v3.0: Volume surge API dipanggil per-koin = 30 API calls = timeout.
    Sekarang: Pre-fetch volume 1h untuk semua koin sekaligus via batch,
    lalu scoring menggunakan data yang sudah ada di ticker (vol 24h).
    
    Scoring berbasis data yang SUDAH ADA di ticker response:
    - quoteVolume 24h vs threshold absolut (tidak butuh API tambahan)
    - range 24h (high-low) sebagai proxy volatilitas
    - % change posisi dalam range
    - Funding rate (1 API call per koin, tapi async-friendly)
    """
    import pandas as pd

    if not raw_data:
        return []

    df = pd.DataFrame(raw_data)
    if len(df) == 0:
        return []

    # ── Normalisasi kolom ─────────────────────────────────────────────────────
    col_map = {
        'priceChangePercent': ['priceChangePercent', 'chgPct', 'change', 'change24h'],
        'quoteVolume':        ['quoteVolume', 'quoteVol', 'usdtVolume', 'vol'],
        'lastPrice':          ['lastPrice', 'last', 'close', 'price'],
        'high24h':            ['high24h', 'high', 'highPrice'],
        'low24h':             ['low24h', 'low', 'lowPrice'],
        'symbol':             ['symbol', 'instId'],
    }
    for target, alts in col_map.items():
        if target not in df.columns:
            for alt in alts:
                if alt in df.columns:
                    df[target] = df[alt]
                    break
        if target not in df.columns:
            df[target] = 0

    for col in ['quoteVolume', 'priceChangePercent', 'lastPrice', 'high24h', 'low24h']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # ── BLACKLIST ─────────────────────────────────────────────────────────────
    def is_blacklisted(sym):
        base = sym.upper().replace('USDT', '').replace('_UMCBL', '').replace('PERP', '')
        skip = {'BTC', 'ETH', 'USDC', 'USDT', 'DAI', 'BUSD', 'TUSD', 'FDUSD',
                'WBTC', 'WETH', 'WBNB'}
        if base in skip:
            return True
        if any(base.endswith(x) for x in ['UP', 'DOWN', 'BULL', 'BEAR', '3L', '3S']):
            return True
        return False

    df = df[~df['symbol'].apply(is_blacklisted)]
    df = df[df['quoteVolume'] > 1_000_000]   # Min $1M volume
    df = df[df['priceChangePercent'] < 20]    # Belum pump terlalu jauh
    df = df[df['priceChangePercent'] > -25]   # Bukan panic sell

    # Range 24h
    df['range_pct'] = ((df['high24h'] - df['low24h']) / df['low24h'].replace(0, 1)) * 100
    df = df[df['range_pct'] > 3.0]

    if len(df) == 0:
        return []

    # ── SCORING — HANYA PAKAI DATA YANG SUDAH ADA (tidak butuh API tambahan) ──
    def pump_score(row):
        score = 0.0
        vol   = float(row.get('quoteVolume', 0))
        pct   = float(row.get('priceChangePercent', 0))
        price = float(row.get('lastPrice', 0))
        high  = float(row.get('high24h', price * 1.01))
        low   = float(row.get('low24h',  price * 0.99))
        rng   = float(row.get('range_pct', 0))

        # ── 1. VOLATILITAS RANGE (max 30 poin) ───────────────────────────────
        # Range besar = koin bisa bergerak 8% untuk hit TP
        if rng >= 20:    score += 30
        elif rng >= 15:  score += 25
        elif rng >= 10:  score += 20
        elif rng >= 7:   score += 15
        elif rng >= 5:   score += 10
        elif rng >= 3:   score += 5

        # ── 2. VOLUME ABSOLUT (max 25 poin) ──────────────────────────────────
        # Volume besar = likuiditas, slippage kecil
        if vol >= 100_000_000:   score += 25   # $100M+
        elif vol >= 50_000_000:  score += 20   # $50M+
        elif vol >= 20_000_000:  score += 15   # $20M+
        elif vol >= 10_000_000:  score += 10   # $10M+
        elif vol >= 5_000_000:   score += 7    # $5M+
        elif vol >= 2_000_000:   score += 4    # $2M+

        # ── 3. POSISI HARGA DI RANGE (max 25 poin) ───────────────────────────
        # Harga di 10-45% dari range = early entry, belum terlambat
        if high > low and price > 0:
            pos = (price - low) / (high - low) * 100
            if 10 <= pos <= 35:   score += 25   # Dekat bottom, ideal long
            elif 35 < pos <= 50:  score += 18   # Di bawah tengah
            elif 50 < pos <= 65:  score += 10   # Di atas tengah
            elif pos > 85:        score -= 5    # Dekat puncak, risky

        # ── 4. MOMENTUM AWAL (max 20 poin) ───────────────────────────────────
        # Koin yang baru mulai bergerak = early entry
        if 1.5 <= pct <= 6:    score += 20   # Sweet spot
        elif 0.5 <= pct < 1.5: score += 12   # Mulai bergerak
        elif 6 < pct <= 12:    score += 8    # Sudah bergerak, masih bisa
        elif pct < 0:          score += 5    # Turun = reversal candidate

        # ── BONUS: Whale + OBI dari WebSocket ────────────────────────────────
        try:
            from shared_state import state
            sym   = str(row.get('symbol', ''))
            whale = state.rt_whale.get(sym, '')
            obi   = state.rt_obi.get(sym, 0)
            if whale == 'WHALE_BUY':  score += 20
            elif whale == 'WHALE_SELL': score -= 5
            if obi > 0.15:            score += 10
            elif obi < -0.15:         score -= 5
        except Exception:
            pass

        return max(0.0, min(100.0, score))

    df['pump_score'] = df.apply(pump_score, axis=1)
    df_sorted = df.sort_values(by='pump_score', ascending=False).head(30)

    # Log top 5
    print(f"[PUMP PREDICTOR] Top 5 candidates:")
    for _, row in df_sorted.head(5).iterrows():
        sym  = row.get('symbol', '')
        pct  = round(float(row.get('priceChangePercent', 0)), 2)
        rng  = round(float(row.get('range_pct', 0)), 1)
        vol  = round(float(row.get('quoteVolume', 0)) / 1_000_000, 1)
        sc   = round(float(row.get('pump_score', 0)), 1)
        pos_in_range = 0
        h = float(row.get('high24h', 0))
        l = float(row.get('low24h', 0))
        p = float(row.get('lastPrice', 0))
        if h > l: pos_in_range = round((p - l) / (h - l) * 100, 0)
        print(f"  {sym}: {pct:+.1f}% | Range {rng}% | Pos {pos_in_range:.0f}% | Vol ${vol}M | Score {sc}/100")

    return df_sorted.to_dict('records')


def smart_trade_decision(symbol, technicals, news):
    """Tidak dipakai lagi — diganti pump predictor scoring."""
    return True, "Pump predictor approved"


def analyze_market_data(data_json):
    """Untuk frontend dashboard — tetap pakai Gemini kalau tersedia."""
    if not client:
        return "Gemini API Key tidak tersedia."
    try:
        prompt = f"""
        Analyze this crypto/market data and provide 3 hot trading recommendations.
        Focus on whale activity, RSI momentum, and MTF trend confirmation.
        Data: {data_json}
        Format your response in professional Indonesian, use emojis, and be concise.
        Include Entry, TP, and SL for each recommendation.
        """
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        return response.text
    except Exception as e:
        return f"Gagal analisis: {e}"