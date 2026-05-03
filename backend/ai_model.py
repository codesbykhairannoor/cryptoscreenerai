import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

# Configure the Gemini API with the provided key
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

def analyze_and_sort(raw_data):
    """
    GENIUS COIN SELECTOR v2.0
    ===========================
    Bukan sekedar sort by % change — itu cara beli di puncak.
    
    Logika seleksi:
    1. Filter likuiditas minimum $1M volume/hari (hindari slippage)
    2. Filter koin yang SEDANG BERGERAK (volume spike vs rata-rata)
    3. Prioritas koin yang baru breakout DARI BAWAH (bukan yang sudah naik jauh)
    4. Score gabungan: momentum + volume + posisi harga vs range
    5. Blacklist stablecoin, wrapped token, dan koin terlalu kecil
    """
    import pandas as pd

    if not raw_data:
        return []

    df = pd.DataFrame(raw_data)
    if len(df) == 0:
        return []

    # ── Normalisasi nama kolom ────────────────────────────────────────────────
    col_map = {
        'priceChangePercent': ['priceChangePercent', 'chgPct', 'change', 'change24h'],
        'quoteVolume':        ['quoteVolume', 'quoteVol', 'usdtVolume', 'vol'],
        'lastPrice':          ['lastPrice', 'last', 'close', 'price'],
        'high24h':            ['high24h', 'high', 'highPrice'],
        'low24h':             ['low24h', 'low', 'lowPrice'],
    }
    for target, alts in col_map.items():
        if target not in df.columns:
            for alt in alts:
                if alt in df.columns:
                    df[target] = df[alt]
                    break
        if target not in df.columns:
            df[target] = 0

    # ── Konversi numerik ──────────────────────────────────────────────────────
    for col in ['quoteVolume', 'priceChangePercent', 'lastPrice', 'high24h', 'low24h']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # ── BLACKLIST: stablecoin, wrapped, leverage token ────────────────────────
    blacklist_keywords = ['USD', 'DAI', 'BUSD', 'TUSD', 'USDC', 'FDUSD',
                          'WBTC', 'WETH', 'WBNB', 'UP', 'DOWN', 'BULL', 'BEAR',
                          'BTC', 'ETH']  # BTC/ETH terlalu mahal untuk modal kecil
    mask_blacklist = df['symbol'].str.upper().apply(
        lambda s: not any(s.replace('USDT', '').replace('_UMCBL', '') == kw
                          or s.startswith(kw) for kw in blacklist_keywords)
    )
    df = df[mask_blacklist]

    # ── FILTER 1: Likuiditas minimum $1M/hari ─────────────────────────────────
    df = df[df['quoteVolume'] > 1_000_000]

    if len(df) == 0:
        # Fallback ke $500k kalau tidak ada yang lolos
        df = pd.DataFrame(raw_data)
        for col in ['quoteVolume', 'priceChangePercent', 'lastPrice', 'high24h', 'low24h']:
            df[col] = pd.to_numeric(df.get(col, 0), errors='coerce').fillna(0)
        df = df[df['quoteVolume'] > 500_000]

    # ── FILTER 2: Koin yang BERGERAK (% change tidak terlalu kecil) ───────────
    # Minimal ada gerakan 0.5% — koin flat tidak menarik untuk scalping
    df = df[df['priceChangePercent'].abs() > 0.5]

    # ── FILTER 3: Hindari koin yang sudah terlalu jauh naik/turun ────────────
    # Koin yang naik >15% hari ini kemungkinan besar sudah overbought
    # Koin yang turun >15% kemungkinan besar sedang panic sell
    df = df[df['priceChangePercent'].abs() < 15]

    # ── SCORING SYSTEM ────────────────────────────────────────────────────────
    def score_coin(row):
        score = 0.0
        pct   = float(row.get('priceChangePercent', 0))
        vol   = float(row.get('quoteVolume', 0))
        price = float(row.get('lastPrice', 0))
        high  = float(row.get('high24h', price))
        low   = float(row.get('low24h', price))

        # 1. Volume score (max 40 poin) — volume besar = likuiditas bagus
        if vol > 50_000_000:   score += 40
        elif vol > 20_000_000: score += 30
        elif vol > 10_000_000: score += 20
        elif vol > 5_000_000:  score += 15
        elif vol > 2_000_000:  score += 10
        else:                  score += 5

        # 2. Momentum score (max 30 poin) — gerakan sedang, bukan ekstrem
        abs_pct = abs(pct)
        if 2 <= abs_pct <= 8:    score += 30  # Sweet spot: bergerak tapi belum jauh
        elif 1 <= abs_pct < 2:   score += 20  # Mulai bergerak
        elif 8 < abs_pct <= 12:  score += 10  # Sudah jauh, hati-hati
        elif abs_pct > 12:       score += 0   # Terlalu jauh

        # 3. Posisi harga dalam range 24h (max 30 poin)
        # Untuk LONG: ideal kalau harga di 20-50% dari range (bukan di puncak)
        # Untuk SHORT: ideal kalau harga di 50-80% dari range
        if high > low and price > 0:
            pos_in_range = (price - low) / (high - low) * 100
            if 20 <= pos_in_range <= 50:   score += 30  # Di bawah tengah — bagus untuk long
            elif 50 < pos_in_range <= 70:  score += 20  # Di tengah
            elif pos_in_range > 80:        score += 5   # Dekat puncak — risky untuk long
            elif pos_in_range < 20:        score += 15  # Dekat bottom — bisa reversal

        return score

    df['genius_score'] = df.apply(score_coin, axis=1)

    # ── SORT: Score tertinggi dulu ────────────────────────────────────────────
    df_sorted = df.sort_values(by='genius_score', ascending=False).head(30)

    # Log top 5 untuk debugging
    if len(df_sorted) > 0:
        top5 = df_sorted.head(5)[['symbol', 'priceChangePercent', 'quoteVolume', 'genius_score']].to_dict('records')
        print(f"[GENIUS SELECTOR] Top 5 candidates:")
        for c in top5:
            sym = c.get('symbol', '')
            pct = round(float(c.get('priceChangePercent', 0)), 2)
            vol = round(float(c.get('quoteVolume', 0)) / 1_000_000, 1)
            sc  = round(float(c.get('genius_score', 0)), 1)
            print(f"  {sym}: {pct}% | Vol ${vol}M | Score {sc}")

    return df_sorted.to_dict('records')

def smart_trade_decision(symbol, technicals, news):
    """
    Final Filter: Uses Gemini to decide if we should actually place the trade.
    Returns: (bool, str_reason)
    """
    if not client: return False, "Gemini Client not initialized"
    
    try:
        prompt = f"""
        TIDAK BOLEH ASAL TRADE! Anda adalah Risk Manager Pro.
        Analisa apakah kita harus masuk ke trade ini sekarang?
        
        Aset: {symbol}
        Data Teknikal: {technicals}
        Berita Terkini: {news}
        
        Aturan: 
        1. Hanya katakan SETUJU jika teknikal (RSI, Trend, OB/FVG) DAN berita mendukung.
        2. Jika berita negatif atau teknikal jenuh (overbought), katakan TOLAK.
        
        Format Jawaban Harus:
        KEPUTUSAN: [SETUJU/TOLAK]
        ALASAN: [Berikan alasan singkat dan padat]
        """
        
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        text = response.text
        decision = "SETUJU" in text.upper()
        return decision, text
    except Exception as e:
        return False, f"AI Error: {str(e)}"

def analyze_market_data(data_json):
    if not client:
        return "API Key Gemini belum diset di .env"
    try:
        prompt = f"""
        Analyze this crypto/market data and provide 3 hot trading recommendations.
        Focus on whale activity, RSI momentum, and MTF trend confirmation.
        Data: {data_json}
        Format your response in professional Indonesian, use emojis, and be concise.
        Include Entry, TP, and SL for each recommendation.
        """
        
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"AI Analysis Error: {e}")
        return "Gagal melakukan analisis AI. Silakan cek koneksi atau API Key Anda."