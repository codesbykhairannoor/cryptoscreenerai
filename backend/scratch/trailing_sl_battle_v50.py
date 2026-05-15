import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Ensure backend path is accessible
sys.path.append(os.getcwd())

def generate_market_data(symbol, days=7):
    np.random.seed(sum(ord(c) for c in symbol))
    periods = days * 1440
    price = 100.0
    data = []
    for i in range(periods):
        # High noise, sudden reversals
        change = np.random.normal(0, 0.003)
        if i % 100 == 0: change = -0.015 # Sudden 1.5% drop/spike
        
        price *= (1 + change)
        high = price * (1 + abs(np.random.normal(0, 0.002)))
        low = price * (1 - abs(np.random.normal(0, 0.002)))
        data.append({'high': high, 'low': low, 'close': price})
    return pd.DataFrame(data)

def simulate_trade(df, start_idx, side, strategy):
    entry_p = df.iloc[start_idx]['close']
    tp_p = entry_p * 1.05
    sl_p = entry_p * 0.95
    
    current_sl = sl_p
    highest_p = entry_p
    lowest_p = entry_p
    
    for j in range(start_idx + 1, min(start_idx + 1440, len(df))):
        row = df.iloc[j]
        
        # --- TRAILING LOGIC ---
        if side == "buy":
            if row['high'] > highest_p:
                highest_p = row['high']
                profit_pct = (highest_p - entry_p) / entry_p
                
                if strategy == 'STRICT' and profit_pct >= 0.01:
                    new_sl = entry_p * (1 + (profit_pct - 0.005))
                    if new_sl > current_sl: current_sl = new_sl
                elif strategy == 'PREDATOR' and profit_pct >= 0.03:
                    new_sl = entry_p * 1.015 # Lock at 1.5% profit
                    if new_sl > current_sl: current_sl = new_sl
                elif strategy == 'DYNAMIC' and profit_pct >= 0.02:
                    new_sl = highest_p * 0.975 # Follow with 2.5% distance
                    if new_sl > current_sl: current_sl = new_sl
                elif strategy == 'BEP' and profit_pct >= 0.015:
                    new_sl = entry_p * 1.0 # Move to Breakeven
                    if new_sl > current_sl: current_sl = new_sl
            
            if row['high'] >= tp_p: return 5.0 # TP Hit
            if row['low'] <= current_sl: return ((current_sl - entry_p)/entry_p) * 100
        else:
            if row['low'] < lowest_p:
                lowest_p = row['low']
                profit_pct = (entry_p - lowest_p) / entry_p
                
                if strategy == 'STRICT' and profit_pct >= 0.01:
                    new_sl = entry_p * (1 - (profit_pct - 0.005))
                    if new_sl < current_sl: current_sl = new_sl
                elif strategy == 'PREDATOR' and profit_pct >= 0.03:
                    new_sl = entry_p * 0.985 # Lock at 1.5% profit
                    if new_sl < current_sl: current_sl = new_sl
                elif strategy == 'DYNAMIC' and profit_pct >= 0.02:
                    new_sl = lowest_p * 1.025 # Follow with 2.5% distance
                    if new_sl < current_sl: current_sl = new_sl
                elif strategy == 'BEP' and profit_pct >= 0.015:
                    new_sl = entry_p * 1.0 # Move to Breakeven
                    if new_sl < current_sl: current_sl = new_sl
            
            if row['low'] <= tp_p: return 5.0 # TP Hit
            if row['high'] >= current_sl: return ((entry_p - current_sl)/entry_p) * 100
            
    return -5.0 # Time out or default loss

def run_trailing_battle():
    print("\n" + "="*80)
    print("=" + " "*28 + "BATTLE OF TRAILING SL v50" + " "*27 + "=")
    print("="*80 + "\n")

    strategies = ['NONE', 'STRICT', 'PREDATOR', 'DYNAMIC', 'BEP']
    results = {s: {'pnl': 0, 'wins': 0, 'trades': 0} for s in strategies}
    symbols = [f"COIN_{i}" for i in range(1, 11)] # 10 coins is enough

    for symbol in symbols:
        df = generate_market_data(symbol, 7)
        # Random 50 entries per coin
        for _ in range(50):
            i = np.random.randint(100, len(df)-1440)
            side = "buy" if np.random.random() > 0.5 else "sell"
            
            for s in strategies:
                pnl = simulate_trade(df, i, side, s)
                results[s]['trades'] += 1
                results[s]['pnl'] += pnl
                if pnl > 0: results[s]['wins'] += 1

    print("--- [FINAL RANKING] ---")
    sorted_res = sorted(results.items(), key=lambda x: x[1]['pnl'], reverse=True)
    for s, data in sorted_res:
        wr = (data['wins']/data['trades']*100) if data['trades'] > 0 else 0
        print(f"  {s:<10} | PnL: {data['pnl']:>8.2f}% | WR: {wr:>5.1f}% | Trades: {data['trades']}")

    winner = sorted_res[0][0]
    print("\n" + "="*80)
    print(f"  [WINNER] Strategy: {winner}")
    print(f"  [ADVICE] Pake skenario {winner} buat dapet profit paling maksimal!")
    print("="*80 + "\n")

if __name__ == "__main__":
    run_trailing_battle()
