import requests
import pandas as pd
import numpy as np

def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=5m&limit=1500"
    r = requests.get(url)
    df = pd.DataFrame(r.json(), columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df.dropna()

def apply_gainer_hunter_logic(df):
    """Simulasi logika Gainer/Looser Hunter v26.90"""
    # RVOL Calculation (Recent 1h vol vs 24h avg)
    df['vol_24h'] = df['v'].rolling(288).sum() # 288 candles of 5m = 24h
    df['vol_1h'] = df['v'].rolling(12).sum()   # 12 candles of 5m = 1h
    df['rvol'] = df['vol_1h'] / (df['vol_24h'] / 24)
    
    # OI Surge Mock (Simulasi pergerakan OI searah harga)
    df['oi_change_pct'] = (df['c'].diff().rolling(12).sum() / df['c'].shift(12)).abs() * 50 # Mocking OI surge
    
    # AI Score (v26.85)
    df['high24h'] = df['h'].rolling(288).max()
    df['low24h'] = df['l'].rolling(288).min()
    df['pump_sc'] = 0.0; df['dump_sc'] = 0.0
    
    for i in range(len(df)):
        if i < 288: continue
        row = df.iloc[i]
        p_sc = 0.0; d_sc = 0.0
        # Position in range
        h = row['high24h']; l = row['low24h']; p = row['c']
        pos = (p - l) / (h - l) * 100
        if pos < 40: p_sc += 40
        if pos > 60: d_sc += 40
        # RVOL boost to AI
        if row['rvol'] > 3: p_sc += 30; d_sc += 30
        df.at[df.index[i], 'pump_sc'] = p_sc
        df.at[df.index[i], 'dump_sc'] = d_sc

    df['ema_200'] = df['c'].ewm(span=200).mean()
    df['atr'] = (df['h'] - df['l']).rolling(14).mean()
    delta = df['c'].diff(); g = (delta.where(delta > 0, 0)).rolling(14).mean(); l = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (g/l)))
    df['is_bullish'] = df['c'] > df['o']; df['is_bearish'] = df['c'] < df['o']
    
    return df

def run_backtest(df):
    balance = 10.0; margin = 4.0; lev = 10; fee = 0.0006
    trades = []; in_pos = None
    
    for i in range(288, len(df)):
        row = df.iloc[i]
        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if in_pos['side'] == 'sell': cpnl = -cpnl
            if cpnl > in_pos['peak']: in_pos['peak'] = cpnl
            # TSL 10/0
            if in_pos['peak'] >= 10:
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
                net = (pnl/100 * margin) - (margin * lev * fee * 2)
                balance += net; trades.append(net); in_pos = None
                if balance <= 0.5: break
            continue

        # LOGIKA v26.90
        ai_bias = "LONG" if row['pump_sc'] >= row['dump_sc'] else "SHORT"
        rvol = row['rvol']; oi = row['oi_change_pct']
        ls = 0; ss = 0
        
        # 1. Momentum & Velocity
        if rvol >= 3.0:
            if ai_bias == "LONG": ls += 40
            else: ss += 40
        if oi >= 20:
            if ai_bias == "LONG": ls += 30
            else: ss += 30
        
        # 2. RSI (Momentum Rider)
        if rvol >= 2.5:
            if ai_bias == "LONG" and row['rsi'] > 50: ls += 15
            if ai_bias == "SHORT" and row['rsi'] < 50: ss += 15
        
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
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"]
    print("\n" + "="*80)
    print("BACKTEST GAINER HUNTER v26.90 (MOMENTUM & RVOL FOCUS)")
    print("="*80)
    
    total_bal = 0; all_t = []
    for s in syms:
        df = apply_gainer_hunter_logic(fetch_data(s))
        bal, t = run_backtest(df)
        total_bal += bal; all_t.extend(t)
        print(f"[{s:<8}] Saldo Akhir: ${bal:>7.2f} | Trades: {len(t)}")
        
    print("-" * 80)
    print(f"SALDO RATA-RATA  : ${total_bal/len(syms):.2f} (DARI MODAL $10)")
    print(f"WIN RATE GLOBAL  : {len([x for x in all_t if x > 0])/len(all_t)*100 if all_t else 0:.1f}%")
    print("="*80)

if __name__ == "__main__": main()
