import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Ensure backend path is accessible
sys.path.append(os.getcwd())

# Import REAL logic from the engine
from crypto_engine import _determine_trade_side, _calc_tp_sl

# ============================================================================-
#  ULTIMATE TRAILING SL AUDIT v51.0
#  ENTRY: REAL ENGINE LOGIC (AGILE PREDATOR)
#  EXIT: 4 DIFFERENT TRAILING SCENARIOS
# ============================================================================-

def generate_realistic_data(symbol, days=15):
    np.random.seed(sum(ord(c) for c in symbol))
    periods = days * 1440
    price = 100.0 if "BTC" not in symbol else 65000.0
    data = []
    for i in range(periods):
        change = np.random.normal(0, 0.002)
        # Add some trending periods
        if 1000 < i < 3000: change += 0.0005 
        if 5000 < i < 7000: change -= 0.0005
        
        price *= (1 + change)
        high = price * (1 + abs(np.random.normal(0, 0.0015)))
        low = price * (1 - abs(np.random.normal(0, 0.0015)))
        data.append({'timestamp': i, 'high': high, 'low': low, 'close': price})
    return pd.DataFrame(data)

def simulate_real_logic_trade(df, start_idx, side, tech, strategy):
    entry_p = df.iloc[start_idx]['close']
    # Baseline TP/SL from code
    tp_p, sl_p = _calc_tp_sl(entry_p, side, tech)
    
    current_sl = sl_p
    highest_p = entry_p
    lowest_p = entry_p
    
    for j in range(start_idx + 1, min(start_idx + 1440, len(df))):
        row = df.iloc[j]
        
        # --- TRAILING SCENARIOS ---
        if side == "buy":
            if row['high'] > highest_p:
                highest_p = row['high']
                profit_pct = (highest_p - entry_p) / entry_p
                
                if strategy == 'STRICT' and profit_pct >= 0.01:
                    # Move SL to Lock 0.5% profit for every 1% gain
                    new_sl = entry_p * (1 + (profit_pct - 0.005))
                    if new_sl > current_sl: current_sl = new_sl
                elif strategy == 'PREDATOR' and profit_pct >= 0.035:
                    new_sl = entry_p * 1.015 # Lock 1.5%
                    if new_sl > current_sl: current_sl = new_sl
                elif strategy == 'BEP' and profit_pct >= 0.015:
                    new_sl = entry_p * 1.0 # Breakeven
                    if new_sl > current_sl: current_sl = new_sl
            
            if row['high'] >= tp_p: return 5.0 # Win
            if row['low'] <= current_sl: return ((current_sl - entry_p)/entry_p)*100 # SL Hit
        else:
            if row['low'] < lowest_p:
                lowest_p = row['low']
                profit_pct = (entry_p - lowest_p) / entry_p
                
                if strategy == 'STRICT' and profit_pct >= 0.01:
                    new_sl = entry_p * (1 - (profit_pct - 0.005))
                    if new_sl < current_sl: current_sl = new_sl
                elif strategy == 'PREDATOR' and profit_pct >= 0.035:
                    new_sl = entry_p * 0.985 # Lock 1.5%
                    if new_sl < current_sl: current_sl = new_sl
                elif strategy == 'BEP' and profit_pct >= 0.015:
                    new_sl = entry_p * 1.0 # Breakeven
                    if new_sl < current_sl: current_sl = new_sl
            
            if row['low'] <= tp_p: return 5.0 # Win
            if row['high'] >= current_sl: return ((entry_p - current_sl)/entry_p)*100 # SL Hit
            
    return -5.0 # Timeout

def run_ultimate_audit():
    print("\n" + "="*80)
    print("=" + " "*25 + "ULTIMATE TRAILING SL AUDIT" + " "*26 + "=")
    print("=" + " "*20 + "LOGIC: AGILE PREDATOR (v47.1)" + " "*22 + "=")
    print("="*80 + "\n")

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
    strategies = ['NONE', 'STRICT', 'PREDATOR', 'BEP']
    results = {s: {'pnl': 0, 'wins': 0, 'trades': 0} for s in strategies}

    for symbol in symbols:
        print(f"  [DATA] Scanning {symbol} for REAL signals...")
        df = generate_realistic_data(symbol, 15)
        
        for i in range(100, len(df)-1440, 10):
            row = df.iloc[i]
            # Mock indicators based on REAL logic
            mss_bull = row['close'] > df.iloc[i-20:i]['high'].max()
            mss_bear = row['close'] < df.iloc[i-20:i]['low'].min()
            ema_21 = df['close'].iloc[i-21:i].mean()
            
            tech = {
                'mss_bullish': mss_bull, 'mss_bearish': mss_bear,
                'fvg': 'BULLISH' if mss_bull else ('BEARISH' if mss_bear else 'NONE'),
                'in_demand': mss_bull, 'in_supply': mss_bear,
                'rvol': 1.2, 'atr': row['high'] - row['low'], 'obi': 0.2 if mss_bull else -0.2,
                'ema_21': ema_21
            }
            
            # REAL Engine Side Determination
            side, reason, score = _determine_trade_side(tech, 55 if mss_bull else 45, 0, "NEUTRAL", row['close'], 50, 50)
            
            if side:
                # Found a REAL entry. Now test all SL scenarios on THIS specific entry.
                for s in strategies:
                    pnl = simulate_real_logic_trade(df, i, side, tech, s)
                    results[s]['trades'] += 1
                    results[s]['pnl'] += pnl
                    if pnl > 0: results[s]['wins'] += 1
                
                # Fast forward to end of trade to avoid overlapping the same signal
                i += 100 

    print("\n" + "="*80)
    print("=" + " "*28 + "ULTIMATE RANKING" + " "*35 + "=")
    print("="*80)
    
    for s in strategies:
        data = results[s]
        wr = (data['wins']/data['trades']*100) if data['trades'] > 0 else 0
        print(f"  {s:<10} | PnL: {data['pnl']:>8.2f}% | WR: {wr:>5.1f}% | Trades: {data['trades']}")
    
    print("="*80 + "\n")

if __name__ == "__main__":
    run_ultimate_audit()
