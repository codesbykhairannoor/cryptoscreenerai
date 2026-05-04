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
    SPREAD-AWARE COIN SELECTOR v3.0
    =================================
    Dengan fee 0.12% round trip (1.2% PnL di 10x), kita butuh:
    - Koin yang BISA bergerak minimal 8% dalam satu sesi
    - Volume cukup besar agar tidak kena slippage
    - Sinyal pre-pump yang kuat sebelum masuk

    Filter ketat:
    1. Volume $2M+/hari — likuiditas cukup, slippage minimal
    2. ATR 24h > 5% dari harga — koin yang memang volatile
    3. Bukan koin yang sudah pump >15% hari ini (terlambat)
    4. Bukan koin yang turun >20% (panic sell, hindari)
    5. Pump score berdasarkan volume spike + OI + funding + posisi range
    """
    import pandas as pd
    import requests

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

    # ── FILTER 1: Volume minimum $2M/hari ─────────────────────────────────────
    df = df[df['quoteVolume'] > 2_000_000]

    # ── FILTER 2: Koin yang sudah pump >15% dibuang (terlambat masuk) ─────────
    df = df[df['priceChangePercent'] < 15]

    # ── FILTER 3: Hindari panic sell >20% turun ───────────────────────────────
    df = df[df['priceChangePercent'] > -20]

    # ── FILTER 4: Koin harus VOLATILE — range 24h > 4% dari harga ────────────
    # Ini filter terpenting: koin yang range-nya kecil tidak akan hit TP 8%
    df['range_pct'] = ((df['high24h'] - df['low24h']) / df['low24h'].replace(0, 1)) * 100
    df = df[df['range_pct'] > 4.0]

    if len(df) == 0:
        # Fallback: longgarkan filter kalau tidak ada yang lolos
        df = pd.DataFrame(raw_data)
        for col in ['quoteVolume', 'priceChangePercent', 'lastPrice', 'high24h', 'low24h']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        df = df[df['quoteVolume'] > 1_000_000]
        df['range_pct'] = ((df['high24h'] - df['low24h']) / df['low24h'].replace(0, 1)) * 100
        df = df[df['range_pct'] > 2.0]

    # ── PUMP PREDICTION SCORING ───────────────────────────────────────────────
    def pump_score(row):
        score  = 0.0
        sym    = str(row.get('symbol', ''))
        vol    = float(row.get('quoteVolume', 0))
        pct    = float(row.get('priceChangePercent', 0))
        price  = float(row.get('lastPrice', 0))
        high   = float(row.get('high24h', price * 1.01))
        low    = float(row.get('low24h',  price * 0.99))
        rng    = float(row.get('range_pct', 0))

        # ── SINYAL 1: Volatilitas koin (max 25 poin) ──────────────────────────
        # Koin yang range-nya besar = lebih mudah hit TP 8%
        if rng >= 15:    score += 25
        elif rng >= 10:  score += 20
        elif rng >= 7:   score += 15
        elif rng >= 5:   score += 10
        elif rng >= 4:   score += 5

        # ── SINYAL 2: Volume Surge 1h vs rata-rata (max 30 poin) ─────────────
        try:
            url = (f"https://api.bitget.com/api/v2/mix/market/history-candles"
                   f"?symbol={sym}&granularity=1h&limit=24&productType=USDT-FUTURES")
            r = requests.get(url, timeout=3, verify=False)
            if r.status_code == 200:
                candles = r.json().get('data', [])
                if len(candles) >= 4:
                    vols = [float(c[5]) for c in candles]
                    avg_vol_1h = sum(vols[:-1]) / len(vols[:-1])
                    last_vol_1h = vols[-1]
                    vol_ratio = last_vol_1h / avg_vol_1h if avg_vol_1h > 0 else 1
                    if vol_ratio >= 5:     score += 30
                    elif vol_ratio >= 3:   score += 22
                    elif vol_ratio >= 2:   score += 14
                    elif vol_ratio >= 1.5: score += 7
        except Exception:
            pass

        # ── SINYAL 3: Funding Rate (max 20 poin) ─────────────────────────────
        try:
            fr_url = (f"https://api.bitget.com/api/v2/mix/market/current-funding-rate"
                      f"?symbol={sym}&productType=USDT-FUTURES")
            fr_r = requests.get(fr_url, timeout=3, verify=False)
            if fr_r.status_code == 200:
                fr_data = fr_r.json().get('data', [{}])
                fr = float(fr_data[0].get('fundingRate', 0)) if fr_data else 0
                if fr < -0.0005:   score += 20   # Short squeeze imminent
                elif fr < -0.0002: score += 12
                elif fr > 0.001:   score -= 10   # Longs terlalu mahal
        except Exception:
            pass

        # ── SINYAL 4: Posisi harga di range (max 15 poin) ────────────────────
        # Harga di 15-40% dari range = early entry, belum terlambat
        if high > low and price > 0:
            pos = (price - low) / (high - low) * 100
            if 15 <= pos <= 40:   score += 15
            elif 40 < pos <= 60:  score += 8
            elif pos > 80:        score -= 5

        # ── SINYAL 5: Momentum awal (max 10 poin) ────────────────────────────
        if 1 <= pct <= 8:      score += 10
        elif 0.5 <= pct < 1:   score += 5
        elif pct < 0:          score += 3

        # ── BONUS: Whale + OBI dari WebSocket ────────────────────────────────
        try:
            from shared_state import state
            whale = state.rt_whale.get(sym, '')
            obi   = state.rt_obi.get(sym, 0)
            if whale == 'WHALE_BUY':  score += 15
            if obi > 0.15:            score += 10
        except Exception:
            pass

        return max(0.0, min(100.0, score))

    df['pump_score'] = df.apply(pump_score, axis=1)
    df_sorted = df.sort_values(by='pump_score', ascending=False).head(30)

    # Log top 5
    print(f"[PUMP PREDICTOR] Top 5 candidates (fee-aware, need 8%+ move):")
    for _, row in df_sorted.head(5).iterrows():
        sym  = row.get('symbol', '')
        pct  = round(float(row.get('priceChangePercent', 0)), 2)
        rng  = round(float(row.get('range_pct', 0)), 1)
        vol  = round(float(row.get('quoteVolume', 0)) / 1_000_000, 1)
        sc   = round(float(row.get('pump_score', 0)), 1)
        print(f"  {sym}: {pct:+.1f}% | Range {rng}% | Vol ${vol}M | Score {sc}/100")

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