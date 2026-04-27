import pandas as pd
import numpy as np

def detect_candle_patterns(open_0, high_0, low_0, close_0, open_1, high_1, low_1, close_1):
    """
    Detects basic candlestick patterns based on current (0) and previous (1) candle.
    """
    patterns = []
    
    # Calculate body and wicks
    body_0 = abs(close_0 - open_0)
    upper_wick_0 = high_0 - max(open_0, close_0)
    lower_wick_0 = min(open_0, close_0) - low_0
    is_bullish_0 = close_0 > open_0
    
    body_1 = abs(close_1 - open_1)
    is_bullish_1 = close_1 > open_1

    # 1. Bullish Engulfing
    if not is_bullish_1 and is_bullish_0 and close_0 > open_1 and open_0 < close_1:
        patterns.append("BULLISH ENGULFING")
        
    # 2. Bearish Engulfing
    if is_bullish_1 and not is_bullish_0 and close_0 < open_1 and open_0 > close_1:
        patterns.append("BEARISH ENGULFING")

    # 3. Hammer (Bullish Reversal)
    if body_0 > 0 and lower_wick_0 > (1.5 * body_0) and upper_wick_0 < (0.2 * body_0):
        patterns.append("HAMMER")

    # 4. Shooting Star (Bearish Reversal)
    if body_0 > 0 and upper_wick_0 > (1.5 * body_0) and lower_wick_0 < (0.2 * body_0):
        patterns.append("SHOOTING STAR")

    # 5. Doji (Indecision)
    if body_0 <= (0.1 * (high_0 - low_0)) if (high_0 - low_0) > 0 else True:
        patterns.append("DOJI")

    return patterns[0] if patterns else "NONE"

def detect_smart_money_concepts(df):
    """
    Detects Order Blocks and Fair Value Gaps (FVG) from a DataFrame.
    """
    if len(df) < 5: return {"ob": "NONE", "fvg": "NONE"}
    
    # Get last 5 candles
    last_3 = df.iloc[-3:]
    
    # 1. Fair Value Gap (FVG) Detection
    # Bullish FVG: Low(n) > High(n-2)
    # Bearish FVG: High(n) < Low(n-2)
    fvg = "NONE"
    # Current FVG (Gap between current low and 2 candles ago high)
    if df.iloc[-1]['low'] > df.iloc[-3]['high']:
        fvg = "BULLISH FVG"
    elif df.iloc[-1]['high'] < df.iloc[-3]['low']:
        fvg = "BEARISH FVG"

    # 2. Order Block (Simplified)
    # Bullish OB: Last bearish candle before a strong bullish move
    # Bearish OB: Last bullish candle before a strong bearish move
    ob = "NONE"
    
    # Check if last move was impulsive (body > 2x average of last 5)
    avg_body = abs(df['close'] - df['open']).tail(10).mean()
    last_body = abs(df.iloc[-1]['close'] - df.iloc[-1]['open'])
    
    if last_body > (1.5 * avg_body):
        if df.iloc[-1]['close'] > df.iloc[-1]['open']:
            ob = "BULLISH OB"
        else:
            ob = "BEARISH OB"
            
    return {"ob": ob, "fvg": fvg}
