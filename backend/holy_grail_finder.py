import requests
import pandas as pd
import numpy as np

def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1500"
    r = requests.get(url)
    df = pd.DataFrame(r.json(), columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df.dropna()

def prepare_data(df):
    df['ema_50'] = df['c'].ewm(span=50).mean()
    df['ema_200'] = df['c'].ewm(span=200).mean()
    df['atr'] = (df['h'] - df['l']).rolling(14).mean()
    
    delta = df['c'].diff()
    g = (delta.where(delta > 0, 0)).rolling(14).mean()
    l_loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (g/l_loss)))
    
    # Pinbar Detection (Long Wick)
    df['body_size'] = abs(df['c'] - df['o'])
    df['lower_wick'] = df[['o', 'c']].min(axis=1) - df['l']
    df['upper_wick'] = df['h'] - df[['o', 'c']].max(axis=1)
    
    df['bull_pinbar'] = (df['lower_wick'] > df['body_size'] * 2) & (df['upper_wick'] < df['body_size'])
    df['bear_pinbar'] = (df['upper_wick'] > df['body_size'] * 2) & (df['lower_wick'] < df['body_size'])
    
    # Engulfing
    df['bull_engulf'] = (df['c'] > df['o']) & (df['o'] < df['c'].shift(1)) & (df['c'] > df['o'].shift(1)) & (df['c'].shift(1) < df['o'].shift(1))
    df['bear_engulf'] = (df['c'] < df['o']) & (df['o'] > df['c'].shift(1)) & (df['c'] < df['o'].shift(1)) & (df['c'].shift(1) > df['o'].shift(1))
    
    return df

def simulate_holy_grail(df, sl_m, tp_m, margin=3.0):
    balance = 10.0
    lev = 10
    fee = 0.0006
    trades = []
    in_pos = None
    
    for i in range(200, len(df)):
        row = df.iloc[i]
        
        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if in_pos['side'] == 'sell': cpnl = -cpnl
            if cpnl > in_pos['peak']: in_pos['peak'] = cpnl
            
            # TSL KETAT 10/0 (Breakeven super cepat)
            if in_pos['peak'] >= 10:
                if in_pos['side'] == 'buy':
                    if in_pos['sl'] < in_pos['ent']: in_pos['sl'] = in_pos['ent'] * 1.001
                else:
                    if in_pos['sl'] > in_pos['ent']: in_pos['sl'] = in_pos['ent'] * 0.999

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
            continue

        # HOLY GRAIL LOGIC (PULLBACK + REJECTION)
        is_uptrend = row['ema_50'] > row['ema_200'] and row['c'] > row['ema_200']
        is_downtrend = row['ema_50'] < row['ema_200'] and row['c'] < row['ema_200']
        
        # Jarak ke EMA 50 (Pullback filter)
        dist_ema50 = abs(row['c'] - row['ema_50']) / row['ema_50'] * 100
        
        buy_signal = is_uptrend and dist_ema50 < 0.5 and (row['bull_pinbar'] or row['bull_engulf']) and row['rsi'] < 50
        sell_signal = is_downtrend and dist_ema50 < 0.5 and (row['bear_pinbar'] or row['bear_engulf']) and row['rsi'] > 50
        
        if buy_signal:
            in_pos = {'side':'buy','ent':row['c'],'peak':0,'sl':row['c']-(row['atr']*sl_m),'tp':row['c']+(row['atr']*tp_m)}
        elif sell_signal:
            in_pos = {'side':'sell','ent':row['c'],'peak':0,'sl':row['c']+(row['atr']*sl_m),'tp':row['c']-(row['atr']*tp_m)}
            
    return balance, trades

def main():
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    data = {s: prepare_data(fetch_data(s)) for s in syms}
    
    configs = [
        (1.0, 3.0), (1.5, 4.0), (2.0, 5.0), (1.5, 6.0), (2.0, 8.0)
    ]
    
    best_overall = 0
    best_conf = None
    best_results = {}
    
    for c in configs:
        bals = []; all_t = []
        for sym in syms:
            b, t = simulate_holy_grail(data[sym], c[0], c[1])
            bals.append(b); all_t.extend(t)
            
        avg_bal = sum(bals) / len(bals)
        if avg_bal > best_overall:
            best_overall = avg_bal
            best_conf = c
            best_results = {'bal': avg_bal, 'trades': len(all_t), 'wins': len([x for x in all_t if x > 0])}

    print("\n" + "="*80)
    print("PENCARIAN HOLY GRAIL SELESAI!")
    print("="*80)
    
    if best_overall > 10.0:
        wr = best_results['wins'] / best_results['trades'] * 100 if best_results['trades'] > 0 else 0
        print(f"[OK] DITEMUKAN STRATEGI PROFITABLE! (SALDO NAIK)")
        print(f"Target Kemenangan (WR) : {wr:.1f}%")
        print(f"Saldo Akhir Rata-rata  : ${best_overall:.2f} (Dari modal $10)")
        print(f"Total Trading (3 Koin) : {best_results['trades']}x")
        print(f"Settingan SL / TP      : {best_conf[0]} / {best_conf[1]} ATR")
        print(f"Logika Utama           : EMA 50/200 Pullback + Pinbar Rejection")
    else:
        print("[FAIL] Sial, market benar-benar hancur minggu ini. Saldo mentok di $", best_overall)
    print("="*80)

if __name__ == "__main__": main()



