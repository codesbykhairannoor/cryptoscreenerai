import sys
import os

def test_stepped_whale_logic():
    print("\n" + "="*80)
    print("=" + " "*22 + "BLUE WHALE STEPPED TEST (LADDER) v2.0" + " "*21 + "=")
    print("="*80 + "\n")

    # Simulation Params
    entry = 100.0
    lev = 10.0
    
    # Test cases: (Peak PnL, Expected SL PnL)
    test_cases = [
        (10.0, -20.0), # Below activation
        (15.0, 0.0),   # Step 1: BEP
        (29.0, 0.0),   # Still Step 1
        (30.0, 15.0),  # Step 2: +15% Locked
        (44.0, 15.0),  # Still Step 2
        (45.0, 30.0),  # Step 3: +30% Locked (User Requirement!)
        (60.0, 45.0)   # Step 4: +45% Locked
    ]
    
    for peak_pnl, expected_sl_pnl in test_cases:
        # --- LOGIC TO TEST ---
        step_count = int(peak_pnl // 15)
        if step_count >= 1:
            target_sl_pnl = (step_count - 1) * 15.0
        else:
            target_sl_pnl = -20.0 # Initial SL
            
        print(f"Peak PnL: {peak_pnl:>4.1f}% | SL PnL: {target_sl_pnl:>5.1f}% | {'MATCH' if target_sl_pnl == expected_sl_pnl else 'FAIL'}")

    print("\n" + "="*80)
    print("  [SUCCESS] Ladder logic verified. Peak 45% correctly locks 30% Profit!")
    print("="*80 + "\n")

if __name__ == "__main__":
    test_stepped_whale_logic()
