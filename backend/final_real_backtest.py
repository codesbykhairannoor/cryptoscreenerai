import requests
import pandas as pd
import numpy as np

# --- FINAL REAL BACKTEST v26.81 ---
def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1500"
    r = requests.get(url)
    df = pd.DataFrame(r.json(), columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df.dropna()

def prepare_tech_data(df):
    df['ema_200'] = df['c'].ewm(span=200).mean()
    df['atr'] = (df['h'] - df['l']).rolling(14).mean()
    delta = df['c'].diff()
    g = (delta.where(delta > 0, 0)).rolling(14).mean()
    l_loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (g/l_loss)))
    
    # VWAP & OBI Mock
    df['vwap'] = (df['c'] * df['v']).cumsum() / df['v'].cumsum()
    df['vwap_dist'] = ((df['c'] - df['vwap']) / df['vwap']) * 100
    df['obi'] = 0.2 * np.random.randn(len(df)) # Mock OBI volatility
    
    # Candlestick States
    df['is_bullish'] = df['c'] > df['o']
    df['is_bearish'] = df['c'] < df['o']
    
    df['still_falling'] = (df['c'] < df['ema_200']) & df['is_bearish']
    df['still_rising'] = (df['c'] > df['ema_200']) & df['is_bullish']
    
    # Institutional Zones & Sweeps
    df['dsz_status'] = 'NONE'
    df['liq_grab_bull'] = False
    df['liq_grab_bear'] = False
    df['mss_bullish'] = False
    df['mss_bearish'] = False
    df['ob_bull'] = False
    df['ob_bear'] = False
    
    for i in range(20, len(df)):
        # OB
        if df['c'].iloc[i] > df['h'].iloc[i-1] and df['c'].iloc[i-1] < df['o'].iloc[i-1]: df.at[df.index[i], 'ob_bull'] = True
        if df['c'].iloc[i] < df['l'].iloc[i-1] and df['c'].iloc[i-1] > df['o'].iloc[i-1]: df.at[df.index[i], 'ob_bear'] = True
        
        # Liq Grab
        if df['l'].iloc[i] < df['l'].iloc[i-1] and df['c'].iloc[i] > df['l'].iloc[i-1]: df.at[df.index[i], 'liq_grab_bull'] = True
        if df['h'].iloc[i] > df['h'].iloc[i-1] and df['c'].iloc[i] < df['h'].iloc[i-1]: df.at[df.index[i], 'liq_grab_bear'] = True
            
        # DSZ
        body = abs(df['c'].iloc[i-1] - df['o'].iloc[i-1])
        if body > (df['h'].iloc[i-1] - df['l'].iloc[i-1]) * 0.7:
            if df['c'].iloc[i-1] > df['o'].iloc[i-1]:
                if df['l'].iloc[i] <= df['o'].iloc[i-1]: df.at[df.index[i], 'dsz_status'] = 'IN_DEMAND_ZONE'
            else:
                if df['h'].iloc[i] >= df['o'].iloc[i-1]: df.at[df.index[i], 'dsz_status'] = 'IN_SUPPLY_ZONE'

    return df

def run_real_backtest(df):
    balance = 10.0
    margin = 3.0
    lev = 10
    fee = 0.0006
    trades = []
    in_pos = None
    
    stats = {'win': 0, 'loss': 0, 'tsl_hits': 0}
    
    for i in range(200, len(df)):
        row = df.iloc[i]
        
        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if in_pos['side'] == 'sell': cpnl = -cpnl
            if cpnl > in_pos['peak']: in_pos['peak'] = cpnl
            
            # TSL 20/10 Logic from bitget_executor.py
            if in_pos['peak'] >= 20:
                locked_pnl = (int(in_pos['peak'] / 20) * 20) - 10
                locked_pnl = max(0.0, locked_pnl)
                
                if in_pos['side'] == 'buy':
                    ns = in_pos['ent'] * (1 + (locked_pnl/100)/lev)
                    if ns > in_pos['sl']: in_pos['sl'] = ns
                else:
                    ns = in_pos['ent'] * (1 - (locked_pnl/100)/lev)
                    if ns < in_pos['sl']: in_pos['sl'] = ns

            # Exit
            ep = 0; exit_type = ""
            if in_pos['side'] == 'buy':
                if row['l'] <= in_pos['sl']: 
                    ep = in_pos['sl']
                    exit_type = "TSL" if in_pos['sl'] > in_pos['ent'] else "SL"
                elif row['h'] >= in_pos['tp']: 
                    ep = in_pos['tp']
                    exit_type = "TP"
            else:
                if row['h'] >= in_pos['sl']: 
                    ep = in_pos['sl']
                    exit_type = "TSL" if in_pos['sl'] < in_pos['ent'] else "SL"
                elif row['l'] <= in_pos['tp']: 
                    ep = in_pos['tp']
                    exit_type = "TP"
            
            if ep > 0:
                final_pnl = ((ep - in_pos['ent'])/in_pos['ent']) * lev * 100
                if in_pos['side'] == 'sell': final_pnl = -final_pnl
                net = (final_pnl/100 * margin) - (margin * lev * fee * 2)
                balance += net
                trades.append(net)
                
                if net > 0:
                    stats['win'] += 1
                    if exit_type == "TSL": stats['tsl_hits'] += 1
                else:
                    stats['loss'] += 1
                    
                in_pos = None
                if balance <= 0.2: break
            continue

        # LOGIKA SCORING ASLI v26.81 (crypto_engine.py)
        ls = 0; ss = 0
        
        if row['dsz_status'] == 'IN_DEMAND_ZONE' or row['liq_grab_bull']: ls += 40
        if row['dsz_status'] == 'IN_SUPPLY_ZONE' or row['liq_grab_bear']: ss += 40
        
        is_up = row['c'] > row['ema_200']
        if is_up: ls += 20
        else: ss += 20
        
        if row['obi'] > 0.15: ls += 15
        elif row['obi'] < -0.15: ss += 15
        
        if row['ob_bull']: ls += 15
        if row['ob_bear']: ss += 15
        
        if row['rsi'] < 35: ls += 10
        if row['rsi'] > 65: ss += 10
        
        if row['vwap_dist'] < -1.0: ls += 10
        if row['vwap_dist'] > 1.0: ss += 10
        
        # ANTI-FALLING KNIFE & CANDLE CONFIRMATION (v26.81)
        if row['still_falling'] and not (row['liq_grab_bull'] or row['dsz_status'] == 'IN_DEMAND_ZONE'): ls -= 50
        if row['still_rising'] and not (row['liq_grab_bear'] or row['dsz_status'] == 'IN_SUPPLY_ZONE'): ss -= 50
        
        if not row['is_bullish']: ls -= 50 # Bunuh skor Buy jika candle merah
        if not row['is_bearish']: ss -= 50 # Bunuh skor Sell jika candle hijau
        
        if ls >= 60:
            in_pos = {'side':'buy','ent':row['c'],'peak':0,'sl':row['c']-(row['atr']*0.8),'tp':row['c']+(row['atr']*2.0)}
        elif ss >= 60:
            in_pos = {'side':'sell','ent':row['c'],'peak':0,'sl':row['c']+(row['atr']*0.8),'tp':row['c']-(row['atr']*2.0)}
            
    return balance, stats

def main():
    print("\n" + "="*80)
    print("BACKTEST LOGIKA ASLI v26.81 (ANTI-FALLING KNIFE & TSL 20/10)")
    print("Modal: $10 | Margin: $3 | Leverage: 10x | Fee Taker: 0.06%")
    print("="*80)
    print(f"{'KOIN':<10} | {'SALDO':<8} | {'WR (%)':<8} | {'WIN/LOSS':<15} | {'TSL HITS (SELAMAT)'}")
    print("-" * 80)
    
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        df = prepare_tech_data(fetch_data(sym))
        bal, stats = run_real_backtest(df)
        total = stats['win'] + stats['loss']
        wr = (stats['win'] / total * 100) if total > 0 else 0
        wl_str = f"{stats['win']} W / {stats['loss']} L"
        
        print(f"{sym:<10} | ${bal:>6.2f} | {wr:>6.1f}% | {wl_str:<15} | {stats['tsl_hits']}x TSL Hit")
    print("="*80)

if __name__ == "__main__": main()
