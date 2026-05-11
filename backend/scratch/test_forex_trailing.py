def simulate_forex_trailing(open_price, current_price, is_buy=True):
    # Hitung profit dalam poin (XAUUSD biasanya 3 desimal, 1 poin = 0.1 di harga)
    # Di kode bot: profit_pt = abs(current_price - open_price) * 10
    # Tapi di XAUUSD: 1 poin emas = $1 per troy ounce? 
    # Mari gunakan logika poin bot: profit_pt = abs(current_price - open_price)
    
    profit_pt = abs(current_price - open_price)
    target_sl = 0
    stage = "NONE"
    
    if is_buy:
        if profit_pt >= 30.0:
            target_sl = round(open_price + 20.0, 3)
            stage     = "LOCK-20"
        elif profit_pt >= 20.0:
            target_sl = round(open_price + 10.0, 3)
            stage     = "LOCK-10"
        elif profit_pt >= 15.0:
            target_sl = round(open_price + 7.0, 3)
            stage     = "LOCK-7"
        elif profit_pt >= 10.0:
            target_sl = round(open_price + 3.0, 3)
            stage     = "LOCK-3"
    else:
        if profit_pt >= 30.0:
            target_sl = round(open_price - 20.0, 3)
            stage     = "LOCK-20"
        elif profit_pt >= 20.0:
            target_sl = round(open_price - 10.0, 3)
            stage     = "LOCK-10"
        elif profit_pt >= 15.0:
            target_sl = round(open_price - 7.0, 3)
            stage     = "LOCK-7"
        elif profit_pt >= 10.0:
            target_sl = round(open_price - 3.0, 3)
            stage     = "LOCK-3"
            
    return stage, target_sl

def run_forex_test():
    ENTRY = 2350.000 # Contoh entry XAUUSD
    print("="*60)
    print(f"FOREX TRAILING TEST (Entry: {ENTRY})")
    print("="*60)
    print(f"{'Current Price':<15} | {'Profit Pt':<10} | {'Stage':<10} | {'SL Price':<12}")
    print("-"*60)
    
    # Skenario BUY: Harga Naik
    scenarios = [2355, 2360, 2365, 2370, 2380]
    for cp in scenarios:
        pt = cp - ENTRY
        stage, sl = simulate_forex_trailing(ENTRY, cp, is_buy=True)
        print(f"{cp:<15.3f} | {pt:>8.1f}pt | {stage:<10} | {sl:<12.3f}")

if __name__ == "__main__":
    run_forex_test()
