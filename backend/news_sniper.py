"""
NEWS SNIPER v3.0   ULTRA-FAST FOREX NEWS EXECUTION
====================================================
Arsitektur untuk eksekusi sub-detik:

1. ForexExecutor di-pre-initialize SEKALI di startup (bukan per-news)
2. Koneksi MetaAPI sudah warm   tidak ada cold start saat news masuk
3. Multi-source parallel polling: 3 RSS + Finnhub WebSocket
4. Keyword detection spesifik untuk XAUUSD (gold sangat sensitif ke:
   - NFP, CPI, FOMC, Fed Rate Decision
   - Geopolitical: war, conflict, sanctions
   - Dollar strength: DXY, Treasury yields
5. Confidence scoring: semakin kuat news, semakin banyak lot yang dibuka
6. Cooldown 60 detik setelah eksekusi (hindari double entry)

LATENCY PIPELINE:
RSS polling: ~300ms deteksi + ~50ms eksekusi = ~350ms total
Finnhub WS: ~50ms deteksi + ~50ms eksekusi = ~100ms total
"""

import time
import requests
import xml.etree.ElementTree as ET
from threading import Thread, Lock
from datetime import datetime, timezone
import re


#     8. NEWS CALENDAR   UPCOMING HIGH-IMPACT EVENTS                           

def get_upcoming_high_impact_events() -> dict:
    """
    Cek apakah ada event high-impact yang akan terjadi dalam 2 jam ke depan.
    Pakai ForexFactory RSS sebagai sumber kalender ekonomi.

    Return:
      has_upcoming : True kalau ada event dalam 2 jam
      events       : list event yang akan datang
      caution_level: "HIGH" / "MEDIUM" / "NONE"
      recommendation: "AVOID_NEW_TRADES" / "REDUCE_SIZE" / "NORMAL"
    """
    result = {
        "has_upcoming": False,
        "events": [],
        "caution_level": "NONE",
        "recommendation": "NORMAL",
    }

    # Cache 15 menit agar tidak spam
    if not hasattr(get_upcoming_high_impact_events, '_cache'):
        get_upcoming_high_impact_events._cache = {"ts": 0, "result": result}

    now = time.time()
    if now - get_upcoming_high_impact_events._cache["ts"] < 900:
        return get_upcoming_high_impact_events._cache["result"]

    try:
        # ForexFactory calendar RSS
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        res = requests.get(url, timeout=8)
        if res.status_code != 200:
            return result

        events = res.json()
        now_utc = datetime.now(timezone.utc)
        upcoming = []

        HIGH_IMPACT_TITLES = [
            "Non-Farm", "NFP", "FOMC", "Fed Rate", "Interest Rate",
            "CPI", "Inflation", "GDP", "Unemployment", "Payroll",
            "Powell", "Lagarde", "ECB", "BOE", "BOJ",
        ]

        for event in events:
            try:
                impact = event.get("impact", "").lower()
                if impact not in ("high", "red"):
                    continue

                title = event.get("title", "")
                date_str = event.get("date", "")
                time_str = event.get("time", "")

                if not date_str or not time_str or time_str == "All Day":
                    continue

                # Parse event time
                event_dt_str = f"{date_str} {time_str}"
                try:
                    event_dt = datetime.strptime(event_dt_str, "%Y-%m-%d %I:%M%p")
                    event_dt = event_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                # Cek apakah dalam 2 jam ke depan
                diff_hours = (event_dt - now_utc).total_seconds() / 3600
                if -0.5 <= diff_hours <= 2.0:  # -30 menit sampai +2 jam
                    upcoming.append({
                        "title": title,
                        "time": time_str,
                        "hours_away": round(diff_hours, 1),
                    })
            except Exception:
                continue

        if upcoming:
            result["has_upcoming"] = True
            result["events"] = upcoming[:5]
            # Kalau dalam 30 menit = HIGH caution
            very_soon = [e for e in upcoming if e["hours_away"] <= 0.5]
            if very_soon:
                result["caution_level"]   = "HIGH"
                result["recommendation"]  = "AVOID_NEW_TRADES"
            else:
                result["caution_level"]   = "MEDIUM"
                result["recommendation"]  = "REDUCE_SIZE"

            print(f"[NEWS CALENDAR] {len(upcoming)} event high-impact dalam 2 jam:")
            for e in upcoming[:3]:
                print(f"  {e['title']} | {e['time']} | {e['hours_away']:+.1f}h")

        get_upcoming_high_impact_events._cache = {"ts": now, "result": result}
        return result

    except Exception:
        get_upcoming_high_impact_events._cache = {"ts": now, "result": result}
        return result

#     NEWS SOURCES                                                              
SOURCES = [
    "https://content.dailyfx.com/feeds/forex_market_news",
    "https://www.forexlive.com/feed/news",
    "https://www.investing.com/rss/news_1.rss",
    "https://feeds.reuters.com/reuters/businessNews",  # Reuters business
]

#     KEYWORD PATTERNS                                                          
# XAUUSD sangat sensitif ke events ini
CRITICAL_KEYWORDS = re.compile(
    r"NFP|NON.FARM|FOMC|CPI|FED|POWELL|LAGARDE|INTEREST RATE|UNEMPLOYMENT|"
    r"PAYROLL|INFLATION|RATE DECISION|RATE HIKE|RATE CUT|TREASURY|YIELD|"
    r"GEOPOLIT|WAR|CONFLICT|SANCTION|GOLD|XAUUSD|SAFE.HAVEN|RISK.OFF"
)

# Bullish XAUUSD = Dollar lemah / risk-off / rate cut
BULLISH_GOLD = re.compile(
    r"RATE CUT|DOVISH|WEAK|MISSES|DEFICIT|BELOW EXPECT|DISAPPOINTS|"
    r"RECESSION|SLOWDOWN|CONFLICT|WAR|SANCTION|RISK.OFF|SAFE.HAVEN|"
    r"GOLD RISES|GOLD SURGES|XAU GAINS|DOLLAR FALLS|DXY DROPS"
)

# Bearish XAUUSD = Dollar kuat / risk-on / rate hike
BEARISH_GOLD = re.compile(
    r"RATE HIKE|HAWKISH|STRONG|BEATS|SURPLUS|ABOVE EXPECT|EXCEEDS|"
    r"RECOVERY|GROWTH|RISK.ON|DOLLAR RISES|DXY SURGES|GOLD FALLS|"
    r"XAU DROPS|GOLD SLUMPS|YIELDS RISE"
)

#     CONFIDENCE SCORING                                                        
HIGH_IMPACT = re.compile(r"NFP|NON.FARM|FOMC|RATE DECISION|CPI|PAYROLL")
MED_IMPACT  = re.compile(r"FED|POWELL|LAGARDE|INFLATION|UNEMPLOYMENT|TREASURY")
GEO_IMPACT  = re.compile(r"WAR|CONFLICT|SANCTION|GEOPOLIT|NUCLEAR|ATTACK")


class NewsSniper:
    """
    [INSTITUTIONAL NEWS SNIPER V3]
    Pre-initialized executor untuk zero cold-start latency.
    """
    def __init__(self, callback):
        self.callback    = callback
        self.seen_ids    = set()
        self.is_running  = True
        self._lock       = Lock()
        self._last_exec  = 0
        self._cooldown   = 60  # detik antar eksekusi

        # PRE-INITIALIZE ForexExecutor SEKALI   ini kunci latency rendah
        # Saat news masuk, koneksi sudah warm, tidak ada cold start
        print("[NEWS SNIPER] Pre-initializing ForexExecutor...")
        from forex_executor import ForexExecutor
        self.fx = ForexExecutor()
        print("[NEWS SNIPER] ForexExecutor ready. Zero cold-start latency.")

    def _calc_confidence(self, title_upper):
        """
        Hitung confidence level 1-5 berdasarkan impact news.
        Confidence menentukan berapa lot yang dibuka.
        """
        if HIGH_IMPACT.search(title_upper):  return 5  # NFP, FOMC, CPI = max impact
        if GEO_IMPACT.search(title_upper):   return 4  # Geopolitical = high impact
        if MED_IMPACT.search(title_upper):   return 3  # Fed speech = medium
        return 2  # Other critical news

    def fetch_source(self, url):
        """Individual thread untuk setiap news source."""
        while self.is_running:
            try:
                res = requests.get(url, timeout=4)
                if res.status_code == 200:
                    root  = ET.fromstring(res.content)
                    items = root.findall('.//item')

                    if items:
                        latest = items[0]
                        title_el = latest.find('title')
                        link_el  = latest.find('link')
                        if title_el is None or link_el is None:
                            time.sleep(0.3)
                            continue

                        title = title_el.text or ""
                        link  = link_el.text  or ""

                        with self._lock:
                            if link not in self.seen_ids:
                                self.seen_ids.add(link)
                                # Catat waktu ingestion SEBELUM processing
                                ingestion_time = time.time()
                                self.process_news(title, ingestion_time)

                        # Jaga seen_ids tidak terlalu besar
                        if len(self.seen_ids) > 200:
                            oldest = list(self.seen_ids)[:50]
                            for o in oldest:
                                self.seen_ids.discard(o)

            except Exception:
                pass

            time.sleep(0.3)  # 300ms polling

    def process_news(self, title, ingestion_time):
        """
        Proses news dan eksekusi kalau memenuhi kriteria.
        Dipanggil dari thread   harus thread-safe.
        """
        title_upper = title.upper()

        # Filter: hanya news yang relevan untuk XAUUSD
        if not CRITICAL_KEYWORDS.search(title_upper):
            return

        print(f"\n  [CRITICAL NEWS] {title}")

        # Tentukan arah
        is_bullish = bool(BULLISH_GOLD.search(title_upper))
        is_bearish = bool(BEARISH_GOLD.search(title_upper))

        if not is_bullish and not is_bearish:
            print(f"    [NEWS ALERT] Sentiment unclear   monitoring only: {title[:60]}")
            return

        side       = 'buy' if is_bullish else 'sell'
        confidence = self._calc_confidence(title_upper)

        # Cooldown check
        now = time.time()
        if now - self._last_exec < self._cooldown:
            remaining = round(self._cooldown - (now - self._last_exec))
            print(f"[NEWS SNIPER] Cooldown aktif ({remaining}s). Skip.")
            return

        self._last_exec = now
        self.callback(side, title, ingestion_time, confidence)

    def process_finnhub_news(self, headline, score):
        """
        Dipanggil dari FinnhubWS saat ada news real-time.
        Score: -1 (bearish) sampai +1 (bullish).
        """
        if abs(score) < 0.2:
            return  # Sentiment terlalu lemah

        title_upper = headline.upper()
        if not CRITICAL_KEYWORDS.search(title_upper):
            return

        side       = 'buy' if score > 0 else 'sell'
        confidence = 4 if abs(score) >= 0.6 else 3
        ingestion_time = time.time()

        now = time.time()
        if now - self._last_exec < self._cooldown:
            return

        self._last_exec = now
        print(f"\n  [FINNHUB NEWS] {headline[:80]} | Score: {score}")
        self.callback(side, headline, ingestion_time, confidence)

    def start(self):
        print("[NEWS SNIPER V3] Multi-Source Parallel Engine ACTIVE")
        print(f"  Sources: {len(SOURCES)} RSS feeds + Finnhub WebSocket")
        print(f"  Cooldown: {self._cooldown}s antar eksekusi")
        for source in SOURCES:
            Thread(target=self.fetch_source, args=(source,), daemon=True).start()


#     GLOBAL SNIPER INSTANCE                                                    
# Singleton   dipakai oleh FinnhubWS dan main.py
_sniper_instance = None

def get_sniper_instance():
    global _sniper_instance
    if _sniper_instance is None:
        _sniper_instance = NewsSniper(news_execution_handler)
    return _sniper_instance


def news_execution_handler(side, title, ingestion_time, confidence=3):
    """
    ULTRA-FAST EXECUTION HANDLER
    =============================
    Cek arah posisi aktif sebelum fire.
    Kalau ada posisi aktif berlawanan arah, skip news execution.
    """
    execution_start = time.time()
    latency_ms      = (execution_start - ingestion_time) * 1000

    # Lot sizing berdasarkan confidence   max 3 trade
    lot_map    = {2: (1, 0.01), 3: (2, 0.01), 4: (3, 0.01), 5: (3, 0.01)}
    trades, lot = lot_map.get(confidence, (1, 0.01))

    sniper = get_sniper_instance()

    # CEK POSISI AKTIF
    try:
        positions = sniper.fx._get_positions()
        xau_positions = [p for p in positions if "XAU" in p.get("symbol", "").upper()]

        if xau_positions:
            active_types = set(p.get("type", "") for p in xau_positions)
            has_buy  = "POSITION_TYPE_BUY"  in active_types
            has_sell = "POSITION_TYPE_SELL" in active_types

            # Cek apakah news berlawanan arah dengan posisi aktif
            news_conflicts = (side == "buy" and has_sell and not has_buy) or \
                             (side == "sell" and has_buy and not has_sell)
            news_same_dir  = (side == "buy" and has_buy) or (side == "sell" and has_sell)

            if news_conflicts:
                # News berlawanan arah posisi aktif
                if confidence >= 4:
                    # Cek minimum holding time   jangan close posisi yang baru dibuka < 30 menit
                    import datetime
                    now_utc = datetime.datetime.now(datetime.timezone.utc)
                    too_young = []
                    for p in xau_positions:
                        open_time_str = p.get("time", p.get("openTime", ""))
                        if open_time_str:
                            try:
                                open_dt = datetime.datetime.fromisoformat(open_time_str.replace("Z", "+00:00"))
                                age_min = (now_utc - open_dt).total_seconds() / 60
                                if age_min < 30:
                                    too_young.append(p)
                            except Exception:
                                pass

                    if too_young:
                        print(f"[NEWS SKIP] {len(too_young)} posisi baru dibuka < 30 menit. "
                              f"Tidak override   hindari FOMO.")
                        return

                    # News kuat (geopolitical/NFP/FOMC)   close semua posisi, lalu masuk arah baru
                    print(f"[NEWS OVERRIDE] Confidence {confidence}/5. Closing all {len(xau_positions)} "
                          f"{'BUY' if has_buy else 'SELL'} positions, then entering {side.upper()}.")
                    closed = 0
                    for p in xau_positions:
                        pos_id = p.get("id")
                        try:
                            url = f"{sniper.fx.base_url}/users/current/accounts/{sniper.fx.account_id}/trade"
                            headers = {"auth-token": sniper.fx.api_token, "Content-Type": "application/json"}
                            res = requests.post(url, headers=headers,
                                json={"actionType": "POSITION_CLOSE_ID", "positionId": pos_id}, timeout=8)
                            if res.status_code == 200:
                                closed += 1
                        except Exception:
                            pass
                    print(f"[NEWS OVERRIDE] Closed {closed}/{len(xau_positions)} positions.")
                    time.sleep(0.5)  # Tunggu sebentar sebelum buka posisi baru
                    # Reset trades ke max 3
                    trades = min(trades, 3)
                else:
                    # News lemah (confidence 2-3)   skip, tidak worth it close semua
                    print(f"[NEWS SKIP] Confidence {confidence}/5 terlalu rendah untuk override "
                          f"{len(xau_positions)} posisi aktif. Skip.")
                    return

            elif news_same_dir:
                # News searah dengan posisi aktif
                # Cek slot tersedia
                slots = max(0, 3 - len(xau_positions))
                if slots <= 0:
                    print(f"[NEWS SKIP] Sudah {len(xau_positions)} posisi aktif (max 3). Skip.")
                    return
                trades = min(trades, slots)

                # Jangan tambah kalau ada yang rugi > $0.5
                losing = [p for p in xau_positions if float(p.get("profit", 0)) < -0.5]
                if losing:
                    print(f"[NEWS SKIP] {len(losing)} posisi rugi. Skip news.")
                    return
            else:
                # Tidak ada posisi aktif   cek slot
                slots = max(0, 3 - len(xau_positions))
                trades = min(trades, slots)
                if trades <= 0:
                    return

        if trades <= 0:
            return

    except Exception:
        pass  # Kalau gagal cek, tetap fire dengan jumlah original

    # Cek kondisi teknikal   kalau trend berlawanan, kurangi trades
    try:
        ind   = sniper.fx._calc_indicators()
        trend = ind.get("trend", "NEUTRAL") if ind else "NEUTRAL"
        rsi   = ind.get("rsi", 50) if ind else 50

        if side == "buy" and trend == "BEARISH" and rsi >= 35:
            trades = max(1, trades - 1)
            print(f"[NEWS FILTER] Trend BEARISH RSI:{rsi}. Reduced to {trades} trades.")
        elif side == "sell" and trend == "BULLISH" and rsi <= 65:
            trades = max(1, trades - 1)
            print(f"[NEWS FILTER] Trend BULLISH RSI:{rsi}. Reduced to {trades} trades.")
    except Exception:
        pass

    print(f"\n{'='*60}")
    print(f"  [NEWS EXECUTION] {side.upper()} XAUUSD")
    print(f"   News     : {title[:70]}")
    print(f"   Latency  : {round(latency_ms, 2)}ms")
    print(f"   Confidence: {confidence}/5   {trades} trades   {lot} lot")
    print(f"{'='*60}")

    sniper.fx.place_xauusd_scalp_batch(side, trades_count=trades, volume=lot)


if __name__ == "__main__":
    sniper = get_sniper_instance()
    sniper.start()
    while True:
        time.sleep(1)
