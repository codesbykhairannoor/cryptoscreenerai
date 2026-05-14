import requests
import pandas as pd
import numpy as np

def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=5m&limit=1500"
    r = requests.get(url)
    df = pd.DataFrame(r.json(), columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df.dropna()

def prepare_data(df):
    df['ema_20'] = df['c'].ewm(span=20).mean()
    df['ema_50'] = df['c'].ewm(span=50).mean()
    df['atr'] = (df['h'] - df['l']).rolling(14).mean()
    
    # VWAP
    df['vwap'] = (df['c'] * df['v']).cumsum() / df['v'].cumsum()
    
    # MACD Fast
    ema_12 = df['c'].ewm(span=12).mean()
    ema_26 = df['c'].ewm(span=26).mean()
    df['macd'] = ema_12 - ema_26
    df['signal'] = df['macd'].ewm(span=9).mean()
    df['hist'] = df['macd'] - df['signal']
    
    # Breakout Detect
    df['recent_high'] = df['h'].rolling(10).max().shift(1)
    df['recent_low'] = df['l'].rolling(10).min().shift(1)
    
    return df

def simulate_moonshot(df, margin=5.0): # Margin Gede ($5 dari $10) buat kejar cuan
    balance = 10.0
    lev = 10
    fee = 0.0006
    trades = []
    in_pos = None
    
    for i in range(50, len(df)):
        row = df.iloc[i]
        
        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if in_pos['side'] == 'sell': cpnl = -cpnl
            if cpnl > in_pos['peak']: in_pos['peak'] = cpnl
            
            # TSL AGRESOR (Kunci Breakeven cepat)
            if in_pos['peak'] >= 15:
                if in_pos['side'] == 'buy':
                    if in_pos['sl'] < in_pos['ent']: in_pos['sl'] = in_pos['ent'] * 1.002
                else:
                    if in_pos['sl'] > in_pos['ent']: in_pos['sl'] = in_pos['ent'] * 0.998

            ep = 0
            if in_pos['side'] == 'buy':
                if row['l'] <= in_pos['sl']: ep = in_pos['sl']
                elif row['h'] >= in_pos['tp']: ep = in_pos['tp']
            else:
                if row['h'] >= in_pos['sl']: ep = in_pos['sl']
                elif row['l'] <= in_pos['tp']: ep = in_pos['tp']
            
            if ep > 0:
                final_pnl = ((ep - in_pos['ent'])/in_pos['ent']) * lev * 100
                if in_pos['side'] == 'sell': final_pnl = -final_pnl
                net = (final_pnl/100 * margin) - (margin * lev * fee * 2)
                balance += net; trades.append(net)
                in_pos = None
                if balance <= 0: break
            continue

        # MOONSHOT LOGIC: MACD Momentum + VWAP Breakout
        # Hajar saat MACD hijau membesar dan harga nembus VWAP ke atas
        macd_cross_up = row['hist'] > 0 and df['hist'].iloc[i-1] <= 0
        macd_cross_dn = row['hist'] < 0 and df['hist'].iloc[i-1] >= 0
        
        buy_signal = macd_cross_up and row['c'] > row['vwap'] and row['c'] > row['ema_20']
        sell_signal = macd_cross_dn and row['c'] < row['vwap'] and row['c'] < row['ema_20']
        
        # Risk Reward ketat
        sl_m = 1.0
        tp_m = 3.5
        
        if buy_signal:
            in_pos = {'side':'buy','ent':row['c'],'peak':0,'sl':row['c']-(row['atr']*sl_m),'tp':row['c']+(row['atr']*tp_m)}
        elif sell_signal:
            in_pos = {'side':'sell','ent':row['c'],'peak':0,'sl':row['c']+(row['atr']*sl_m),'tp':row['c']-(row['atr']*tp_m)}
            
    return balance, trades

def main():
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"]
    print("\n" + "="*80)
    print("MENGHITUNG MOONSHOT STRATEGY (5 Menit, Margin $5)")
    print("="*80)
    
    total_bal = 0
    all_t = []
    for sym in syms:
        df = prepare_data(fetch_data(sym))
        b, t = simulate_moonshot(df)
        total_bal += b
        all_t.extend(t)
        wr = len([x for x in t if x > 0])/len(t)*100 if t else 0
        print(f"[{sym:<8}] Saldo Akhir: ${b:>6.2f} | WR: {wr:>5.1f}% | Trades: {len(t)}")
        
    avg_bal = total_bal / len(syms)
    total_wr = len([x for x in all_t if x > 0])/len(all_t)*100 if all_t else 0
    
    print("-" * 80)
    print(f"SALDO RATA-RATA  : ${avg_bal:.2f} (Dari Modal $10)")
    print(f"TOTAL TRADES     : {len(all_t)}x")
    print(f"WIN RATE GLOBAL  : {total_wr:.1f}%")
    print("="*80)

if __name__ == "__main__": main()



