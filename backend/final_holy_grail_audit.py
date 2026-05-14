import requests
import pandas as pd
import numpy as np

# --- THE HOLY GRAIL v34.0: DNA + OPTIMIZED PARAMS ---

def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1000"
    try:
        r = requests.get(url, timeout=10).json()
        df = pd.DataFrame(r, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
        df['ema_9'] = df['c'].ewm(span=9).mean()
        df['ema_21'] = df['c'].ewm(span=21).mean()
        df['atr'] = (df['h'] - df['l']).rolling(14).mean()
        df['vwap'] = (df['c'] * df['v']).cumsum() / df['v'].cumsum()
        delta = df['c'].diff()
        df['rsi'] = 100 - (100 / (1 + (delta.where(delta > 0, 0).rolling(14).mean() / -delta.where(delta < 0, 0).rolling(14).mean())))
        return symbol, df.dropna()
    except: return symbol, None

def run_holy_grail(df):
    wallet = 10.0
    margin = 5.0
    lev = 10
    fee = 0.0006
    in_pos = None
    trades = []
    
    # Optimized Params from v33.0
    SL_PCT = 2.0 # 20% PnL
    TRAIL_STEP = 10 # 10% PnL
    
    for i in range(50, len(df)):
        row = df.iloc[i]
        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if cpnl > in_pos['peak']: in_pos['peak'] = cpnl
            
            if in_pos['peak'] >= TRAIL_STEP:
                locked = (int(in_pos['peak'] / TRAIL_STEP) * TRAIL_STEP) - 5
                new_sl = in_pos['ent'] * (1 + (max(0, locked)/100)/lev)
                if new_sl > in_pos['sl']: in_pos['sl'] = new_sl

            ep = 0
            if row['l'] <= in_pos['sl']: ep = in_pos['sl']
            elif row['h'] >= in_pos['tp']: ep = in_pos['tp']
            
            if ep > 0:
                f_pnl = ((ep - in_pos['ent'])/in_pos['ent']) * lev * 100
                net = (f_pnl/100 * margin) - (margin * lev * fee * 2)
                wallet += net
                trades.append(net)
                in_pos = None
            continue

        if in_pos is None and wallet >= margin:
            # WINNING DNA FILTER v34.0
            is_gold_cross = row['ema_9'] > row['ema_21']
            is_above_vwap = row['c'] > row['vwap']
            is_rsi_boom   = 50 <= row['rsi'] <= 65
            
            if is_gold_cross and is_above_vwap and is_rsi_boom:
                in_pos = {
                    'ent': row['c'], 'peak': 0, 'margin': margin,
                    'sl': row['c'] * (1 - SL_PCT/100),
                    'tp': row['c'] + (row['atr'] * 4.0)
                }
    
    win_rate = (len([t for t in trades if t > 0]) / len(trades) * 100) if trades else 0
    return wallet, win_rate, len(trades)

def main():
    print("\n" + "="*80)
    print("FINAL AUDIT: THE HOLY GRAIL STRATEGY v34.0")
    print("Combining Optimized Params + Winning DNA Filter")
    print("="*80)
    
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    symbols = [s['symbol'] for s in requests.get(url).json() if s['symbol'].endswith('USDT')][:20]
    
    total_bal = 0; total_wr = 0; total_trades = 0; count = 0
    for s in symbols:
        _, df = fetch_data(s)
        if df is not None:
            bal, wr, t_count = run_holy_grail(df)
            total_bal += bal; total_wr += wr; total_trades += t_count; count += 1
            print(f"{s:<10} | Bal: ${bal:>6.2f} | WR: {wr:>5.1f}% | Trades: {t_count}")

    print("-" * 80)
    print(f"RATA-RATA SALDO AKHIR : ${total_bal/count:.2f}")
    print(f"RATA-RATA WIN RATE    : {total_wr/count:.1f}%")
    print(f"TOTAL TRADE (10 HARI) : {total_trades}")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()



