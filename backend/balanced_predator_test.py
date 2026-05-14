import requests
import pandas as pd
import numpy as np

# --- BALANCED PREDATOR v31.0 VALIDATION ---
def get_hot_symbols():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    r = requests.get(url)
    df = pd.DataFrame(r.json())
    df['priceChangePercent'] = df['priceChangePercent'].astype(float)
    df['quoteVolume'] = df['quoteVolume'].astype(float)
    hot = df[(df['priceChangePercent'].abs() > 6) & (df['quoteVolume'] > 20_000_000)]
    return hot.sort_values(by='quoteVolume', ascending=False)['symbol'].tolist()[:10]

def fetch_klines(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1000"
    r = requests.get(url)
    df = pd.DataFrame(r.json(), columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df.dropna()

def prepare_logic(df):
    df['ema_9'] = df['c'].ewm(span=9).mean()
    df['ema_21'] = df['c'].ewm(span=21).mean()
    df['atr'] = (df['h'] - df['l']).rolling(14).mean()
    df['vol_24h'] = df['v'].rolling(96).sum()
    df['vol_1h'] = df['v'].rolling(4).sum()
    df['rvol'] = df['vol_1h'] / (df['vol_24h'] / 24)
    df['high24h'] = df['h'].rolling(96).max()
    df['low24h'] = df['l'].rolling(96).min()
    df['is_bullish'] = df['c'] > df['o']; df['is_bearish'] = df['c'] < df['o']
    return df

def run_simulation(df):
    balance = 10.0; margin = 3.5; lev = 10; fee = 0.0006
    trades = []; in_pos = None
    consecutive_losses = 0; locked_until = 0
    
    for i in range(100, len(df)):
        row = df.iloc[i]
        if i < locked_until: continue
        if row['atr'] > (row['c'] * 0.05): continue

        # AI LOGIC
        p_sc = 0.0; d_sc = 0.0
        h = row['high24h']; l = row['low24h']; pr = row['c']
        if h > l:
            pos = (pr - l) / (h - l) * 100
            if row['rvol'] >= 1.5:
                if pos >= 75: p_sc += 40
                elif pos <= 25: d_sc += 40
        if row['rvol'] >= 1.5: p_sc += 35; d_sc += 35
        
        side = "buy" if p_sc >= d_sc else "sell"
        
        # FAST MOMENTUM (v31.0)
        if side == "buy" and row['ema_9'] < row['ema_21']: continue
        if side == "sell" and row['ema_9'] > row['ema_21']: continue

        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if in_pos['side'] == 'sell': cpnl = -cpnl
            if cpnl > in_pos['peak']: in_pos['peak'] = cpnl
            if in_pos['peak'] >= 15:
                if in_pos['side'] == 'buy' and in_pos['sl'] < in_pos['ent']: in_pos['sl'] = in_pos['ent'] * 1.001
            
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
                balance += (pnl/100 * margin) - (margin * lev * fee * 2)
                trades.append(pnl); in_pos = None
                if pnl < 0:
                    consecutive_losses += 1
                    if consecutive_losses >= 2: locked_until = i + 96; consecutive_losses = 0
                else: consecutive_losses = 0
            continue

        score = int(p_sc) if side == "buy" else int(d_sc)
        if score >= 75 and row['rvol'] >= 1.5:
            in_pos = {'side':side,'ent':row['c'],'peak':0,'sl':row['c']-(row['atr']*1.5),'tp':row['c']+(row['atr']*5.0)}
            
    return balance, trades

def main():
    print("\n" + "="*85)
    print("BALANCED PREDATOR v31.0: THE PROFIT CHASE")
    print("="*85)
    hot_symbols = get_hot_symbols()
    total_b = 0; all_t = []
    for s in hot_symbols:
        try:
            df = prepare_logic(fetch_klines(s))
            b, t = run_simulation(df)
            total_b += b; all_t.extend(t)
            wr = (len([x for x in t if x > 0]) / len(t) * 100) if t else 0
            print(f"{s:<12} | SALDO AKHIR: ${b:>7.2f} | WR: {wr:>5.1f}% | Trades: {len(t)}")
        except Exception: pass
    
    avg_bal = total_b/len(hot_symbols)
    print("-" * 85)
    print(f"RATA-RATA SALDO AKHIR : ${avg_bal:.2f}")
    print(f"TOTAL TRADES          : {len(all_t)}x")
    print("="*85)

if __name__ == "__main__": main()
