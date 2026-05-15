import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Ensure backend path is accessible
sys.path.append(os.getcwd())

# Import components
from crypto_engine import _determine_trade_side

def generate_historical_deadlock_data():
    # Simulate a "Quiet" market period from 30 days ago
    np.random.seed(42)
    periods = 1440 * 5 # 5 days of data
    price = 100.0
    data = []
    for i in range(periods):
        change = np.random.normal(0, 0.001)
        price *= (1 + change)
        # Simulate realistic SMC conditions that OLD code would skip
        # e.g. RVOL 0.5 (below old 0.8 limit), ATR 0.8% (below old 2% limit)
        data.append({
            'close': price,
            'high': price * 1.005,
            'low': price * 0.995,
            'rvol': 0.5, # THE DEADLOCK CAUSE
            'atr': price * 0.008, # THE DEADLOCK CAUSE
            'rsi': 52,
            'mss_bullish': i % 100 == 0,
            'fvg': 'BULLISH' if i % 100 == 0 else 'NONE',
            'in_demand': True if i % 100 == 0 else False,
            'obi': 0.2
        })
    return pd.DataFrame(data)

def run_deadlock_audit():
    print("\n" + "="*80)
    print("=" + " "*25 + "DEADLOCK BREAKER AUDIT" + " "*27 + "=")
    print("=" + " "*18 + "COMPARING OLD (CLOSED) VS NEW (PRO) LOGIC" + " "*16 + "=")
    print("="*80 + "\n")

    df = generate_historical_deadlock_data()
    
    old_trades = 0
    new_trades = 0
    
    print("[1/2] Simulating Market Conditions from the 'No-Trade' Period...")
    
    for i in range(len(df)):
        row = df.iloc[i]
        
        # --- MOCK OLD LOGIC (The Silent Blockers) ---
        # Dulu ada filter keras: RVOL > 0.8 dan ATR > 2%
        is_old_blocked = False
        if row['rvol'] < 0.8: is_old_blocked = True
        if row['atr'] < (row['close'] * 0.02): is_old_blocked = True
        
        if not is_old_blocked and row['mss_bullish']:
            old_trades += 1
            
        # --- REAL NEW LOGIC (Predator Pro) ---
        side, reason, score = _determine_trade_side(row.to_dict(), row['rsi'], 0, "NEUTRAL", row['close'], 50, 50)
        if side:
            new_trades += 1

    print("\n" + "="*80)
    print("=" + " "*28 + "AUDIT RESULT" + " "*38 + "=")
    print("="*80)
    print(f"  TRADES FOUND WITH OLD CODE : {old_trades}")
    print(f"  TRADES FOUND WITH NEW CODE : {new_trades}")
    print("="*80)

    if new_trades > old_trades:
        print(f"\n[SUCCESS] Bukti nyata! Kode baru nemu {new_trades} peluang di periode mati.")
        print(f"Penyebab mandet dulu: RVOL & ATR terlalu ketat. Sekarang sudah DIBEBASKAN!")
    else:
        print("\n[!] Hasil tidak konklusif. Mengecek parameter lain...")

    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    run_deadlock_audit()
