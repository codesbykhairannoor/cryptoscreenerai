"""
PUMP PREDICTOR ENGINE v1.0
===========================
Deteksi koin yang AKAN pump sebelum pump terjadi.

Sinyal pump yang valid (berdasarkan market microstructure):
1. OI naik + harga naik = fresh longs masuk -> bullish
2. OI naik + harga turun = fresh shorts masuk -> bearish (short squeeze candidate)
3. Funding rate negatif + OI tinggi = short squeeze imminent
4. Volume spike 3x+ dari rata-rata = institutional accumulation
5. Bid/Ask imbalance > 0.2 = buyer dominance
6. Harga baru breakout dari range 4 jam terakhir = momentum entry
7. Whale buy > $100k dalam 5 menit = smart money masuk
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Gemini client
gemini_api_key = os.getenv("GEMINI_API_KEY")
gemini_client = None
if gemini_api_key:
    try:
        from google import genai
        gemini_client = genai.Client(api_key=gemini_api_key)
    except Exception:
        pass

# DeepSeek client
api_key = os.getenv("DEEPSEEK_API_KEY")
_deepseek_disabled = False  # Flag untuk disable setelah error insufficient balance

def _get_deepseek_client():
    """Lazy client - return None kalau disabled atau tidak ada key."""
    global _deepseek_disabled
    if _deepseek_disabled or not api_key:
        return None
    try:
        return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    except Exception:
        return None

client = _get_deepseek_client()


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

    # -- Normalisasi kolom --
    # Bitget V2 ticker fields: symbol, lastPr, high24h, low24h, change24h, baseVolume, quoteVolume
    col_map = {
        'priceChangePercent': ['change24h', 'priceChangePercent', 'chgPct', 'change'],
        'quoteVolume':        ['quoteVolume', 'quoteVol', 'usdtVolume'],
        'lastPrice':          ['lastPr', 'lastPrice', 'last', 'close'],
        'high24h':            ['high24h', 'highPrice'],
        'low24h':             ['low24h', 'lowPrice'],
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
    if len(df) == 0: return []

    for col in ['quoteVolume', 'priceChangePercent', 'lastPrice', 'high24h', 'low24h']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Fix: Bitget change24h adalah desimal (0.008 = 0.8%), bukan persen langsung
    # Kalau nilai max < 1.0, berarti masih dalam format desimal
    if df['priceChangePercent'].abs().max() < 2.0:
        df['priceChangePercent'] = df['priceChangePercent'] * 100

    # -- BLACKLIST --
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

    # -- SCORING --
    def pump_score(row):
        score = 0.0
        vol   = float(row.get('quoteVolume', 0))
        pct   = float(row.get('priceChangePercent', 0))
        price = float(row.get('lastPrice', 0))
        high  = float(row.get('high24h', price * 1.01))
        low   = float(row.get('low24h',  price * 0.99))
        rng   = float(row.get('range_pct', 0))

        # -- 1. VOLATILITAS RANGE (max 30 poin) --
        # Range besar = koin bisa bergerak 8% untuk hit TP
        if rng >= 20:    score += 30
        elif rng >= 15:  score += 25
        elif rng >= 10:  score += 20
        elif rng >= 7:   score += 15
        elif rng >= 5:   score += 10
        elif rng >= 3:   score += 5

        # -- 2. VOLUME ABSOLUT (max 25 poin) --
        # Volume besar = likuiditas, slippage kecil
        if vol >= 100_000_000:   score += 25   # $100M+
        elif vol >= 50_000_000:  score += 20   # $50M+
        elif vol >= 20_000_000:  score += 15   # $20M+
        elif vol >= 10_000_000:  score += 10   # $10M+
        elif vol >= 5_000_000:   score += 7    # $5M+
        elif vol >= 2_000_000:   score += 4    # $2M+

        # -- 3. POSISI HARGA DI RANGE (max 25 poin) --
        if high > low and price > 0:
            pos = (price - low) / (high - low) * 100
            
            # Jika Volume Rendah: Cari koin di bawah (Mean Reversion)
            # Jika Volume MELEDAK: Hajar koin di atas (Breakout Momentum)
            rvol_val = 1.0
            try:
                from shared_state import state
                rvol_val = state.rt_rvol.get(str(row.get('symbol', '')), 1.0)
            except Exception: pass

            if rvol_val >= 3.0: # MOMENTUM MODE!
                if pos >= 80:     score += 25   # BREAKOUT! Hajar terus!
                elif 50 <= pos < 80: score += 15
            else: # NORMAL MODE (Cari yang murah)
                if 10 <= pos <= 35:   score += 25   # Dekat bottom, ideal long
                elif 35 < pos <= 50:  score += 18   
                elif pos > 85:        score -= 10   # Terlalu tinggi untuk volume rendah

        # -- 4. MOMENTUM & VELOCITY (max 40 poin) --
        # Koin yang volumenya meledak (RVOL) adalah prioritas utama (The Gainer Hunter)
        try:
            from shared_state import state
            sym = str(row.get('symbol', ''))
            rvol = state.rt_rvol.get(sym, 1.0) # Relative Volume dari early_signal
            if rvol >= 5.0:    score += 40   # Volume meledak parah!
            elif rvol >= 3.0:  score += 30   # Volume sangat tinggi
            elif rvol >= 2.0:  score += 15   # Volume mulai masuk
        except Exception:
            pass

        if 1.5 <= pct <= 6:    score += 20   # Sweet spot
        elif 0.5 <= pct < 1.5: score += 12   # Mulai bergerak
        elif 6 < pct <= 12:    score += 8    # Sudah bergerak
        elif pct < 0:          score += 5    # Reversal candidate

        # -- BONUS: Whale + OBI dari WebSocket --
        try:
            from shared_state import state
            sym   = str(row.get('symbol', ''))
            whale = state.rt_whale.get(sym, '')
            obi   = state.rt_obi.get(sym, 0)
            if whale == 'WHALE_BUY':  score += 20
            elif whale == 'WHALE_SELL': score -= 5
            if obi > 0.15:            score += 10
            elif obi < -0.15:         score -= 5
            # OI Surge boost (dari early_signal engine)
            oi_surge = state.oi_surge_coins.get(sym, {})
            oi_pct = oi_surge.get("oi_change_pct", 0)
            if oi_pct >= 50:   score += 25   # OI naik >50% = akumulasi kuat
            elif oi_pct >= 30: score += 15   # OI naik >30%
            elif oi_pct >= 15: score += 8
        except Exception:
            pass

        return max(0.0, min(100.0, score))

    df['pump_score'] = df.apply(pump_score, axis=1)

    # -- DUMP SCORE - untuk SHORT candidates --
    def dump_score(row):
        """
        Score untuk SHORT setup.
        Koin yang ideal untuk short:
        - Harga di 65-90% dari range 24h (dekat puncak)
        - Sudah naik banyak (overbought)
        - Volume tinggi (likuiditas untuk short)
        - Range besar (bisa turun 8% untuk hit TP)
        """
        score = 0.0
        vol   = float(row.get('quoteVolume', 0))
        pct   = float(row.get('priceChangePercent', 0))
        price = float(row.get('lastPrice', 0))
        high  = float(row.get('high24h', price * 1.01))
        low   = float(row.get('low24h',  price * 0.99))
        rng   = float(row.get('range_pct', 0))

        # 1. VOLATILITAS RANGE (sama dengan pump)
        if rng >= 20:    score += 30
        elif rng >= 15:  score += 25
        elif rng >= 10:  score += 20
        elif rng >= 7:   score += 15
        elif rng >= 5:   score += 10
        elif rng >= 3:   score += 5

        # 2. VOLUME ABSOLUT (sama dengan pump)
        if vol >= 100_000_000:   score += 25
        elif vol >= 50_000_000:  score += 20
        elif vol >= 20_000_000:  score += 15
        elif vol >= 10_000_000:  score += 10
        elif vol >= 5_000_000:   score += 7
        elif vol >= 2_000_000:   score += 4

        # 3. POSISI HARGA DI RANGE - kebalikan dari pump
        # Harga di 65-90% dari range = dekat puncak, ideal short
        if high > low and price > 0:
            pos = (price - low) / (high - low) * 100
            if 65 <= pos <= 90:   score += 25   # Dekat puncak, ideal short
            elif 50 <= pos < 65:  score += 10   # Di atas tengah, masih ok
            elif 35 <= pos < 50:  score -= 5    # Di tengah, tidak ideal short
            elif pos < 35:        score -= 15   # Dekat bottom, JANGAN short

        # 4. MOMENTUM - koin yang sudah naik banyak = reversal candidate
        if 6 < pct <= 15:    score += 20   # Sudah naik banyak, ripe for reversal
        elif 3 < pct <= 6:   score += 15   # Naik signifikan
        elif 1.5 < pct <= 3: score += 8    # Naik sedikit
        elif pct < -5:       score -= 10   # Sudah turun banyak, jangan short lagi

        # 5. Whale SELL dari WebSocket
        try:
            from shared_state import state
            sym   = str(row.get('symbol', ''))
            whale = state.rt_whale.get(sym, '')
            obi   = state.rt_obi.get(sym, 0)
            if whale == 'WHALE_SELL': score += 20
            elif whale == 'WHALE_BUY': score -= 5
            if obi < -0.15:           score += 10
            elif obi > 0.15:          score -= 5
            # OI Surge penalty untuk short (OI naik + harga naik = longs masuk, jangan short)
            oi_surge = state.oi_surge_coins.get(sym, {})
            oi_pct = oi_surge.get("oi_change_pct", 0)
            if oi_pct >= 30: score -= 10  # OI surge = smart money long, jangan short
        except Exception:
            pass

        return max(0.0, min(100.0, score))

    df['dump_score'] = df.apply(dump_score, axis=1)

    # PREDATOR TANPA BATAS: Pantau semua koin yang masuk kriteria (head(80) untuk stability)
    df['best_score'] = df[['pump_score', 'dump_score']].max(axis=1)
    df_sorted = df.sort_values(by='best_score', ascending=False).head(80)

    # Log top 5
    print(f"[PUMP PREDICTOR] Top 5 candidates:")
    for _, row in df_sorted.head(5).iterrows():
        sym  = row.get('symbol', '')
        pct  = round(float(row.get('priceChangePercent', 0)), 2)
        rng  = round(float(row.get('range_pct', 0)), 1)
        vol  = round(float(row.get('quoteVolume', 0)) / 1_000_000, 1)
        ps   = round(float(row.get('pump_score', 0)), 1)
        ds   = round(float(row.get('dump_score', 0)), 1)
        bias = "LONG" if ps >= ds else "SHORT"
        pos_in_range = 0
        h = float(row.get('high24h', 0))
        l = float(row.get('low24h', 0))
        p = float(row.get('lastPrice', 0))
        if h > l: pos_in_range = round((p - l) / (h - l) * 100, 0)
        print(f"  {sym}: {pct:+.1f}% | Range {rng}% | Pos {pos_in_range:.0f}% | Vol ${vol}M | Pump:{ps} Dump:{ds} [{bias}]")

    return df_sorted.to_dict('records')


def smart_trade_decision(symbol, technicals, news):
    """Tidak dipakai lagi - diganti pump predictor scoring."""
    return True, "Pump predictor approved"


def analyze_market_data(data_json):
    """Untuk frontend dashboard - menggunakan Gemini (prioritas) atau DeepSeek."""
    global _deepseek_disabled, client, gemini_client
    
    prompt = f"""
    Analyze this crypto/market data and provide 3 hot trading recommendations.
    Focus on whale activity, RSI momentum, and MTF trend confirmation.
    Data: {data_json}
    Format your response in professional Indonesian, use emojis, and be highly creative.
    Include Entry, TP, and SL for each recommendation.
    """

    # 1. Try Gemini first
    if gemini_client:
        try:
            response = gemini_client.models.generate_content(
                model='gemini-1.5-flash',
                contents=prompt
            )
            return response.text
        except Exception as e:
            print(f"[GEMINI ERROR] {e}")

    # 2. Fallback to DeepSeek
    if client and not _deepseek_disabled:
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a brilliant, creative, and highly accurate institutional trading analyst assistant."},
                    {"role": "user", "content": prompt},
                ],
                stream=False
            )
            return response.choices[0].message.content
        except Exception as e:
            err_str = str(e).lower()
            if "insufficient" in err_str or "balance" in err_str or "quota" in err_str:
                _deepseek_disabled = True
                client = None
                print("[DEEPSEEK] Kredit habis. DeepSeek dinonaktifkan.", flush=True)
            return f"Gagal analisis: {e}"
            
    return "AI analysis tidak tersedia (kredit habis atau key tidak ada). Bot tetap berjalan normal."


