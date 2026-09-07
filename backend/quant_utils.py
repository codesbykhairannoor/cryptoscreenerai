import pandas as pd
import numpy as np

def fractional_differentiation(series: pd.Series, d: float, threshold: float = 1e-4) -> pd.Series:
    """
    Fractional Differentiation untuk mempertahankan memori jangka panjang
    namun membuat deret waktu menjadi stasioner.
    (Referensi: Marcos Lopez de Prado - Advances in Financial Machine Learning)
    """
    if d == 0:
        return series
    if d == 1:
        return series.diff().dropna()
        
    weights = [1.0]
    k = 1
    while True:
        weight = -weights[-1] * (d - k + 1) / k
        if abs(weight) < threshold:
            break
        weights.append(weight)
        k += 1

    weights = np.array(weights)[::-1]
    
    diff_series = []
    for i in range(len(weights) - 1, len(series)):
        window = series.iloc[i - len(weights) + 1: i + 1]
        diff_val = np.dot(weights, window)
        diff_series.append(diff_val)
        
    # Pad awal dengan NaN agar shape sama
    padding = [np.nan] * (len(series) - len(diff_series))
    return pd.Series(padding + diff_series, index=series.index)

def cusum_filter(close_prices: pd.Series, threshold: float) -> list:
    """
    Symmetric CUSUM Filter untuk Event-Based Sampling.
    Hanya mengambil sampel (menciptakan event) ketika akumulasi
    pergerakan harga melampaui batas volatilitas (threshold).
    Return: list index di mana event terjadi.
    """
    events = []
    s_pos, s_neg = 0.0, 0.0
    
    returns = close_prices.diff().dropna()
    
    for i in returns.index:
        s_pos = max(0, s_pos + returns.loc[i])
        s_neg = min(0, s_neg + returns.loc[i])
        
        if s_pos > threshold:
            s_pos = 0
            events.append(i)
        elif s_neg < -threshold:
            s_neg = 0
            events.append(i)
            
    return events
    
def detect_market_regime(df: pd.DataFrame, window=20) -> str:
    """
    Deteksi rezim pasar menggunakan volatilitas dan kekuatan tren (ADX proxy).
    Rezim: TRENDING_BULL, TRENDING_BEAR, SIDEWAYS, CHOPPY
    """
    if len(df) < window:
        return "UNKNOWN"
        
    returns = df['close'].pct_change().dropna()
    volatility = returns.rolling(window).std().iloc[-1]
    
    sma_short = df['close'].rolling(window // 2).mean().iloc[-1]
    sma_long = df['close'].rolling(window).mean().iloc[-1]
    
    trend_strength = abs(sma_short - sma_long) / sma_long
    
    # Threshold ini idealnya dinamis, namun untuk versi awal kita tetapkan statis
    if trend_strength > 0.015: 
        if sma_short > sma_long:
            return "TRENDING_BULL"
        else:
            return "TRENDING_BEAR"
    else:
        if volatility > 0.02: 
            return "CHOPPY"
        else:
            return "SIDEWAYS"
