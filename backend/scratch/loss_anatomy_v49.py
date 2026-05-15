import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Ensure backend path is accessible
sys.path.append(os.getcwd())

# Import REAL logic
from crypto_engine import _determine_trade_side, _calc_tp_sl

def generate_volatile_data(symbol, days=7):
    np.random.seed(sum(ord(c) for c in symbol))
    periods = days * 1440
    base_price = 100.0
    data = []
    price = base_price
    for i in range(periods):
        # Add "Fakeouts": Price goes up then suddenly dumps
        if i % 150 == 0: 
            change = 0.015 # Fake pump
        elif i % 151 == 0:
            change = -0.04 # Sudden dump
        else:
            change = np.random.normal(0, 0.002)
        
        price *= (1 + change)
        data.append({'high': price*1.002, 'low': price*0.998, 'close': price})
    return pd.DataFrame(data)

def run_loss_anatomy():
    print("\n" + "="*80)
    print("=" + " "*28 + "LOSS ANATOMY & TRAILING AUDIT" + " "*23 + "=")
    print("="*80 + "\n")

    symbols = ["VOL_COIN_1", "VOL_COIN_2"]
    loss_reasons = {'FAKEOUT': 0, 'DIRECT_REVERSAL': 0, 'SQUEEZED': 0}
    trailing_results = {
        'NO_TRAILING': 0,
        'TRAIL_1%': 0,
        'TRAIL_1.5%': 0,
        'TRAIL_2%': 0
    }

    for symbol in symbols:
        df = generate_volatile_data(symbol, 7)
        for i in range(50, len(df)-200):
            row = df.iloc[i]
            # Mock Signal (Simplified)
            side = "buy" if i % 100 == 0 else None
            if not side: continue
            
            entry_p = row['close']
            tp_p = entry_p * 1.05
            sl_p = entry_p * 0.95
            
            # --- ANALYZE LOSS ANATOMY ---
            max_profit_before_loss = 0
            is_win = False
            
            # 1. No Trailing (Baseline)
            for j in range(i+1, i+200):
                f_row = df.iloc[j]
                pnl = (f_row['high']-entry_p)/entry_p
                max_profit_before_loss = max(max_profit_before_loss, pnl)
                
                if f_row['high'] >= tp_p: is_win = True; break
                if f_row['low'] <= sl_p: break
            
            if not is_win:
                if max_profit_before_loss >= 0.02: loss_reasons['FAKEOUT'] += 1
                elif max_profit_before_loss < 0.005: loss_reasons['DIRECT_REVERSAL'] += 1
                else: loss_reasons['SQUEEZED'] += 1
            else:
                trailing_results['NO_TRAILING'] += 1

            # --- SIMULATE TRAILING SL ---
            def sim_trail(step_pct):
                current_sl = entry_p * 0.95
                highest_seen = entry_p
                for j in range(i+1, i+200):
                    f_row = df.iloc[j]
                    if f_row['high'] > highest_seen:
                        highest_seen = f_row['high']
                        # Move SL up every 'step_pct' gain
                        new_sl = highest_seen * (1 - 0.05)
                        if new_sl > current_sl: current_sl = new_sl
                    
                    if f_row['high'] >= entry_p * 1.05: return True
                    if f_row['low'] <= current_sl: return False
                return False

            if sim_trail(0.01): trailing_results['TRAIL_1%'] += 1
            if sim_trail(0.015): trailing_results['TRAIL_1.5%'] += 1
            if sim_trail(0.02): trailing_results['TRAIL_2%'] += 1

    print("--- [WHY DID WE LOSS?] ---")
    total_losses = sum(loss_reasons.values())
    if total_losses > 0:
        print(f"  FAKEOUT (Profit > 2% then dumped) : {loss_reasons['FAKEOUT']} ({loss_reasons['FAKEOUT']/total_losses*100:.1f}%)")
        print(f"  DIRECT REVERSAL (Never went up)   : {loss_reasons['DIRECT_REVERSAL']} ({loss_reasons['DIRECT_REVERSAL']/total_losses*100:.1f}%)")
        print(f"  SQUEEZED (Choppy/Sideways)        : {loss_reasons['SQUEEZED']} ({loss_reasons['SQUEEZED']/total_losses*100:.1f}%)")
    
    print("\n--- [TRAILING SL PERFORMANCE] ---")
    print(f"  Wins with NO Trailing  : {trailing_results['NO_TRAILING']}")
    print(f"  Wins with 1.0% Trailing: {trailing_results['TRAIL_1%']}")
    print(f"  Wins with 1.5% Trailing: {trailing_results['TRAIL_1.5%']}")
    print(f"  Wins with 2.0% Trailing: {trailing_results['TRAIL_2%']}")

    print("\n" + "="*80)
    print("  [LESSON] Fakeouts are our biggest enemy. Trailing SL can save those trades.")
    print("  [LESSON] Direct Reversals mean the 'Signal' was wrong. We need better OBI/Sentiment.")
    print("="*80 + "\n")

if __name__ == "__main__":
    run_loss_anatomy()
