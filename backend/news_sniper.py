import time
import requests
import xml.etree.ElementTree as ET
from threading import Thread
from datetime import datetime
import re

# Multiple High-Speed Sources
SOURCES = [
    "https://content.dailyfx.com/feeds/forex_market_news",
    "https://www.forexlive.com/feed/news",
    "https://www.investing.com/rss/news_1.rss"
]

# Institutional High-Impact Keywords
BULLISH_KEYWORDS = re.compile(r"HIKE|BEATS|SURPLUS|STRONG|HAWKISH|GAINS|RECOVERS|EXPANDS|PEAK")
BEARISH_KEYWORDS = re.compile(r"CUT|MISSES|DEFICIT|WEAK|DOVISH|DROPS|SLUMPS|CONTRACTS|BOTTOM")
CRITICAL_KEYWORDS = re.compile(r"NFP|FOMC|CPI|FED|POWELL|LAGARDE|INTEREST RATE|UNEMPLOYMENT|PAYROLL")

class NewsSniper:
    """
    [INSTITUTIONAL NEWS SNIPER V2]
    Sub-second ingestion with multi-source parallel processing.
    """
    def __init__(self, callback):
        self.callback = callback
        self.seen_ids = set()
        self.is_running = True
        # Pre-initialize executor for zero-lag execution
        from forex_executor import ForexExecutor
        self.fx = ForexExecutor()

    def fetch_source(self, url):
        """Individual thread for each news source"""
        while self.is_running:
            try:
                res = requests.get(url, timeout=5)
                if res.status_code == 200:
                    root = ET.fromstring(res.content)
                    items = root.findall('.//item')
                    
                    if items:
                        latest = items[0]
                        title = latest.find('title').text
                        link = latest.find('link').text
                        
                        if link not in self.seen_ids:
                            self.seen_ids.add(link)
                            ingestion_time = time.time()
                            self.process_news(title, ingestion_time)
                            
                # Keep seen_ids manageable
                if len(self.seen_ids) > 100: self.seen_ids.pop()
                
            except Exception as e:
                pass
            
            time.sleep(0.3) # 300ms polling for high sensitivity

    def process_news(self, title, ingestion_time):
        title_upper = title.upper()
        is_critical = CRITICAL_KEYWORDS.search(title_upper)
        
        if is_critical:
            print(f"[CRITICAL NEWS] {title}")
            
            # Sub-millisecond Sentiment Logic
            side = None
            if BULLISH_KEYWORDS.search(title_upper): side = 'buy'
            elif BEARISH_KEYWORDS.search(title_upper): side = 'sell'
            
            if side:
                # Trigger the high-priority callback
                self.callback(side, title, ingestion_time)
            else:
                # If unsure but critical, alert the user for manual sniper action
                print(f"⚠️ [NEWS ALERT] Critical event detected but sentiment neutral: {title}")

    def start(self):
        print("[NEWS SNIPER V2] Multi-Source Parallel Engine ACTIVE")
        for source in SOURCES:
            Thread(target=self.fetch_source, args=(source,), daemon=True).start()

def news_execution_handler(side, title, ingestion_time):
    """
    ULTRA-FAST EXECUTION HANDLER
    """
    execution_start = time.time()
    latency = (execution_start - ingestion_time) * 1000
    
    print(f"[NEWS EXECUTION] Side: {side.upper()} | Latency: {round(latency, 4)}ms")
    
    # IMPORT AND TRIGGER BARRAGE
    from forex_executor import ForexExecutor
    fx = ForexExecutor()
    
    # 10 positions for critical news (The 'Aggressive' request)
    fx.place_xauusd_scalp_batch(side, trades_count=10, volume=0.01)

if __name__ == "__main__":
    sniper = NewsSniper(news_execution_handler)
    sniper.start()
    while True: time.sleep(1)
