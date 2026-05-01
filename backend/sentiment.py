import requests
import xml.etree.ElementTree as ET
import os
from dotenv import load_dotenv

load_dotenv()

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
    Summarizes the general market sentiment from all sources.
    This is what the bot 'thinks' about the current future trend.
    """
    try:
        # 1. Crypto Headlines
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
        if any(x in all_news for x in ["BULLISH", "SURGE", "GAINS", "RECOVERY", "ADOPTION", "EASE"]):
            sentiment = "BULLISH"
        elif any(x in all_news for x in ["BEARISH", "CRASH", "DROP", "INFLATION", "HIKE", "CRACKDOWN"]):
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
    Fetches real news headlines and checks for symbol mentions.
    """
    try:
        url = "https://www.coindesk.com/arc/outboundfeeds/rss/"
        res = requests.get(url, timeout=5)
        root = ET.fromstring(res.content)
        
        headlines = [item.find('title').text for item in root.findall('.//item')]
        clean_symbol = symbol.replace("USDT", "").upper()
        mentions = [h for h in headlines if clean_symbol in h.upper()]
        
        if mentions:
            msg = f"[NEWS] {clean_symbol}: {mentions[0]}"
            print(msg)
            return msg
            
        msg = f"[SENTIMENT] {clean_symbol} following BTC/ETH macro trends."
        return msg
    except:
        return "Analyzing market pulse..."
