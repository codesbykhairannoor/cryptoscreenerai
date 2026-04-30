import time
import requests
import feedparser
from threading import Thread
from datetime import datetime

# Institutional-grade News Source (DailyFX or Forexfactory)
NEWS_RSS_URL = "https://content.dailyfx.com/feeds/forex_market_news"

# High-priority triggers
VOLATILITY_KEYWORDS = ["NFP", "FOMC", "CPI", "NON-FARM", "INTEREST RATE", "POWELL", "FED", "UNEMPLOYMENT"]

class NewsSniper:
    """
    [MILLI-SECOND EXECUTION ENGINE]
    Monitors news feeds with sub-second precision to trigger entries.
    """
    def __init__(self, callback):
        self.callback = callback
        self.last_news_id = None
        self.is_running = True
        self.latency_stats = []

    def monitor_loop(self):
        print("🛰️ [NEWS SNIPER] Ingestion Engine ACTIVE (Precision: 500ms)")
        while self.is_running:
            try:
                start_fetch = time.time()
                feed = feedparser.parse(NEWS_RSS_URL)
                fetch_latency = (time.time() - start_fetch) * 1000
                
                if feed.entries:
                    latest = feed.entries[0]
                    news_id = latest.get('id') or latest.get('link')
                    
                    if news_id != self.last_news_id:
                        title = latest.title.upper()
                        # Record ingestion time
                        ingestion_time = time.time()
                        
                        # Detect critical events
                        is_critical = any(kw in title for kw in VOLATILITY_KEYWORDS)
                        
                        if is_critical:
                            print(f"🔥 [CRITICAL NEWS] {latest.title}")
                            print(f"⏱️ [LATENCY] Ingestion: {round(fetch_latency, 2)}ms | Time: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
                            
                            # Trigger sub-millisecond execution callback
                            self.callback(latest.title, ingestion_time)
                        
                        self.last_news_id = news_id
                
            except Exception as e:
                print(f"⚠️ [NEWS SNIPER ERROR] {e}")
            
            time.sleep(0.5) # Poll every 500ms for high-impact events

    def start(self):
        Thread(target=self.monitor_loop, daemon=True).start()

def news_execution_handler(news_title, ingestion_time):
    """
    This function reacts to news. In a production environment, 
    this would call place_forex_order immediately.
    """
    # Simulate execution
    execution_start = time.time()
    latency = (execution_start - ingestion_time) * 1000
    
    print(f"⚡ [EXECUTION] News-Triggered Trade Initialized!")
    print(f"📈 [DELTA] Trigger-to-Execution: {round(latency, 4)}ms")
    
    # Logic to decide BUY/SELL based on title content
    # (Simplified for now)
    side = 'buy' if any(x in news_title for x in ["BEATS", "GAINS", "HIKE", "STRONG"]) else 'sell'
    
    # Import here to avoid circular dependencies
    from forex_executor import ForexExecutor
    fx = ForexExecutor()
    # fx.place_xauusd_scalp_batch(side, trades_count=5, volume=0.01) # Uncomment for LIVE

if __name__ == "__main__":
    sniper = NewsSniper(news_execution_handler)
    sniper.monitor_loop()
