"""
Test Underground Alpha Hunter Trailing Stop Logic
"""

def simulate_trade(entry_price=10.0, price_path=[]):
    sl = entry_price * 0.980  # Tight initial SL -2.0% (Risk capped at $3 on $150)
    tp = entry_price * 1.500  # Moonshot TP +50%
    peak_pnl = 0.0
    closed = False
    exit_info = None

    print(f"--- Simulating Trade Entry @ {entry_price} | Initial SL: {sl:.4f} (-2.0%) | Moonshot TP: {tp:.4f} (+50%) ---")

    for step, mrk in enumerate(price_path):
        pnl = ((mrk - entry_price) / entry_price) * 100.0
        if pnl > peak_pnl:
            peak_pnl = pnl

        # TRAILING ENGINE FIRST
        # Stage 4: Super Parabolic Runner (>= 25%)
        if peak_pnl >= 25.0:
            dynamic_sl = mrk * 0.955
            min_lock = entry_price * 1.180
            new_sl = max(dynamic_sl, min_lock)
            if new_sl > sl:
                sl = new_sl
                print(f"  [Step {step}] Price: {mrk:.4f} (+{pnl:.2f}%) | PEAK: {peak_pnl:.2f}% => STAGE 4 SL: {sl:.4f} (+{((sl-entry_price)/entry_price)*100:.2f}%)")
        # Stage 3: Sky Runner Trailing (>= 12%)
        elif peak_pnl >= 12.0:
            dynamic_sl = mrk * 0.965
            min_lock = entry_price * 1.080
            new_sl = max(dynamic_sl, min_lock)
            if new_sl > sl:
                sl = new_sl
                print(f"  [Step {step}] Price: {mrk:.4f} (+{pnl:.2f}%) | PEAK: {peak_pnl:.2f}% => STAGE 3 SL: {sl:.4f} (+{((sl-entry_price)/entry_price)*100:.2f}%)")
        # Stage 2: Strong Profit Lock (>= 7%)
        elif peak_pnl >= 7.0:
            new_sl = entry_price * 1.040 # Lock in +4.0% guaranteed!
            if new_sl > sl:
                sl = new_sl
                print(f"  [Step {step}] Price: {mrk:.4f} (+{pnl:.2f}%) | PEAK: {peak_pnl:.2f}% => STAGE 2 PROFIT LOCK: {sl:.4f} (+4.00% Guaranteed)")
        # Stage 1: Chandelier Breathing Buffer (>= 4.0%)
        elif peak_pnl >= 4.0:
            new_sl = entry_price * 1.012 # Lock in +1.2% with 2.8% breathing buffer!
            if new_sl > sl:
                sl = new_sl
                print(f"  [Step {step}] Price: {mrk:.4f} (+{pnl:.2f}%) | PEAK: {peak_pnl:.2f}% => STAGE 1 CHANDELIER BUFFER: {sl:.4f} (+1.20% with Room to Breathe)")

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

    if not closed:
        print(f"  Posisi masih berjalan di harga {price_path[-1]:.4f} (PnL: {pnl:.2f}%)\n")
    return exit_info

if __name__ == "__main__":
    # Test 1: Immediate loser - cuts loss at -2.0% (NOT -4.5%!)
    print("TEST 1: Immediate Loser (Capped Loss)")
    simulate_trade(10.0, [9.9, 9.85, 9.79])

    # Test 2: Normal 2.5% pump with 1.5% wick pullback - SURVIVES and does NOT exit at +0.28%!
    print("TEST 2: The +2.5% Wick Pullback Test (Survival Test)")
    simulate_trade(10.0, [10.1, 10.25, 10.10, 10.20, 10.45, 10.50])

    # Test 3: +8.5% Pump - Locks in +4.0% profit ($6 on $150 margin)!
    print("TEST 3: +8.5% Pump (Stage 2 Lock)")
    simulate_trade(10.0, [10.2, 10.45, 10.85, 10.60, 10.39])
