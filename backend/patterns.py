import pandas as pd

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
    # Body is small, lower wick is at least 2x body, little/no upper wick
    if body_0 > 0 and lower_wick_0 > (2 * body_0) and upper_wick_0 < (0.1 * body_0):
        patterns.append("HAMMER")

    # 4. Shooting Star (Bearish Reversal)
    # Body is small, upper wick is at least 2x body, little/no lower wick
    if body_0 > 0 and upper_wick_0 > (2 * body_0) and lower_wick_0 < (0.1 * body_0):
        patterns.append("SHOOTING STAR")

    # 5. Doji (Indecision)
    if body_0 <= (0.1 * (high_0 - low_0)) if (high_0 - low_0) > 0 else True:
        patterns.append("DOJI")

    return patterns[0] if patterns else "NONE"
