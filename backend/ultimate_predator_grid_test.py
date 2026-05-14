import requests
import pandas as pd
import numpy as np
import itertools

# --- ULTIMATE PREDATOR GRID TEST v27.5 ---
def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1500"
    r = requests.get(url)
    df = pd.DataFrame(r.json(), columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df.dropna()

def prepare_predator_data(df):
    # Technicals
    df['ema_200'] = df['c'].ewm(span=200).mean()
    df['atr'] = (df['h'] - df['l']).rolling(14).mean()
    delta = df['c'].diff(); g = (delta.where(delta > 0, 0)).rolling(14).mean(); l = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (g/l)))
    df['vwap'] = (df['c'] * df['v']).cumsum() / df['v'].cumsum()
    df['vwap_dist'] = ((df['c'] - df['vwap']) / df['vwap']) * 100
    df['is_bullish'] = df['c'] > df['o']; df['is_bearish'] = df['c'] < df['o']
    
    # RVOL & AI Score Preparation
    df['vol_24h'] = df['v'].rolling(96).sum()
    df['vol_1h'] = df['v'].rolling(4).sum() # 4 candles of 15m = 1h
    df['rvol'] = df['vol_1h'] / (df['vol_24h'] / 24)
    df['high24h'] = df['h'].rolling(96).max()
    df['low24h'] = df['l'].rolling(96).min()
    
    # Zones & OB (Exactly like User's logic)
    df['dsz_status'] = 'NONE'; df['liq_grab_bull'] = False; df['liq_grab_bear'] = False
    for i in range(20, len(df)):
        if df['l'].iloc[i] < df['l'].iloc[i-1] and df['c'].iloc[i] > df['l'].iloc[i-1]: df.at[df.index[i], 'liq_grab_bull'] = True
        if df['h'].iloc[i] > df['h'].iloc[i-1] and df['c'].iloc[i] < df['h'].iloc[i-1]: df.at[df.index[i], 'liq_grab_bear'] = True
        body = abs(df['c'].iloc[i-1] - df['o'].iloc[i-1])
        if body > (df['h'].iloc[i-1] - df['l'].iloc[i-1]) * 0.7:
            if df['c'].iloc[i-1] > df['o'].iloc[i-1]:
                if df['l'].iloc[i] <= df['o'].iloc[i-1]: df.at[df.index[i], 'dsz_status'] = 'IN_DEMAND_ZONE'
            else:
                if df['h'].iloc[i] >= df['o'].iloc[i-1]: df.at[df.index[i], 'dsz_status'] = 'IN_SUPPLY_ZONE'
    return df

def run_scenario(df, p):
    balance = 10.0; margin = 3.0; lev = 10; fee = 0.0006
    trades = []; in_pos = None
    
    for i in range(100, len(df)):
        row = df.iloc[i]
        
        # BRAVE AI PUMP/DUMP v27.5
        p_sc = 0.0; d_sc = 0.0
        h = row['high24h']; l = row['low24h']; pr = row['c']
        if h > l:
            pos = (pr - l) / (h - l) * 100
            if row['rvol'] >= 2.0:
                if pos >= 80: p_sc += 40
                elif pos <= 20: d_sc += 40
            else:
                if pos < 40: p_sc += 40
                if pos > 60: d_sc += 40
        if row['rvol'] >= 2.0: p_sc += 30; d_sc += 30
        ai_bias = "LONG" if p_sc >= d_sc else "SHORT"

        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if in_pos['side'] == 'sell': cpnl = -cpnl
            if cpnl > in_pos['peak']: in_pos['peak'] = cpnl
            
            # TSL Dynamic Logic (Exactly like User's logic)
            if in_pos['peak'] >= p['tsl_trig']:
                locked_pnl = max(0.0, (int(in_pos['peak'] / p['tsl_trig']) * p['tsl_trig']) - p['tsl_gap'])
                if in_pos['side'] == 'buy':
                    ns = in_pos['ent'] * (1 + (locked_pnl/100)/lev)
                    if ns > in_pos['sl']: in_pos['sl'] = ns
                else:
                    ns = in_pos['ent'] * (1 - (locked_pnl/100)/lev)
                    if ns < in_pos['sl']: in_pos['sl'] = ns

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

        # CORE SCORING
        ls = 0; ss = 0
        if row['dsz_status'] == 'IN_DEMAND_ZONE' or row['liq_grab_bull']: ls += 40
        if row['dsz_status'] == 'IN_SUPPLY_ZONE' or row['liq_grab_bear']: ss += 40
        if row['c'] > row['ema_200']: ls += 20
        else: ss += 20
        if row['rsi'] < 35: ls += 10
        if row['rsi'] > 65: ss += 10
        
        # BRAVE MOMENTUM BOOST
        if row['rvol'] >= 2.0:
            if ai_bias == "LONG": ls += 40
            else: ss += 40
            
        if not row['is_bullish']: ls -= 50
        if not row['is_bearish']: ss -= 50
        if ai_bias == "SHORT": ls -= 200
        else: ss -= 200
        
        if ls >= 60:
            in_pos = {'side':'buy','ent':row['c'],'peak':0,'sl':row['c']-(row['atr']*p['sl_m']),'tp':row['c']+(row['atr']*p['tp_m'])}
        elif ss >= 60:
            in_pos = {'side':'sell','ent':row['c'],'peak':0,'sl':row['c']+(row['atr']*p['sl_m']),'tp':row['c']-(row['atr']*p['tp_m'])}
            
    return balance, trades

def main():
    syms = ["SOLUSDT", "PEPEUSDT", "DOGEUSDT"]
    data = {s: prepare_predator_data(fetch_data(s)) for s in syms}
    
    # PARAMETER GRID
    sl_mults = [1.0, 1.5]
    tp_mults = [5.0, 8.0] 
    tsl_trigs = [10, 15]
    tsl_gaps = [0, 5]
    
    scenarios = list(itertools.product(sl_mults, tp_mults, tsl_trigs, tsl_gaps))
    results = []
    
    print(f"[*] Menjalankan {len(scenarios)} skenario AI Predator v27.5...")
    
    for s in scenarios:
        p = {'sl_m':s[0], 'tp_m':s[1], 'tsl_trig':s[2], 'tsl_gap':s[3]}
        bals = []; all_t = []
        for sym in syms:
            bal, trades = run_scenario(data[sym], p)
            bals.append(bal); all_t.extend(trades)
            
        avg_bal = sum(bals) / len(bals)
        wr = (len([t for t in all_t if t > 0]) / len(all_t) * 100) if all_t else 0
        
        results.append({'sl_tp': f"{p['sl_m']}/{p['tp_m']}", 'tsl': f"{p['tsl_trig']}/{p['tsl_gap']}", 'bal': avg_bal, 'wr': wr, 'trades': len(all_t)})
        
    results.sort(key=lambda x: x['bal'], reverse=True)
    
    print("\n" + "="*85)
    print(f"{'RANK':<4} | {'SL/TP':<7} | {'TSL(T/G)':<8} | {'TRADES':<6} | {'WR (%)':<6} | {'AVG BAL'}")
    print("-" * 85)
    for i, r in enumerate(results[:10]):
        print(f"#{i+1:<3} | {r['sl_tp']:<7} | {r['tsl']:<8} | {r['trades']:<6} | {r['wr']:>5.1f}% | ${r['bal']:>7.2f}")
    print("="*85)

if __name__ == "__main__": main()
