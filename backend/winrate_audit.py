import requests
import pandas as pd
import numpy as np
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_rsi(series, period=14):
    delta = series.diff()
    u = delta.clip(lower=0)
    d = -delta.clip(upper=0)
    ma_u = u.ewm(com=period-1, adjust=False).mean()
    ma_d = d.ewm(com=period-1, adjust=False).mean()
    rs = ma_u / ma_d
    return 100 - (100 / (1 + rs))

def run_winrate_audit():
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", verify=False).json()
        symbols = [s['symbol'] for s in sorted(r, key=lambda x: float(x['quoteVolume']), reverse=True)[:50] if s['symbol'].endswith('USDT')]
    except: symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    
    trades = []
    print(f"Menganalisis {len(symbols)} koin...")
    
    for sym in symbols:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=15m&limit=1000"
        try:
            res = requests.get(url, verify=False, timeout=10)
            data = res.json()
            df = pd.DataFrame(data, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
            df[['o','h','l','c','v']] = df[['o','h','l','c','v']].astype(float)
            df['rsi'] = get_rsi(df['c'])
            df['rvol'] = df['v'] / df['v'].rolling(20).mean()
            df['atr_pct'] = ((df['h'] - df['l']).rolling(14).mean() / df['c']) * 100
            df = df.dropna()
            
            # Simulation
            active_trade = None
            for i, row in df.iterrows():
                if active_trade:
                    if row['l'] <= active_trade['sl']:
                        trades.append({'res': 'LOSS', 'pnl': -50})
                        active_trade = None
                    elif row['h'] >= active_trade['tp']:
                        trades.append({'res': 'WIN', 'pnl': 40})
                        active_trade = None
                    continue

                if row['rsi'] > 65 and row['rvol'] > 2.0 and row['atr_pct'] > 0.5:
                    active_trade = {
                        'ent': row['c'],
                        'sl': row['c'] * 0.95,
                        'tp': row['c'] * 1.04
                    }
        except: continue

    if trades:
        res_df = pd.DataFrame(trades)
        win_count = len(res_df[res_df['res'] == 'WIN'])
        loss_count = len(res_df[res_df['res'] == 'LOSS'])
        wr = (win_count / len(res_df)) * 100
        print(f"\n--- HASIL AUDIT MASSAL (50 KOIN) ---")
        print(f"Total Tembakan Selesai: {len(res_df)}")
        print(f"Total Menang (WIN)     : {win_count}")
        print(f"Total Kalah (LOSS)     : {loss_count}")
        print(f"Win Rate               : {wr:.1f}%")
        print(f"Estimasi Profit Bersih : {res_df['pnl'].sum()}% PnL")
    else:
        print("Tidak ada trade selesai.")

if __name__ == "__main__":
    run_winrate_audit()
