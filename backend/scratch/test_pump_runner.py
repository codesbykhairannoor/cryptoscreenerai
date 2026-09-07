"""
Test Multi-Stage Unleashed Pump Runner Trailing Stop Logic
"""

def simulate_trade(entry_price=10.0, price_path=[]):
    sl = entry_price * 0.965  # Initial SL -3.5% = 9.65
    tp = entry_price * 1.500  # Moonshot TP +50% = 15.0
    peak_pnl = 0.0
    closed = False
    exit_info = None

    print(f"--- Simulating Trade Entry @ {entry_price} | Initial SL: {sl:.4f} (-3.5%) | Moonshot TP: {tp:.4f} (+50%) ---")

    for step, mrk in enumerate(price_path):
        pnl = ((mrk - entry_price) / entry_price) * 100.0
        if pnl > peak_pnl:
            peak_pnl = pnl

        # TRAILING ENGINE FIRST
        # Stage 4: Super Parabolic Trailing (>= 25%)
        if peak_pnl >= 25.0:
            dynamic_sl = mrk * 0.955
            min_lock = entry_price * 1.200
            new_sl = max(dynamic_sl, min_lock)
            if new_sl > sl:
                sl = new_sl
                print(f"  [Step {step}] Price: {mrk:.4f} (+{pnl:.2f}%) | PEAK: {peak_pnl:.2f}% => STAGE 4 TRAILING SL: {sl:.4f} (+{((sl-entry_price)/entry_price)*100:.2f}%)")
        # Stage 3: Sky Runner Trailing (>= 12%)
        elif peak_pnl >= 12.0:
            dynamic_sl = mrk * 0.965
            min_lock = entry_price * 1.080
            new_sl = max(dynamic_sl, min_lock)
            if new_sl > sl:
                sl = new_sl
                print(f"  [Step {step}] Price: {mrk:.4f} (+{pnl:.2f}%) | PEAK: {peak_pnl:.2f}% => STAGE 3 TRAILING SL: {sl:.4f} (+{((sl-entry_price)/entry_price)*100:.2f}%)")
        # Stage 2: Profit Lock (>= 6%)
        elif peak_pnl >= 6.0:
            new_sl = entry_price * 1.030
            if new_sl > sl:
                sl = new_sl
                print(f"  [Step {step}] Price: {mrk:.4f} (+{pnl:.2f}%) | PEAK: {peak_pnl:.2f}% => STAGE 2 PROFIT LOCK SL: {sl:.4f} (+3.00%)")
        # Stage 1: Breakeven Lock (>= 2.5%)
        elif peak_pnl >= 2.5:
            new_sl = entry_price * 1.003
            if new_sl > sl:
                sl = new_sl
                print(f"  [Step {step}] Price: {mrk:.4f} (+{pnl:.2f}%) | PEAK: {peak_pnl:.2f}% => STAGE 1 BREAKEVEN LOCK SL: {sl:.4f} (+0.30% Risk-Free)")

        # CHECK EXITS
        if mrk <= sl:
            reason = f"Trailing Stop (+{pnl:.2f}%)" if pnl > 0 else "Hit SL"
            exit_info = {"step": step, "price": mrk, "pnl": pnl, "reason": reason}
            closed = True
            print(f"  >>> CLOSED: {reason} @ {mrk:.4f} (PnL: {pnl:.2f}%)\n")
            break

        if mrk >= tp:
            reason = f"Moonshot TP (+{pnl:.2f}%)"
            exit_info = {"step": step, "price": mrk, "pnl": pnl, "reason": reason}
            closed = True
            print(f"  >>> CLOSED: {reason} @ {mrk:.4f} (PnL: {pnl:.2f}%)\n")
            break

    return exit_info

if __name__ == "__main__":
    # Test 1: Immediate loser (cuts loss at -3.5%)
    print("TEST 1: Immediate Loser")
    simulate_trade(10.0, [9.9, 9.8, 9.64])

    # Test 2: Fakeout after small pump (+2.8% then dumps) -> Should exit at +0.3% Breakeven!
    print("TEST 2: Fakeout after +2.8% pump (Breakeven test)")
    simulate_trade(10.0, [10.1, 10.28, 10.2, 10.03, 10.02])

    # Test 3: Mega Runner (+35% pump then pulls back) -> Should exit around +28.9% with huge profit!
    print("TEST 3: Mega Runner (+35% pump)")
    simulate_trade(10.0, [10.2, 10.3, 10.65, 11.2, 11.8, 12.5, 13.5, 13.2, 12.8])
