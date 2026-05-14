import requests
import pandas as pd
import numpy as np

# --- FINAL PREDATOR BACKTEST v27.7 (MEME MODE) ---
def fetch_data(symbol):
    # Ambil 3000 candle 5 menit (~10 hari)
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=5m&limit=1500" # Max is 1500 per call, we use 1500 for speed
    r = requests.get(url)
    df = pd.DataFrame(r.json(), columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df.dropna()

def prepare_predator_data(df):
    df['vol_24h'] = df['v'].rolling(288).sum()
    df['vol_1h'] = df['v'].rolling(12).sum()
    df['rvol'] = df['vol_1h'] / (df['vol_24h'] / 24)
    df['oi_change_pct'] = (df['c'].diff().rolling(12).sum() / df['c'].shift(12)).abs() * 50
    df['high24h'] = df['h'].rolling(288).max()
    df['low24h'] = df['l'].rolling(288).min()
    df['ema_200'] = df['c'].ewm(span=200).mean()
    df['atr'] = (df['h'] - df['l']).rolling(14).mean()
    delta = df['c'].diff(); g = (delta.where(delta > 0, 0)).rolling(14).mean(); l = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (g/l)))
    df['is_bullish'] = df['c'] > df['o']; df['is_bearish'] = df['c'] < df['o']
    return df

def run_predator_test(df):
    balance = 10.0; margin = 4.0; lev = 10; fee = 0.0006
    trades = []; in_pos = None
    
    for i in range(288, len(df)):
        row = df.iloc[i]
        p_sc = 0.0; d_sc = 0.0
        h = row['high24h']; l = row['low24h']; p = row['c']
        if h > l:
            pos = (p - l) / (h - l) * 100
            if row['rvol'] >= 1.5: # LEBIH SENSITIF
                if pos >= 75: p_sc += 40
                elif pos <= 25: d_sc += 40
            else:
                if pos < 40: p_sc += 40
                if pos > 60: d_sc += 40
        if row['rvol'] >= 1.5: p_sc += 30; d_sc += 30
        ai_bias = "LONG" if p_sc >= d_sc else "SHORT"

        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if in_pos['side'] == 'sell': cpnl = -cpnl
            if cpnl > in_pos['peak']: in_pos['peak'] = cpnl
            if in_pos['peak'] >= 10:
                if in_pos['side'] == 'buy' and in_pos['sl'] < in_pos['ent']: in_pos['sl'] = in_pos['ent'] * 1.001
                elif in_pos['side'] == 'sell' and in_pos['sl'] > in_pos['ent']: in_pos['sl'] = in_pos['ent'] * 0.999
            ep = 0
            if in_pos['side'] == 'buy':
                if row['l'] <= in_pos['sl']: ep = in_pos['sl']
                elif row['h'] >= in_pos['tp']: ep = in_pos['tp']
            else:
                if row['h'] >= in_pos['sl']: ep = in_pos['sl']
                elif row['l'] <= in_pos['tp']: ep = in_pos['tp']
            if ep > 0:
                pnl = ((ep - in_pos['ent'])/in_pos['ent']) * lev * 100
                if in_pos['side'] == 'sell': pnl = -pnl
                net = (pnl/100 * margin) - (margin * lev * fee * 2)
                balance += net; trades.append(net); in_pos = None
                if balance <= 0.2: break
            continue

        ls = 0; ss = 0
        if row['rvol'] >= 1.5:
            if ai_bias == "LONG": ls += 40
            else: ss += 40
        if row['oi_change_pct'] >= 10: # LEBIH SENSITIF
            if ai_bias == "LONG": ls += 30
            else: ss += 30
        if not row['is_bullish']: ls -= 50
        if not row['is_bearish']: ss -= 50
        if ai_bias == "SHORT": ls -= 200
        else: ss -= 200
        
        if ls >= 60:
            in_pos = {'side':'buy','ent':row['c'],'peak':0,'sl':row['c']-(row['atr']*1.5),'tp':row['c']+(row['atr']*8.0)}
        elif ss >= 60:
            in_pos = {'side':'sell','ent':row['c'],'peak':0,'sl':row['c']+(row['atr']*1.5),'tp':row['c']-(row['atr']*8.0)}
            
    return balance, trades

def main():
    syms = ["PEPEUSDT", "FLOKIUSDT", "SHIBUSDT", "WIFUSDT", "BONKUSDT"]
    print("\n" + "="*85)
    print("BACKTEST MEME HUNTER v27.7 (HIGH SENSITIVITY MOMENTUM)")
    print("="*85)
    total_b = 0; all_t = []
    for s in syms:
        try:
            df = prepare_predator_data(fetch_data(s))
            b, t = run_predator_test(df)
            total_b += b; all_t.extend(t)
            print(f"{s:<10} | SALDO AKHIR: ${b:>7.2f} | TRADES: {len(t)}")
        except Exception:
            print(f"{s:<10} | ERROR FETCHING DATA")
    
    avg_b = total_b/len(syms)
    print("-" * 85)
    print(f"RATA-RATA SALDO : ${avg_b:.2f} (DARI MODAL $10)")
    print(f"TOTAL TRADES    : {len(all_t)}x")
    print(f"WIN RATE GLOBAL : {len([x for x in all_t if x > 0])/len(all_t)*100 if all_t else 0:.1f}%")
    print("="*85)

if __name__ == "__main__": main()



