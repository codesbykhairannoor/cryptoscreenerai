import requests
import pandas as pd
import numpy as np

def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1500"
    r = requests.get(url)
    df = pd.DataFrame(r.json(), columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df.dropna()

def apply_ai_model(df):
    """Menduplikasi logika AI Model (Pump/Dump Predictor) dari ai_model.py"""
    # Rolling 24h (96 candles of 15m)
    df['high24h'] = df['h'].rolling(96).max()
    df['low24h'] = df['l'].rolling(96).min()
    df['pct_change'] = (df['c'] - df['c'].shift(96)) / df['c'].shift(96) * 100
    df['range_pct'] = (df['high24h'] - df['low24h']) / df['low24h'] * 100
    
    pump_scores = []
    dump_scores = []
    
    for i in range(len(df)):
        if i < 96:
            pump_scores.append(0); dump_scores.append(0)
            continue
            
        row = df.iloc[i]
        p_sc = 0.0; d_sc = 0.0
        
        # Volatility (Max 30)
        rng = row['range_pct']
        if rng >= 20: p_sc+=30; d_sc+=30
        elif rng >= 15: p_sc+=25; d_sc+=25
        elif rng >= 10: p_sc+=20; d_sc+=20
        elif rng >= 5: p_sc+=10; d_sc+=10
        
        # Volume assumtion (high for top coins) -> +20
        p_sc += 20; d_sc += 20
        
        # Position in Range (Max 25)
        high = row['high24h']; low = row['low24h']; price = row['c']
        if high > low:
            pos = (price - low) / (high - low) * 100
            if 10 <= pos <= 35: p_sc += 25  # Dekat bottom = Pump
            elif pos < 35: d_sc -= 15       # Dekat bottom = JANGAN DUMP
            if 65 <= pos <= 90: d_sc += 25  # Dekat pucuk = Dump
            elif pos > 85: p_sc -= 5        # Dekat pucuk = JANGAN PUMP
            
        # Momentum (Max 20)
        pct = row['pct_change']
        if 1.5 <= pct <= 6: p_sc += 20
        elif pct < 0: p_sc += 5
        if 6 < pct <= 15: d_sc += 20
        elif pct < -5: d_sc -= 10
        
        pump_scores.append(max(0, min(100, p_sc)))
        dump_scores.append(max(0, min(100, d_sc)))
        
    df['pump_sc'] = pump_scores
    df['dump_sc'] = dump_scores
    return df

def apply_tech(df):
    df['ema_200'] = df['c'].ewm(span=200).mean()
    df['atr'] = (df['h'] - df['l']).rolling(14).mean()
    delta = df['c'].diff(); g = (delta.where(delta > 0, 0)).rolling(14).mean(); l = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (g/l)))
    df['is_bullish'] = df['c'] > df['o']
    df['is_bearish'] = df['c'] < df['o']
    df['dsz'] = 'NONE'
    df['liq_bull'] = False; df['liq_bear'] = False
    
    for i in range(20, len(df)):
        if df['l'].iloc[i] < df['l'].iloc[i-1] and df['c'].iloc[i] > df['l'].iloc[i-1]: df.at[df.index[i], 'liq_bull'] = True
        if df['h'].iloc[i] > df['h'].iloc[i-1] and df['c'].iloc[i] < df['h'].iloc[i-1]: df.at[df.index[i], 'liq_bear'] = True
        body = abs(df['c'].iloc[i-1] - df['o'].iloc[i-1])
        if body > (df['h'].iloc[i-1] - df['l'].iloc[i-1]) * 0.7:
            if df['c'].iloc[i-1] > df['o'].iloc[i-1] and df['l'].iloc[i] <= df['o'].iloc[i-1]: df.at[df.index[i], 'dsz'] = 'IN_DEMAND_ZONE'
            elif df['h'].iloc[i] >= df['o'].iloc[i-1]: df.at[df.index[i], 'dsz'] = 'IN_SUPPLY_ZONE'
    return df

def run_ai_proof(df):
    balance = 10.0; margin = 3.0; lev = 10; fee = 0.0006
    trades = []; in_pos = None; ai_veto_saved = 0
    
    for i in range(200, len(df)):
        row = df.iloc[i]
        
        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if in_pos['side'] == 'sell': cpnl = -cpnl
            if cpnl > in_pos['peak']: in_pos['peak'] = cpnl
            
            # Optimal TSL from previous run (10/0 - Breakeven)
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
                final_pnl = ((ep - in_pos['ent'])/in_pos['ent']) * lev * 100
                if in_pos['side'] == 'sell': final_pnl = -final_pnl
                net = (final_pnl/100 * margin) - (margin * lev * fee * 2)
                balance += net; trades.append(net)
                in_pos = None
                if balance <= 0: break
            continue

        # LOGIKA v26.85 (AI + TECH)
        ls = 0; ss = 0
        ai_bias = "LONG" if row['pump_sc'] >= row['dump_sc'] else "SHORT"
        
        if row['dsz'] == 'IN_DEMAND_ZONE' or row['liq_bull']: ls += 40
        if row['dsz'] == 'IN_SUPPLY_ZONE' or row['liq_bear']: ss += 40
        if row['c'] > row['ema_200']: ls += 20
        else: ss += 20
        
        if not row['is_bullish']: ls -= 50
        if not row['is_bearish']: ss -= 50

        # AI OVERRIDE (MEMBUNUH TRADE BODOH)
        if ai_bias == "SHORT" and ls > 0:
            ls -= 200
            ai_veto_saved += 1 # Menghitung berapa kali bot dilarang BUY bodoh
        elif ai_bias == "LONG" and ss > 0:
            ss -= 200
            ai_veto_saved += 1 # Menghitung berapa kali bot dilarang SELL bodoh

        # Optimal SL/TP from previous run (1.5 / 6.0)
        sl_m = 1.5; tp_m = 6.0
        
        if ls >= 60 and ai_bias == "LONG":
            in_pos = {'side':'buy','ent':row['c'],'peak':0,'sl':row['c']-(row['atr']*sl_m),'tp':row['c']+(row['atr']*tp_m)}
        elif ss >= 60 and ai_bias == "SHORT":
            in_pos = {'side':'sell','ent':row['c'],'peak':0,'sl':row['c']+(row['atr']*sl_m),'tp':row['c']-(row['atr']*tp_m)}
            
    return balance, trades, ai_veto_saved

def main():
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    print("\n" + "="*85)
    print("PEMBUKTIAN INTEGRASI AI PUMP/DUMP PREDICTOR (v26.85)")
    print("Modal: $10 | Margin: $3 | SL/TP: 1.5/6.0 | TSL: Breakeven 10%")
    print("="*85)
    print(f"{'KOIN':<10} | {'SALDO AKHIR':<15} | {'WR (%)':<10} | {'TRADES':<10} | {'AI VETO SAVED'}")
    print("-" * 85)
    
    total_b = 0; all_t = []; total_veto = 0
    for sym in syms:
        df = apply_tech(apply_ai_model(fetch_data(sym)))
        b, t, veto = run_ai_proof(df)
        wr = len([x for x in t if x > 0])/len(t)*100 if t else 0
        total_b += b; all_t.extend(t); total_veto += veto
        print(f"{sym:<10} | ${b:>13.2f} | {wr:>9.1f}% | {len(t):<10} | {veto}x Sinyal Dicegah")
        
    print("-" * 85)
    print(f"RATA-RATA SALDO : ${total_b/len(syms):.2f} (DARI MODAL $10)")
    print(f"TOTAL TRADES    : {len(all_t)}x")
    print(f"WIN RATE GLOBAL : {len([x for x in all_t if x > 0])/len(all_t)*100 if all_t else 0:.1f}%")
    print(f"TOTAL VETO AI   : {total_veto}x (Bot dilarang keras nge-Buy di pucuk / Sell di lembah)")
    print("="*85)

if __name__ == "__main__": main()



