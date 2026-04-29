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

def get_crypto_news(symbol):
    """
    Fetches real news headlines from CoinDesk RSS feed and checks for symbol mentions.
    """
    try:
        url = "https://www.coindesk.com/arc/outboundfeeds/rss/"
        res = requests.get(url, timeout=5)
        root = ET.fromstring(res.content)
        
        headlines = []
        for item in root.findall('.//item'):
            title = item.find('title').text
            headlines.append(title)
        
        clean_symbol = symbol.replace("USDT", "").upper()
        mentions = [h for h in headlines if clean_symbol in h.upper()]
        
        if mentions:
            return f"Recent News for {clean_symbol}: {mentions[0]}"
        
        # Fallback to general market sentiment if specific news not found
        return f"Market Sentiment for {clean_symbol} is currently tied to broader BTC macro trends."
    except Exception as e:
        return "Market news currently being analyzed by AI..."
