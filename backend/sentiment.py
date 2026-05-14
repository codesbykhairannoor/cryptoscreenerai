import requests
import xml.etree.ElementTree as ET
import os
import time
from dotenv import load_dotenv

load_dotenv()

# ============================================================================-
#  FRED MACRO ENGINE (Federal Reserve Economic Data - St. Louis Fed)
#  Cache TTL: 1 jam - data FRED update harian/mingguan, tidak perlu sering fetch
# ============================================================================-
_fred_cache: dict = {"ts": 0, "data": None}
FRED_CACHE_TTL = 3600  # 1 jam

# Series ID yang dipakai:
# FEDFUNDS  = Fed Funds Rate (suku bunga acuan Fed)
# CPIAUCSL  = CPI All Urban Consumers (inflasi)
# DTWEXBGS  = DXY (US Dollar Index, broad)
# DGS10     = 10-Year Treasury Yield
# UNRATE    = Unemployment Rate
# T10Y2Y    = 10Y-2Y Treasury Spread (yield curve - negatif = resesi signal)
FRED_SERIES = {
    "fed_rate":     "FEDFUNDS",
    "cpi":          "CPIAUCSL",
    "dxy":          "DTWEXBGS",
    "treasury_10y": "DGS10",
    "unemployment": "UNRATE",
    "yield_curve":  "T10Y2Y",
}


def _fetch_fred_series(series_id: str, api_key: str, limit: int = 2) -> list:
    """Ambil N data terbaru dari satu FRED series."""
    try:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}"
            f"&api_key={api_key}"
            f"&file_type=json"
            f"&sort_order=desc"
            f"&limit={limit}"
        )
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            obs = r.json().get("observations", [])
            # Filter out "." values (FRED pakai "." untuk data yang belum tersedia)
            valid = [o for o in obs if o.get("value", ".") != "."]
            return valid
    except Exception:
        pass
    return []


def get_fred_macro_context() -> dict:
    """
    Ambil konteks makro ekonomi dari FRED (Federal Reserve).

    Return dict berisi:
      fed_rate        : float  - Fed Funds Rate saat ini (%)
      fed_rate_prev   : float  - Fed Funds Rate periode sebelumnya
      fed_trend       : str    - "HIKING" / "CUTTING" / "HOLD"
      cpi             : float  - CPI terbaru (YoY %)
      cpi_trend       : str    - "HIGH" (>3%) / "MODERATE" (2-3%) / "LOW" (<2%)
      dxy             : float  - US Dollar Index
      dxy_trend       : str    - "STRONG" / "WEAK" / "NEUTRAL"
      treasury_10y    : float  - 10Y Treasury Yield (%)
      unemployment    : float  - Unemployment Rate (%)
      yield_curve     : float  - 10Y-2Y spread (negatif = inverted = resesi signal)
      macro_bias      : str    - "RISK_ON" / "RISK_OFF" / "NEUTRAL"
      crypto_impact   : str    - "BULLISH" / "BEARISH" / "NEUTRAL"
      gold_impact     : str    - "BULLISH" / "BEARISH" / "NEUTRAL"
      summary         : str    - Ringkasan 1 baris untuk log
    """
    global _fred_cache

    # Cek cache
    now = time.time()
    if _fred_cache["ts"] > 0 and (now - _fred_cache["ts"]) < FRED_CACHE_TTL:
        return _fred_cache["data"]

    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        return _build_fred_neutral("FRED_API_KEY tidak ditemukan di .env")

    result = {}

    # == 1. Fed Funds Rate ====================================================
    fed_obs = _fetch_fred_series(FRED_SERIES["fed_rate"], api_key, limit=2)
    fed_rate      = float(fed_obs[0]["value"]) if len(fed_obs) >= 1 else 0.0
    fed_rate_prev = float(fed_obs[1]["value"]) if len(fed_obs) >= 2 else fed_rate

    if fed_rate > fed_rate_prev + 0.01:
        fed_trend = "HIKING"    # Fed masih naikkan suku bunga = bearish crypto
    elif fed_rate < fed_rate_prev - 0.01:
        fed_trend = "CUTTING"   # Fed turunkan suku bunga = bullish crypto
    else:
        fed_trend = "HOLD"

    result["fed_rate"]      = round(fed_rate, 2)
    result["fed_rate_prev"] = round(fed_rate_prev, 2)
    result["fed_trend"]     = fed_trend

    # == 2. CPI (Inflasi) ====================================================-
    cpi_obs = _fetch_fred_series(FRED_SERIES["cpi"], api_key, limit=1)
    cpi = float(cpi_obs[0]["value"]) if cpi_obs else 0.0
    if cpi > 3.0:
        cpi_trend = "HIGH"       # Inflasi tinggi = Fed hawkish = bearish crypto
    elif cpi >= 2.0:
        cpi_trend = "MODERATE"   # Target Fed = neutral
    else:
        cpi_trend = "LOW"        # Deflasi risk = Fed dovish = bullish crypto

    result["cpi"]       = round(cpi, 2)
    result["cpi_trend"] = cpi_trend

    # == 3. DXY (US Dollar Index) ============================================-
    dxy_obs = _fetch_fred_series(FRED_SERIES["dxy"], api_key, limit=2)
    dxy      = float(dxy_obs[0]["value"]) if len(dxy_obs) >= 1 else 100.0
    dxy_prev = float(dxy_obs[1]["value"]) if len(dxy_obs) >= 2 else dxy

    dxy_change = ((dxy - dxy_prev) / dxy_prev * 100) if dxy_prev > 0 else 0
    if dxy_change > 0.3:
        dxy_trend = "STRONG"    # DXY naik = bearish crypto & gold
    elif dxy_change < -0.3:
        dxy_trend = "WEAK"      # DXY turun = bullish crypto & gold
    else:
        dxy_trend = "NEUTRAL"

    result["dxy"]       = round(dxy, 2)
    result["dxy_trend"] = dxy_trend

    # == 4. 10Y Treasury Yield ================================================
    t10y_obs = _fetch_fred_series(FRED_SERIES["treasury_10y"], api_key, limit=1)
    treasury_10y = float(t10y_obs[0]["value"]) if t10y_obs else 0.0
    result["treasury_10y"] = round(treasury_10y, 2)

    # == 5. Unemployment Rate ================================================-
    unemp_obs = _fetch_fred_series(FRED_SERIES["unemployment"], api_key, limit=1)
    unemployment = float(unemp_obs[0]["value"]) if unemp_obs else 0.0
    result["unemployment"] = round(unemployment, 2)

    # == 6. Yield Curve (10Y - 2Y) ============================================
    yc_obs = _fetch_fred_series(FRED_SERIES["yield_curve"], api_key, limit=1)
    yield_curve = float(yc_obs[0]["value"]) if yc_obs else 0.0
    result["yield_curve"] = round(yield_curve, 2)

    # == 7. Macro Bias (gabungan semua sinyal) ================================
    # Risk-ON  = Fed cutting + DXY lemah + inflasi moderat = bagus untuk crypto
    # Risk-OFF = Fed hiking + DXY kuat + inflasi tinggi = jelek untuk crypto
    risk_on_score  = 0
    risk_off_score = 0

    if fed_trend == "CUTTING":   risk_on_score  += 3
    elif fed_trend == "HIKING":  risk_off_score += 3
    # HOLD: neutral, tidak ada poin

    if dxy_trend == "WEAK":      risk_on_score  += 2
    elif dxy_trend == "STRONG":  risk_off_score += 2

    if cpi_trend == "LOW":       risk_on_score  += 1
    elif cpi_trend == "HIGH":    risk_off_score += 2

    if yield_curve < -0.2:       risk_off_score += 2  # Inverted yield curve = resesi
    elif yield_curve > 0.5:      risk_on_score  += 1  # Normal yield curve = sehat

    if treasury_10y > 5.0:       risk_off_score += 1  # Yield tinggi = obligasi lebih menarik dari crypto
    elif treasury_10y < 3.5:     risk_on_score  += 1

    if risk_on_score > risk_off_score + 1:
        macro_bias = "RISK_ON"
    elif risk_off_score > risk_on_score + 1:
        macro_bias = "RISK_OFF"
    else:
        macro_bias = "NEUTRAL"

    result["macro_bias"] = macro_bias

    # == 8. Asset-specific impact ============================================-
    # Crypto: Risk-ON = bullish, Risk-OFF = bearish
    result["crypto_impact"] = (
        "BULLISH" if macro_bias == "RISK_ON" else
        "BEARISH" if macro_bias == "RISK_OFF" else
        "NEUTRAL"
    )

    # Gold: Inverse DXY + safe haven saat resesi
    # Gold bullish kalau: DXY lemah ATAU yield curve inverted (resesi fear) ATAU inflasi tinggi
    gold_bull = (dxy_trend == "WEAK") or (yield_curve < -0.2) or (cpi_trend == "HIGH")
    gold_bear = (dxy_trend == "STRONG") and (cpi_trend != "HIGH")
    result["gold_impact"] = (
        "BULLISH" if gold_bull and not gold_bear else
        "BEARISH" if gold_bear else
        "NEUTRAL"
    )

    # == 9. Summary log ======================================================-
    result["summary"] = (
        f"[FRED] Fed:{fed_rate}%({fed_trend}) | "
        f"CPI:{cpi}({cpi_trend}) | "
        f"DXY:{dxy}({dxy_trend}) | "
        f"10Y:{treasury_10y}% | "
        f"YieldCurve:{yield_curve} | "
        f"Bias:{macro_bias} | "
        f"Crypto:{result['crypto_impact']} | Gold:{result['gold_impact']}"
    )

    print(result["summary"], flush=True)

    # Simpan ke cache
    _fred_cache = {"ts": now, "data": result}
    return result


def _build_fred_neutral(reason: str = "") -> dict:
    """Return neutral FRED context kalau API gagal."""
    return {
        "fed_rate": 0.0, "fed_rate_prev": 0.0, "fed_trend": "HOLD",
        "cpi": 0.0, "cpi_trend": "MODERATE",
        "dxy": 100.0, "dxy_trend": "NEUTRAL",
        "treasury_10y": 0.0, "unemployment": 0.0, "yield_curve": 0.0,
        "macro_bias": "NEUTRAL",
        "crypto_impact": "NEUTRAL",
        "gold_impact": "NEUTRAL",
        "summary": f"[FRED] Data tidak tersedia: {reason}",
    }

def get_global_market_data():
    """
    Fetches global market metrics from CoinMarketCap.
    Useful for detecting overall market health (e.g., BTC Dominance).
    """
    try:
        api_key = os.getenv("CMC_API_KEY")
        if not api_key: return "Global data: API Key missing"
        
        url = "https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest"
        headers = {
            'Accepts': 'application/json',
            'X-CMC_PRO_API_KEY': api_key,
        }
        res = requests.get(url, headers=headers, timeout=5)
        data = res.json()
        
        if data.get('status', {}).get('error_code') == 0:
            metrics = data['data']
            btc_dom = round(metrics['btc_dominance'], 2)
            eth_dom = round(metrics['eth_dominance'], 2)
            return f"Global: BTC Dom {btc_dom}%, ETH Dom {eth_dom}%"
        return "Global: Market data pending"
    except:
        return "Global: Analysis in progress"

def get_forex_news():
    """
    Fetches real-time Forex news headlines.
    Critical for Gold (XAUUSD) trading.
    """
    try:
        # Using a reliable financial news RSS feed
        url = "https://content.dailyfx.com/feeds/forex_market_news"
        res = requests.get(url, timeout=5)
        root = ET.fromstring(res.content)
        
        headlines = []
        for item in root.findall('.//item'):
            title = item.find('title').text
            headlines.append(title)
        
        if headlines:
            # Look for Gold or USD related news
            important = [h for h in headlines if any(x in h.upper() for x in ["GOLD", "XAU", "USD", "FED", "INFLATION", "NFP"])]
            if important:
                return f"[FOREX NEWS] {important[0]}"
            return f"[FOREX NEWS] {headlines[0]}"
        return "Forex: Market is stable with no major news spikes."
    except:
        return "Forex: News analysis in progress..."

def get_market_news_digest():
    """
    Summarizes the general market sentiment from CryptoPanic and Forex.
    """
    try:
        api_key = os.getenv("CRYPTOPANIC_API_KEY")
        c_headlines = []
        if api_key:
            # 1. CryptoPanic Top News
            c_url = f"https://cryptopanic.com/api/v1/posts/?auth_token={api_key}&filter=hot"
            c_res = requests.get(c_url, timeout=5)
            if c_res.status_code == 200:
                posts = c_res.json().get('results', [])[:3]
                c_headlines = [p.get('title', '') for p in posts]
        else:
            c_url = "https://www.coindesk.com/arc/outboundfeeds/rss/"
            c_res = requests.get(c_url, timeout=5)
            c_root = ET.fromstring(c_res.content)
            c_headlines = [item.find('title').text for item in c_root.findall('.//item')[:3]]
        
        # 2. Forex Headlines
        f_url = "https://content.dailyfx.com/feeds/forex_market_news"
        f_res = requests.get(f_url, timeout=5)
        f_root = ET.fromstring(f_res.content)
        f_headlines = [item.find('title').text for item in f_root.findall('.//item')[:3]]
        
        # 3. Analyze Sentiment
        all_news = " ".join(c_headlines + f_headlines).upper()
        sentiment = "NEUTRAL"
        if any(x in all_news for x in ["BULLISH", "SURGE", "GAINS", "RECOVERY", "ADOPTION", "EASE", "PUMP", "BREAKOUT"]):
            sentiment = "BULLISH"
        elif any(x in all_news for x in ["BEARISH", "CRASH", "DROP", "INFLATION", "HIKE", "CRACKDOWN", "DUMP", "HACK"]):
            sentiment = "BEARISH"
            
        return {
            "sentiment": sentiment,
            "crypto_top": c_headlines[0] if c_headlines else "Quiet",
            "forex_top": f_headlines[0] if f_headlines else "Stable"
        }
    except:
        return {"sentiment": "PENDING", "crypto_top": "Scanning...", "forex_top": "Scanning..."}

def get_crypto_news(symbol):
    """
    Fetches real news headlines from CryptoPanic specifically for the given symbol.
    """
    try:
        api_key = os.getenv("CRYPTOPANIC_API_KEY")
        clean_symbol = symbol.replace("USDT", "").upper()
        
        if api_key:
            # Query CryptoPanic API for the specific coin
            url = f"https://cryptopanic.com/api/v1/posts/?auth_token={api_key}&currencies={clean_symbol}&kind=news"
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                posts = res.json().get('results', [])
                if posts:
                    # Cek sentimen (Bullish/Bearish votes di CryptoPanic)
                    post = posts[0]
                    title = post.get('title', '')
                    votes = post.get('votes', {})
                    bullish_votes = votes.get('positive', 0) + votes.get('important', 0)
                    bearish_votes = votes.get('negative', 0) + votes.get('toxic', 0)
                    
                    sentiment_tag = ""
                    if bullish_votes > bearish_votes * 2: sentiment_tag = " [BULLISH SENTIMENT]"
                    elif bearish_votes > bullish_votes * 2: sentiment_tag = " [BEARISH SENTIMENT]"
                        
                    msg = f"[CRYPTOPANIC] {clean_symbol}: {title}{sentiment_tag}"
                    print(msg)
                    return msg
        else:
            # Fallback RSS
            url = "https://www.coindesk.com/arc/outboundfeeds/rss/"
            res = requests.get(url, timeout=5)
            root = ET.fromstring(res.content)
            headlines = [item.find('title').text for item in root.findall('.//item')]
            mentions = [h for h in headlines if clean_symbol in h.upper()]
            if mentions:
                msg = f"[NEWS] {clean_symbol}: {mentions[0]}"
                print(msg)
                return msg
            
        msg = f"[SENTIMENT] {clean_symbol} following BTC/ETH macro trends."
        return msg
    except Exception as e:
        return "Analyzing market pulse..."



