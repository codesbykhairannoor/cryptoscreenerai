import requests
import pandas as pd
import numpy as np
import itertools

# --- HYPER-OPTIMIZER v26.77 (MASSIVE SCENARIO ATTACK) ---

def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=5m&limit=1500"
    r = requests.get(url)
    df = pd.DataFrame(r.json(), columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    df['ema_200'] = df['c'].ewm(span=200).mean()
    df['atr'] = (df['h'] - df['l']).rolling(14).mean()
    delta = df['c'].diff(); g = (delta.where(delta > 0, 0)).rolling(14).mean(); l = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (g/l)))
    df['ob_bull'] = (df['c'] > df['h'].shift(1)) & (df['c'].shift(1) < df['o'].shift(1))
    df['ob_bear'] = (df['c'] < df['l'].shift(1)) & (df['c'].shift(1) > df['o'].shift(1))
    return df.dropna()

def simulate(df, p):
    balance = 10.0
    margin = 3.0
    lev = 10
    fee = 0.0006 # 0.06% Taker Fee
    trades = []
    in_pos = None
    
    for i in range(len(df)):
        row = df.iloc[i]
        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if in_pos['side'] == 'sell': cpnl = -cpnl
            if cpnl > in_pos['peak']: in_pos['peak'] = cpnl
            
            # Trailing
            if in_pos['peak'] >= p['t_tr']:
                lock = max(0.0, (int(in_pos['peak'] / p['t_tr']) * p['t_tr']) - p['t_g'])
                if in_pos['side'] == 'buy':
                    ns = in_pos['ent'] * (1 + (lock/100)/lev)
                    if ns > in_pos['sl']: in_pos['sl'] = ns
                else:
                    ns = in_pos['ent'] * (1 - (lock/100)/lev)
                    if ns < in_pos['sl']: in_pos['sl'] = ns

            # Exit
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
                balance += net
                trades.append(net)
                in_pos = None
                if balance <= 0.2: break
            continue

        # Dynamic Scoring Logic
        slong = 0; sshort = 0; ut = row['c'] > row['ema_200']
        # RSI Weight
        if ut and 40 <= row['rsi'] <= 65: slong += p['w_rsi']
        elif not ut and 45 <= row['rsi'] <= 75: sshort += p['w_rsi']
        # SMC Weight
        if row['ob_bull']: slong += p['w_smc']
        if row['ob_bear']: sshort += p['w_smc']
        
        fs = slong if slong >= sshort else sshort
        side = 'buy' if slong >= sshort else 'sell'
        
        if fs >= p['m_sc']:
            in_pos = {'side':side,'ent':row['c'],'peak':0,
                      'sl':row['c']-(row['atr']*p['sl_m']) if side=='buy' else row['c']+(row['atr']*p['sl_m']),
                      'tp':row['c']+(row['atr']*p['tp_m']) if side=='buy' else row['c']-(row['atr']*p['tp_m'])}
    
    return balance, len(trades)

def main():
    syms = ["BTCUSDT", "SOLUSDT"]
    data = {s: fetch_data(s) for s in syms}
    
    # HYPER PARAMETER GRID
    m_scores = [30, 45, 60]
    w_rsis = [20, 30]
    w_smcs = [30, 40]
    sl_tps = [(0.7, 1.5), (1.0, 3.0)]
    tsls = [(20, 10), (30, 0)] # Trigger, Gap
    
    scenarios = list(itertools.product(m_scores, w_rsis, w_smcs, sl_tps, tsls))
    results = []
    
    print(f"[*] Menjalankan {len(scenarios)} skenario...")
    
    for s in scenarios:
        p = {'m_sc':s[0], 'w_rsi':s[1], 'w_smc':s[2], 'sl_m':s[3][0], 'tp_m':s[3][1], 't_tr':s[4][0], 't_g':s[4][1]}
        
        bals = []
        counts = []
        for sym in syms:
            bal, count = simulate(data[sym], p)
            bals.append(bal)
            counts.append(count)
            
        avg_bal = sum(bals) / len(bals)
        results.append({'p': p, 'bal': avg_bal, 'counts': sum(counts), 'details': bals})
        
    results.sort(key=lambda x: x['bal'], reverse=True)
    
    print("\n" + "="*120)
    print(f"{'RANK':<4} | {'SCORE':<5} | {'W_RSI':<5} | {'W_SMC':<5} | {'SL/TP':<8} | {'TSL':<8} | {'TRADES':<6} | {'AVG BAL'}")
    print("-" * 120)
    for i, r in enumerate(results[:15]):
        p = r['p']
        print(f"#{i+1:<3} | {p['m_sc']:<5} | {p['w_rsi']:<5} | {p['w_smc']:<5} | {f'{p['sl_m']}/{p['tp_m']}':<8} | {f'{p['t_tr']}/{p['t_g']}':<8} | {r['counts']:<6} | ${r['bal']:>7.2f}")
    print("="*120)

if __name__ == "__main__": main()



