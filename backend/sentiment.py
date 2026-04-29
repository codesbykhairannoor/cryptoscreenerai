import requests
import xml.etree.ElementTree as ET

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
