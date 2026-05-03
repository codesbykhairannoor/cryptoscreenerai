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
    PUMP PREDICTOR v1.0 — Deteksi koin yang AKAN pump.
    ====================================================
    Bukan sort by % change (itu beli di puncak).
    Ini deteksi sinyal PRE-PUMP sebelum harga bergerak.
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
        # Skip leverage tokens
        if any(base.endswith(x) for x in ['UP', 'DOWN', 'BULL', 'BEAR', '3L', '3S']):
            return True
        return False

    df = df[~df['symbol'].apply(is_blacklisted)]

    # ── FILTER LIKUIDITAS: minimum $500k/hari ─────────────────────────────────
    df = df[df['quoteVolume'] > 500_000]

    # ── FILTER: Koin yang sudah pump >20% dibuang (terlambat) ────────────────
    df = df[df['priceChangePercent'] < 20]

    if len(df) == 0:
        return []

    # ── PUMP PREDICTION SCORING ───────────────────────────────────────────────
    def pump_score(row):
        """
        Score 0-100 berdasarkan sinyal pre-pump.
        Makin tinggi = makin besar kemungkinan akan pump.
        """
        score  = 0.0
        sym    = str(row.get('symbol', ''))
        vol    = float(row.get('quoteVolume', 0))
        pct    = float(row.get('priceChangePercent', 0))
        price  = float(row.get('lastPrice', 0))
        high   = float(row.get('high24h', price * 1.01))
        low    = float(row.get('low24h',  price * 0.99))

        # ── SINYAL 1: Volume Surge (max 30 poin) ─────────────────────────────
        # Ambil volume 1h dari Bitget untuk bandingkan dengan rata-rata
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
                    if vol_ratio >= 5:    score += 30  # Volume 5x = sangat kuat
                    elif vol_ratio >= 3:  score += 22  # Volume 3x = kuat
                    elif vol_ratio >= 2:  score += 14  # Volume 2x = sedang
                    elif vol_ratio >= 1.5: score += 7  # Volume 1.5x = lemah
        except Exception:
            pass

        # ── SINYAL 2: OI + Harga (max 25 poin) ───────────────────────────────
        # OI naik + harga naik = fresh longs = bullish momentum
        try:
            oi_url = (f"https://api.bitget.com/api/v2/mix/market/open-interest"
                      f"?symbol={sym}&productType=USDT-FUTURES")
            oi_r = requests.get(oi_url, timeout=3, verify=False)
            if oi_r.status_code == 200:
                oi_data = oi_r.json().get('data', [{}])
                oi_val  = float(oi_data[0].get('openInterest', 0)) if oi_data else 0
                # Bandingkan dengan OI dari shared_state kalau ada
                from shared_state import state
                sym_ws = sym.replace('USDT', 'USDT')
                prev_oi = state.rt_oi.get(sym_ws, 0)
                if prev_oi > 0 and oi_val > 0:
                    oi_change = (oi_val - prev_oi) / prev_oi
                    if oi_change > 0.05 and pct > 0:   score += 25  # OI naik + harga naik
                    elif oi_change > 0.03 and pct > 0: score += 15
                    elif oi_change < -0.05 and pct < 0: score += 10  # OI turun + harga turun = shorts cover
                state.rt_oi[sym_ws] = oi_val
        except Exception:
            pass

        # ── SINYAL 3: Funding Rate (max 20 poin) ─────────────────────────────
        # Funding negatif = shorts bayar longs = short squeeze candidate
        try:
            fr_url = (f"https://api.bitget.com/api/v2/mix/market/current-funding-rate"
                      f"?symbol={sym}&productType=USDT-FUTURES")
            fr_r = requests.get(fr_url, timeout=3, verify=False)
            if fr_r.status_code == 200:
                fr_data = fr_r.json().get('data', [{}])
                fr = float(fr_data[0].get('fundingRate', 0)) if fr_data else 0
                if fr < -0.0005:   score += 20  # Sangat negatif = short squeeze imminent
                elif fr < -0.0002: score += 12  # Negatif = shorts tertekan
                elif fr > 0.001:   score -= 10  # Terlalu positif = longs mahal, risky
        except Exception:
            pass

        # ── SINYAL 4: Posisi Harga vs Range (max 15 poin) ────────────────────
        # Harga dekat bottom range tapi mulai naik = early entry
        if high > low and price > 0:
            pos = (price - low) / (high - low) * 100
            if 15 <= pos <= 40:   score += 15  # Dekat bottom, mulai naik
            elif 40 < pos <= 60:  score += 8   # Di tengah range
            elif pos > 80:        score -= 5   # Dekat puncak, risky

        # ── SINYAL 5: Momentum awal (max 10 poin) ────────────────────────────
        # Koin yang baru mulai bergerak (0.5-5%) lebih menarik dari yang sudah jauh
        if 0.5 <= pct <= 5:    score += 10
        elif 5 < pct <= 10:    score += 5
        elif pct < 0:          score += 3   # Koin turun bisa reversal

        # ── BONUS: Whale signal dari WebSocket ───────────────────────────────
        try:
            from shared_state import state
            whale = state.rt_whale.get(sym, state.rt_whale.get(sym.replace('USDT', 'USDT'), ''))
            if whale == 'WHALE_BUY':  score += 15
            elif whale == 'WHALE_SELL': score -= 5
        except Exception:
            pass

        # ── BONUS: OBI dari WebSocket ─────────────────────────────────────────
        try:
            from shared_state import state
            obi = state.rt_obi.get(sym, 0)
            if obi > 0.15:   score += 10  # Buyer dominance
            elif obi < -0.15: score -= 5  # Seller dominance
        except Exception:
            pass

        return max(0.0, min(100.0, score))

    # Hitung score untuk semua koin
    df['pump_score'] = df.apply(pump_score, axis=1)

    # Sort by pump score
    df_sorted = df.sort_values(by='pump_score', ascending=False).head(30)

    # Log top 5
    top5 = df_sorted.head(5)
    print(f"[PUMP PREDICTOR] Top 5 pre-pump candidates:")
    for _, row in top5.iterrows():
        sym  = row.get('symbol', '')
        pct  = round(float(row.get('priceChangePercent', 0)), 2)
        vol  = round(float(row.get('quoteVolume', 0)) / 1_000_000, 1)
        sc   = round(float(row.get('pump_score', 0)), 1)
        print(f"  {sym}: {pct:+.1f}% | Vol ${vol}M | PumpScore {sc}/100")

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