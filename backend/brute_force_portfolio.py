import requests
import pandas as pd
import numpy as np
from itertools import product
from concurrent.futures import ProcessPoolExecutor

print("\n" + "="*80)
print("BRUTE FORCE PORTFOLIO SIMULATOR: MENCARI SETTINGAN ABSOLUT")
print("Target: Memaksimalkan Saldo $10 dengan Pola Holy Grail")
print("="*80)

def fetch_data(symbol):
    try:
        r = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1000", timeout=5).json()
        df = pd.DataFrame(r, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        
        df['atr'] = (df['h'] - df['l']).rolling(14).mean()
        df['atr_pct'] = (df['atr'] / df['c']) * 100
        df['rvol'] = df['v'] / df['v'].rolling(20).mean()
        
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        
        return symbol, df.dropna().set_index('ts')
    except: return symbol, None

def simulate_scenario(args):
    tp_pct, sl_pct, use_trailing, market_data, sorted_ts = args
    wallet = 10.0
    margin = 5.0
    lev = 10
    active_pos = None
    trades = []
    
    for ts in sorted_ts:
        if active_pos:
            df = market_data[active_pos['sym']]
            if ts in df.index:
                row = df.loc[ts]
                
                # Trailing SL Logic
                if use_trailing:
                    cpnl = ((row['c'] - active_pos['ent'])/active_pos['ent']) * lev * 100
                    if cpnl > active_pos['peak']: active_pos['peak'] = cpnl
                    if active_pos['peak'] >= 10:
                        locked = float((int(active_pos['peak'] / 10) * 10) - 5)
                        new_sl = active_pos['ent'] * (1 + (locked/100)/lev)
                        if new_sl > active_pos['sl']: active_pos['sl'] = new_sl
                
                ep = 0
                if row['l'] <= active_pos['sl']: ep = active_pos['sl']
                elif row['h'] >= active_pos['tp']: ep = active_pos['tp']
                
                if ep > 0:
                    f_pnl = ((ep - active_pos['ent'])/active_pos['ent']) * lev * 100
                    # Hitung Net Profit (DIKURANGI FEE BURSA $0.06 PER TRADE)
                    net = (f_pnl/100 * margin) - 0.06
                    wallet += net
                    trades.append(net)
                    active_pos = None
            continue

        if active_pos is None and wallet >= margin:
            for sym, df in market_data.items():
                if ts not in df.index: continue
                row = df.loc[ts]
                
                # Entry Mutlak: Holy Grail Breakout
                if row.get('rsi', 0) > 65 and row.get('rvol', 0) > 2.0 and row.get('atr_pct', 0) > 0.5:
                    active_pos = {
                        'sym': sym, 'ent': row['c'], 'peak': 0,
                        'sl': row['c'] * (1 - (sl_pct/100)),
                        'tp': row['c'] * (1 + (tp_pct/100))
                    }
                    break # Hanya bisa masuk 1 koin (Portfolio constraint)
                    
    return {
        'tp': tp_pct, 'sl': sl_pct, 'trailing': use_trailing,
        'final_wallet': wallet, 'trades': len(trades),
        'wins': sum(1 for t in trades if t > 0)
    }

if __name__ == "__main__":
    # Siapkan Data Sekali Saja
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr").json()
        symbols = [s['symbol'] for s in sorted(r, key=lambda x: float(x['quoteVolume']), reverse=True)[:20] if s['symbol'].endswith('USDT')]
    except: symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    print("Mengunduh data market...")
    market_data = {}
    all_ts = set()
    for s in symbols:
        sym, df = fetch_data(s)
        if df is not None:
            market_data[sym] = df
            all_ts.update(df.index.tolist())
    sorted_ts = sorted(list(all_ts))
    print("Data siap. Memulai Brute Force!\n")

    # Grid Search Parameters (Harga Murni, bukan PnL)
    tp_options = [1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 10.0]
    sl_options = [0.5, 0.8, 1.0, 1.5, 2.0, 3.0, 5.0]
    trail_options = [False, True]
    
    scenarios = []
    for tp, sl, tr in product(tp_options, sl_options, trail_options):
        scenarios.append((tp, sl, tr, market_data, sorted_ts))
        
    print(f"Menjalankan {len(scenarios)} skenario portofolio yang berbeda secara berurutan...")
    
    best_result = None
    results = []
    
    # Eksekusi secara single-thread agar ramah memori, python cepat kok
    for args in scenarios:
        res = simulate_scenario(args)
        results.append(res)
        
    results.sort(key=lambda x: x['final_wallet'], reverse=True)
    
    print("\n" + "="*80)
    print("JUARA 1: SETTINGAN ABSOLUT UNTUK SALDO $10")
    print("="*80)
    best = results[0]
    
    wr = (best['wins']/best['trades']*100) if best['trades'] > 0 else 0
    print(f"Take Profit   : {best['tp']}% Harga ({best['tp']*10}% PnL)")
    print(f"Stop Loss     : {best['sl']}% Harga ({best['sl']*10}% PnL)")
    print(f"Trailing SL   : {'NYALA' if best['trailing'] else 'MATI'}")
    print(f"Total Trade   : {best['trades']} Trades (Sudah dipotong Fee)")
    print(f"Win Rate      : {wr:.1f}%")
    print(f"SALDO AKHIR   : ${best['final_wallet']:.2f}")
    
    print("\n[Top 5 Skenario Lainnya]")
    for r in results[1:6]:
        wr_r = (r['wins']/r['trades']*100) if r['trades'] > 0 else 0
        print(f"TP {r['tp']}% | SL {r['sl']}% | Trail: {r['trailing']} => Saldo: ${r['final_wallet']:.2f} (WR: {wr_r:.1f}%)")



