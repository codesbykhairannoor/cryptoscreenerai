import requests
import pandas as pd
import numpy as np

# --- GLOBAL WIN PATTERN SCANNER v28.5 ---
def get_all_active_symbols():
    """Mencari semua koin yang sedang 'Hot' di bursa sekarang"""
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    r = requests.get(url)
    df = pd.DataFrame(r.json())
    df['priceChangePercent'] = df['priceChangePercent'].astype(float)
    df['quoteVolume'] = df['quoteVolume'].astype(float)
    # Filter: Koin yang bergerak > 10% atau Volume > 100M
    hot_coins = df[(df['priceChangePercent'].abs() > 10) & (df['quoteVolume'] > 50_000_000)]
    return hot_coins['symbol'].tolist()[:15] # Ambil 15 koin paling Hot

def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1000"
    r = requests.get(url)
    df = pd.DataFrame(r.json(), columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df.dropna()

def apply_predator_logic(df):
    df['vol_24h'] = df['v'].rolling(96).sum()
    df['vol_1h'] = df['v'].rolling(4).sum()
    df['rvol'] = df['vol_1h'] / (df['vol_24h'] / 24)
    df['high24h'] = df['h'].rolling(96).max()
    df['low24h'] = df['l'].rolling(96).min()
    df['atr'] = (df['h'] - df['l']).rolling(14).mean()
    df['ema_200'] = df['c'].ewm(span=200).mean()
    df['rsi'] = 100 - (100 / (1 + (df['c'].diff().where(df['c'].diff() > 0, 0).rolling(14).mean() / -df['c'].diff().where(df['c'].diff() < 0, 0).rolling(14).mean())))
    df['is_bullish'] = df['c'] > df['o']; df['is_bearish'] = df['c'] < df['o']
    return df

def run_backtest(df):
    balance = 10.0; margin = 3.5; lev = 10; fee = 0.0006
    trades = []; in_pos = None
    
    for i in range(100, len(df)):
        row = df.iloc[i]
        
        # AI PREDATOR v28.1
        p_sc = 0.0; d_sc = 0.0
        h = row['high24h']; l = row['low24h']; pr = row['c']
        if h > l:
            pos = (pr - l) / (h - l) * 100
            if row['rvol'] >= 1.8:
                if pos >= 75: p_sc += 40
                elif pos <= 25: d_sc += 40
        if row['rvol'] >= 1.8: p_sc += 35; d_sc += 35
        
        ai_bias = "LONG" if p_sc >= d_sc else "SHORT"
        
        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if in_pos['side'] == 'sell': cpnl = -cpnl
            if cpnl > in_pos['peak']: in_pos['peak'] = cpnl
            # TSL 15/0
            if in_pos['peak'] >= 15:
                if in_pos['side'] == 'buy' and in_pos['sl'] < in_pos['ent']: in_pos['sl'] = in_pos['ent'] * 1.001
                elif in_pos['side'] == 'sell' and in_pos['sl'] > in_pos['ent']: in_pos['sl'] = in_pos['ent'] * 0.999
            # Exit
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
            continue

        ls = 0; ss = 0
        if row['rvol'] >= 1.8:
            if ai_bias == "LONG": ls += 40
            else: ss += 40
        if not row['is_bullish']: ls -= 50
        if not row['is_bearish']: ss -= 50
        if ai_bias == "SHORT": ls -= 200
        else: ss -= 200
        
        if ls >= 60:
            in_pos = {'side':'buy','ent':row['c'],'peak':0,'sl':row['c']-(row['atr']*1.5),'tp':row['c']+(row['atr']*5.0)}
        elif ss >= 60:
            in_pos = {'side':'sell','ent':row['c'],'peak':0,'sl':row['c']+(row['atr']*1.5),'tp':row['c']-(row['atr']*5.0)}
            
    return balance, trades

def main():
    print("\n" + "="*85)
    print("GLOBAL WIN PATTERN BACKTEST v28.5 (MOMENTUM CHASE)")
    print("Mencari koin 'Hot' secara otomatis di seluruh bursa...")
    print("="*85)
    
    hot_symbols = get_all_active_symbols()
    print(f"[*] Menemukan {len(hot_symbols)} koin 'Hot' (Gainer/Looser):")
    print(f"    {', '.join(hot_symbols)}")
    print("-" * 85)
    
    total_b = 0; all_t = []
    for s in hot_symbols:
        try:
            df = apply_predator_logic(fetch_data(s))
            b, t = run_backtest(df)
            total_b += b; all_t.extend(t)
            print(f"{s:<12} | SALDO AKHIR: ${b:>7.2f} | Trades: {len(t)}")
        except Exception: pass
        
    print("-" * 85)
    print(f"RATA-RATA SALDO AKHIR DARI 15 KOIN HOT: ${total_b/len(hot_symbols):.2f}")
    print(f"KEUNTUNGAN RATA-RATA PER KOIN : {((total_b/len(hot_symbols)-10)/10)*100:+.1f}%")
    print("="*85)

if __name__ == "__main__": main()
