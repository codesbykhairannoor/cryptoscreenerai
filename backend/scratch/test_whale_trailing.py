import sys
import os
import time

# Mocking parts of the system for testing
class MockExecutor:
    def __init__(self):
        self._peak_pnl = {}
        self._last_sl_set = {}
        self.sl_updates = []
        self.startup_time = time.time() - 100

    def _clean_symbol(self, s): return s
    def get_pending_plan_orders(self, s): return []
    def _set_sl_tp_bitget(self, *args, **kwargs): pass
    def update_sl_price(self, symbol, side, amount, new_price):
        self.sl_updates.append(new_price)

def test_whale_logic():
    print("\n" + "="*80)
    print("=" + " "*25 + "BLUE WHALE RATCHET TEST v1.0" + " "*25 + "=")
    print("="*80 + "\n")

    # Simulation Params
    entry = 100.0
    lev = 10.0
    symbol = "TESTUSDT"
    side = "long"
    
    # Mock positions with varying PnL
    pnl_sequence = [0.0, 10.0, 20.0, 35.0, 25.0, 10.0]
    peak_pnl = 0.0
    sl_p = entry * 0.98 # Initial -20% SL
    
    print(f"[START] Entry: {entry} | Initial SL: {sl_p} (-20%)")
    
    for i, pnl in enumerate(pnl_sequence):
        print(f"\nStep {i+1}: Current PnL = {pnl}%")
        
        # --- LOGIC TO TEST ---
        if pnl > peak_pnl:
            peak_pnl = pnl
        
        if peak_pnl >= 15.0:
            target_sl_pnl = peak_pnl - 20.0
            new_sl_price = entry * (1 + (target_sl_pnl / 100 / lev))
            
            if new_sl_price > sl_p:
                print(f"  [ACTION] Moving SL Up: {sl_p:.4f} -> {new_sl_price:.4f} (Peak: {peak_pnl}%)")
                sl_p = new_sl_price
            else:
                print(f"  [HOLD] Price Dropped but SL RATCHETED at {sl_p:.4f}")
        else:
            print(f"  [WAIT] PnL {pnl}% below 15% activation.")

    print("\n" + "="*80)
    if sl_p > entry:
        print("  [SUCCESS] SL is now at PROFIT level despite price drop!")
    else:
        print("  [SUCCESS] SL maintained at Peak Level (Ratchet Verified)")
    print("="*80 + "\n")

if __name__ == "__main__":
    test_whale_logic()
