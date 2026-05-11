import time

def simulate_trailing_sl(entry_price, leverage, current_pnl_pct, side='long'):
    """
    LOGIKA PERSIS DARI bitget_executor.py v8.3
    """
    peak_pnl = current_pnl_pct # Anggap harga sedang di puncak
    
    new_sl = 0
    locked_pnl = 0

    if peak_pnl >= 10:
        # Formula v8.3: Gap 5% dari Peak
        locked_pnl = float(int(peak_pnl / 5) * 5 - 5)
        locked_pnl = max(0.0, locked_pnl)

        if side == 'long':
            new_sl = entry_price * (1 + (locked_pnl / 100.0) / leverage)
        else:
            new_sl = entry_price * (1 - (locked_pnl / 100.0) / leverage)
            
    return locked_pnl, new_sl

def run_test():
    ENTRY = 0.4000 # Contoh harga LDO
    LEV = 50.0     # Leverage 50x (High Leverage Test)
    
    print("="*60)
    print(f"TRAILING SL SIMULATION TEST (Entry: {ENTRY}, Lev: {LEV}x)")
    print("="*60)
    print(f"{'Peak PnL':<12} | {'Locked PnL':<12} | {'New SL Price':<15} | {'Status'}")
    print("-"*60)
    
    stages = [5, 10, 15, 20, 30, 40, 50, 60, 70]
    
    for pnl in stages:
        locked, sl_price = simulate_trailing_sl(ENTRY, LEV, pnl)
        
        status = "BELOW ENTRY" if sl_price < ENTRY and sl_price > 0 else "OK (ABOVE ENTRY)"
        if sl_price == 0: status = "WAITING (PnL < 10%)"
        
        print(f"{pnl:>7}%      | {locked:>8}%      | {sl_price:>12.6f}    | {status}")

if __name__ == "__main__":
    run_test()
