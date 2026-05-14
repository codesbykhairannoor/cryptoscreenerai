
import time

# --- MOCK DATA DARI LOG BOS (USELESS) ---
coin = {
    'symbol': 'USELESSUSDT',
    'pump_score': 22
}
tech = {
    'rsi': 69,
    'rvol': 4.9,
    'atr': 0.153, # Ini akan disesuaikan dengan mark_price agar ATR% 1.53%
    'mark_price': 10.0,
    'ema_9': 10.5,
    'ema_21': 10.1,
}
market_sentiment = "PENDING"
tech_score = 100
combined_score = round((coin['pump_score'] * 0.5) + (tech_score * 0.5)) # Hasilnya 61

print(f"--- SIMULASI EKSEKUSI (KASUS USELESS) ---")
print(f"RSI: {tech['rsi']} | RVOL: {tech['rvol']} | Combined Score: {combined_score}")
print(f"Sentiment: {market_sentiment} | Tech Score: {tech_score}")

# --- LOGIKA BARU SAYA (COPIED FROM crypto_engine.py) ---
reject = None
side = "buy" # Dari logic _determine_trade_side

# 1. Cek Sentiment (Line 1399)
if side is None:
    reject = "NO_SIDE"
elif market_sentiment == "PENDING" and tech_score < 100: # LOGIKA BARU
    reject = "SENTIMENT_PENDING"
elif combined_score < 60: # Assume threshold momentum
    reject = "SCORE_LOW"

if reject:
    print(f"RESULT: REJECTED with reason: {reject}")
else:
    print(f"RESULT: PASSED Sentiment Check!")

    # 2. Cek Threshold Eksekusi (Line 1552)
    is_holy = (tech['rsi'] > 65 and tech['rvol'] > 2.0)
    threshold = 60 if is_holy else 75
    
    if combined_score >= threshold and tech['rvol'] >= 1.5:
        print(f"EXECUTION: FIRE!!! (Score {combined_score} >= Threshold {threshold})")
    else:
        print(f"EXECUTION: BLOCKED (Score {combined_score} < Threshold {threshold})")
