import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Ensure backend path is accessible
sys.path.append(os.getcwd())

def generate_wild_pump_data(symbol, days=15):
    np.random.seed(sum(ord(c) for c in symbol))
    periods = days * 1440
    price = 100.0
    data = []
    is_pumping = False
    pump_duration = 0
    
    for i in range(periods):
        # High Noise Market
        change = np.random.normal(0, 0.005) # 0.5% noise per minute
        
        # Super Pump Trigger
        if not is_pumping and np.random.random() < 0.0005:
            is_pumping = True
            pump_duration = np.random.randint(300, 1500)
        
        if is_pumping:
            # Pumping but with SCARY corrections (2-7% drops inside the pump)
            if i % 50 == 0: change = -0.05 # 5% Flash crash
            else: change = np.random.uniform(0.001, 0.004) # Fast climb
            
            pump_duration -= 1
            if pump_duration <= 0: is_pumping = False
            
        price *= (1 + change)
        high = price * (1 + abs(np.random.normal(0, 0.002)))
        low = price * (1 - abs(np.random.normal(0, 0.002)))
        data.append({'high': high, 'low': low, 'close': price})
    return pd.DataFrame(data)

def simulate_whale_trade(df, start_idx, side, strategy):
    entry_p = df.iloc[start_idx]['close']
    
    if strategy == 'ORCA': sl_val = 0.15; step = 0.10
    elif strategy == 'BLUE_WHALE': sl_val = 0.20; step = 0.15
    elif strategy == 'KRAKEN': sl_val = 0.30; step = 0.20
    else: sl_val = 0.05; step = 0.05 # Small baseline
    
    current_sl = entry_p * (1 - sl_val) if side == "buy" else entry_p * (1 + sl_val)
    highest_p = entry_p
    lowest_p = entry_p
    
    for j in range(start_idx + 1, len(df)):
        row = df.iloc[j]
        
        if side == "buy":
            if row['high'] > highest_p:
                highest_p = row['high']
                profit_pct = (highest_p - entry_p) / entry_p
                # Move SL up by 'step' every 'step' gain
                if profit_pct >= step:
                    # New SL = Highest - (Initial SL distance)
                    new_sl = highest_p * (1 - sl_val)
                    if new_sl > current_sl: current_sl = new_sl
            
            if row['low'] <= current_sl: return (current_sl - entry_p)/entry_p * 100
        else:
            if row['low'] < lowest_p:
                lowest_p = row['low']
                profit_pct = (entry_p - lowest_p) / entry_p
                if profit_pct >= step:
                    new_sl = lowest_p * (1 + sl_val)
                    if new_sl < current_sl: current_sl = new_sl
            
            if row['high'] >= current_sl: return (entry_p - current_sl)/entry_p * 100
            
    return -sl_val * 100

def run_whale_battle():
    print("\n" + "="*80)
    print("=" + " "*28 + "WHALE DISTANCE BATTLE v53" + " "*25 + "=")
    print("="*80 + "\n")

    strategies = ['ORCA', 'BLUE_WHALE', 'KRAKEN', 'SMALL_FISH']
    results = {s: {'pnl': 0, 'wins': 0, 'trades': 0, 'max_trade': 0} for s in strategies}
    symbols = [f"WHALE_{i}" for i in range(1, 31)]

    for symbol in symbols:
        df = generate_wild_pump_data(symbol, 15)
        for i in range(100, len(df)-2000, 100):
            if i % 500 == 0: # Trigger trade
                for s in strategies:
                    pnl = simulate_whale_trade(df, i, "buy", s)
                    results[s]['trades'] += 1
                    results[s]['pnl'] += pnl
                    if pnl > 0: results[s]['wins'] += 1
                    results[s]['max_trade'] = max(results[s]['max_trade'], pnl)
                i += 1800

    print("--- [HEAVYWEIGHT RANKING] ---")
    for s in strategies:
        data = results[s]
        wr = (data['wins']/data['trades']*100) if data['trades'] > 0 else 0
        avg_pnl = data['pnl'] / data['trades'] if data['trades'] > 0 else 0
        print(f"  {s:<12} | PnL: {data['pnl']:>10.2f}% | Max: {data['max_trade']:>6.2f}% | WR: {wr:>5.1f}% | Avg: {avg_pnl:>6.2f}%")

    print("\n" + "="*80)
    winner = sorted(results.items(), key=lambda x: x[1]['pnl'], reverse=True)[0][0]
    print(f"  [THE KING] {winner} wins with the best balance of survival and profit!")
    print("="*80 + "\n")

if __name__ == "__main__":
    run_whale_battle()
