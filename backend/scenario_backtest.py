import requests
import pandas as pd
import numpy as np
import itertools

# --- MULTI-SCENARIO BACKTEST v26.81 ---
def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1500"
    r = requests.get(url)
    df = pd.DataFrame(r.json(), columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df.dropna()

def prepare_tech_data(df):
    df['ema_200'] = df['c'].ewm(span=200).mean()
    df['atr'] = (df['h'] - df['l']).rolling(14).mean()
    delta = df['c'].diff(); g = (delta.where(delta > 0, 0)).rolling(14).mean(); l_loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (g/l_loss)))
    
    df['vwap'] = (df['c'] * df['v']).cumsum() / df['v'].cumsum()
    df['vwap_dist'] = ((df['c'] - df['vwap']) / df['vwap']) * 100
    df['obi'] = 0.2 * np.random.randn(len(df)) # Mock OBI
    
    df['is_bullish'] = df['c'] > df['o']
    df['is_bearish'] = df['c'] < df['o']
    df['still_falling'] = (df['c'] < df['ema_200']) & df['is_bearish']
    df['still_rising'] = (df['c'] > df['ema_200']) & df['is_bullish']
    
    df['dsz_status'] = 'NONE'
    df['liq_grab_bull'] = False; df['liq_grab_bear'] = False
    df['ob_bull'] = False; df['ob_bear'] = False
    
    for i in range(20, len(df)):
        if df['c'].iloc[i] > df['h'].iloc[i-1] and df['c'].iloc[i-1] < df['o'].iloc[i-1]: df.at[df.index[i], 'ob_bull'] = True
        if df['c'].iloc[i] < df['l'].iloc[i-1] and df['c'].iloc[i-1] > df['o'].iloc[i-1]: df.at[df.index[i], 'ob_bear'] = True
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
    trades = []; in_pos = None; tsl_hits = 0
    
    for i in range(200, len(df)):
        row = df.iloc[i]
        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if in_pos['side'] == 'sell': cpnl = -cpnl
            if cpnl > in_pos['peak']: in_pos['peak'] = cpnl
            
            # TSL Dynamic Logic
            if in_pos['peak'] >= p['tsl_trig']:
                locked_pnl = max(0.0, (int(in_pos['peak'] / p['tsl_trig']) * p['tsl_trig']) - p['tsl_gap'])
                if in_pos['side'] == 'buy':
                    ns = in_pos['ent'] * (1 + (locked_pnl/100)/lev)
                    if ns > in_pos['sl']: in_pos['sl'] = ns
                else:
                    ns = in_pos['ent'] * (1 - (locked_pnl/100)/lev)
                    if ns < in_pos['sl']: in_pos['sl'] = ns

            ep = 0; is_tsl = False
            if in_pos['side'] == 'buy':
                if row['l'] <= in_pos['sl']: ep = in_pos['sl']; is_tsl = in_pos['sl'] > in_pos['ent']
                elif row['h'] >= in_pos['tp']: ep = in_pos['tp']
            else:
                if row['h'] >= in_pos['sl']: ep = in_pos['sl']; is_tsl = in_pos['sl'] < in_pos['ent']
                elif row['l'] <= in_pos['tp']: ep = in_pos['tp']
            
            if ep > 0:
                final_pnl = ((ep - in_pos['ent'])/in_pos['ent']) * lev * 100
                if in_pos['side'] == 'sell': final_pnl = -final_pnl
                net = (final_pnl/100 * margin) - (margin * lev * fee * 2)
                balance += net; trades.append(net)
                if is_tsl: tsl_hits += 1
                in_pos = None
                if balance <= 0.2: break
            continue

        # LOGIKA SCORING ASLI
        ls = 0; ss = 0
        if row['dsz_status'] == 'IN_DEMAND_ZONE' or row['liq_grab_bull']: ls += 40
        if row['dsz_status'] == 'IN_SUPPLY_ZONE' or row['liq_grab_bear']: ss += 40
        if row['c'] > row['ema_200']: ls += 20
        else: ss += 20
        if row['obi'] > 0.15: ls += 15
        elif row['obi'] < -0.15: ss += 15
        if row['ob_bull']: ls += 15
        if row['ob_bear']: ss += 15
        if row['rsi'] < 35: ls += 10
        if row['rsi'] > 65: ss += 10
        if row['vwap_dist'] < -1.0: ls += 10
        if row['vwap_dist'] > 1.0: ss += 10
        
        # ANTI-FALLING KNIFE & CANDLE CONFIRMATION
        if row['still_falling'] and not (row['liq_grab_bull'] or row['dsz_status'] == 'IN_DEMAND_ZONE'): ls -= 50
        if row['still_rising'] and not (row['liq_grab_bear'] or row['dsz_status'] == 'IN_SUPPLY_ZONE'): ss -= 50
        if not row['is_bullish']: ls -= 50
        if not row['is_bearish']: ss -= 50
        
        if ls >= 60:
            in_pos = {'side':'buy','ent':row['c'],'peak':0,'sl':row['c']-(row['atr']*p['sl_m']),'tp':row['c']+(row['atr']*p['tp_m'])}
        elif ss >= 60:
            in_pos = {'side':'sell','ent':row['c'],'peak':0,'sl':row['c']+(row['atr']*p['sl_m']),'tp':row['c']-(row['atr']*p['tp_m'])}
            
    return balance, trades, tsl_hits

def main():
    syms = ["BTCUSDT", "SOLUSDT"]
    data = {s: prepare_tech_data(fetch_data(s)) for s in syms}
    
    # PARAMETER GRID (Mencari Settingan Dewa)
    sl_mults = [0.8, 1.5]
    tp_mults = [2.0, 5.0, 8.0] 
    tsl_trigs = [10, 20, 30]
    tsl_gaps = [0, 10]
    
    scenarios = list(itertools.product(sl_mults, tp_mults, tsl_trigs, tsl_gaps))
    results = []
    
    print(f"[*] Menjalankan {len(scenarios)} skenario...")
    
    for s in scenarios:
        p = {'sl_m':s[0], 'tp_m':s[1], 'tsl_trig':s[2], 'tsl_gap':s[3]}
        if p['tsl_gap'] >= p['tsl_trig']: continue # Skip illogical setting
        
        bals = []; all_trades = []; total_tsl = 0
        for sym in syms:
            bal, trades, tsls = run_scenario(data[sym], p)
            bals.append(bal); all_trades.extend(trades); total_tsl += tsls
            
        avg_bal = sum(bals) / len(bals)
        wins = len([t for t in all_trades if t > 0])
        wr = (wins / len(all_trades) * 100) if len(all_trades) > 0 else 0
        
        results.append({
            'sl_tp': f"{p['sl_m']}/{p['tp_m']}",
            'tsl': f"{p['tsl_trig']}/{p['tsl_gap']}",
            'bal': avg_bal,
            'wr': wr,
            'trades': len(all_trades),
            'tsls': total_tsl
        })
        
    results.sort(key=lambda x: x['bal'], reverse=True)
    
    print("\n" + "="*85)
    print(f"{'RANK':<4} | {'SL/TP':<7} | {'TSL(T/G)':<8} | {'TRADES':<6} | {'WR (%)':<6} | {'TSL HITS':<8} | {'AVG BAL'}")
    print("-" * 85)
    for i, r in enumerate(results[:15]):
        print(f"#{i+1:<3} | {r['sl_tp']:<7} | {r['tsl']:<8} | {r['trades']:<6} | {r['wr']:>5.1f}% | {r['tsls']:<8} | ${r['bal']:>7.2f}")
    print("="*85)

if __name__ == "__main__": main()
