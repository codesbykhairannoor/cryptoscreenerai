import requests
import pandas as pd
import numpy as np

# --- TRUE GOD MODE BACKTEST v28.1 ---
def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1500"
    r = requests.get(url)
    df = pd.DataFrame(r.json(), columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df.dropna()

def prepare_data(df):
    df['vol_24h'] = df['v'].rolling(96).sum()
    df['vol_1h'] = df['v'].rolling(4).sum()
    df['rvol'] = df['vol_1h'] / (df['vol_24h'] / 24)
    df['high24h'] = df['h'].rolling(96).max()
    df['low24h'] = df['l'].rolling(96).min()
    df['atr'] = (df['h'] - df['l']).rolling(14).mean()
    df['ema_200'] = df['c'].ewm(span=200).mean()
    df['is_bullish'] = df['c'] > df['o']; df['is_bearish'] = df['c'] < df['o']
    return df

def run_backtest(df):
    balance = 10.0; margin = 3.5; lev = 10; fee = 0.0006
    trades = []; in_pos = None
    
    for i in range(100, len(df)):
        row = df.iloc[i]
        
        # Logika AI Predator v27.5
        p_sc = 0.0; d_sc = 0.0
        h = row['high24h']; l = row['low24h']; pr = row['c']
        if h > l:
            pos = (pr - l) / (h - l) * 100
            if row['rvol'] >= 1.5:
                if pos >= 80: p_sc += 40
            else:
                if pos < 40: p_sc += 40
        if row['rvol'] >= 1.5: p_sc += 30
        
        # Konversi ke Combined Score
        combined_score = int(p_sc)
        
        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if in_pos['peak'] < cpnl: in_pos['peak'] = cpnl
            # TSL 15/0
            if in_pos['peak'] >= 15:
                if in_pos['sl'] < in_pos['ent']: in_pos['sl'] = in_pos['ent'] * 1.001
            # Exit
            if row['l'] <= in_pos['sl'] or row['h'] >= in_pos['tp']:
                ep = in_pos['sl'] if row['l'] <= in_pos['sl'] else in_pos['tp']
                pnl = ((ep - in_pos['ent'])/in_pos['ent']) * lev * 100
                net = (pnl/100 * margin) - (margin * lev * fee * 2)
                balance += net; trades.append(net); in_pos = None
            continue

        # ENTRY JIKA SKOR TINGGI (High Conviction v28.1)
        if combined_score >= 70:
            sl_m = 1.5; tp_m = 5.0
            in_pos = {'side':'buy','ent':row['c'],'peak':0,'sl':row['c']-(row['atr']*sl_m),'tp':row['c']+(row['atr']*tp_m)}
            
    return balance, trades

def main():
    # Gunakan koin yang volatilitasnya tinggi agar terlihat efeknya
    syms = ["SOLUSDT", "PEPEUSDT", "DOGEUSDT", "WIFUSDT"]
    print("\n" + "="*85)
    print("DEMONSTRASI TRUE GOD MODE v28.1 (SINKRONISASI TOTAL)")
    print("Modal: $10 | Target: Melipatgandakan Saldo via Gainer Hunter")
    print("="*85)
    total_b = 0; all_t = []
    for s in syms:
        df = prepare_data(fetch_data(s))
        b, t = run_backtest(df)
        total_b += b; all_t.extend(t)
        print(f"{s:<10} | SALDO AKHIR: ${b:>7.2f} | Trades: {len(t)}")
    print("-" * 85)
    print(f"RATA-RATA SALDO AKHIR: ${total_b/len(syms):.2f}")
    print("="*85)

if __name__ == "__main__": main()
