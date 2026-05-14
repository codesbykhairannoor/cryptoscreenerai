import pandas as pd
import numpy as np
import requests
import warnings
warnings.filterwarnings("ignore")

class MachineGunAuditor:
    def __init__(self, symbol):
        self.symbol = symbol
        self.df = None

    def fetch(self):
        # Ambil 1500 candle 1m (sekitar 1 hari lebih data padat)
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={self.symbol}&interval=1m&limit=1500"
        try:
            r = requests.get(url, verify=False, timeout=15)
            data = r.json()
            df = pd.DataFrame(data, columns=['ts','open','high','low','close','vol','cts','qvol','tr','tbb','tbq','i'])
            df[['open','high','low','close','vol']] = df[['open','high','low','close','vol']].astype(float)
            self.df = df
        except: pass

    def run(self):
        if self.df is None or len(self.df) < 100: return None
        df = self.df.copy()
        df['ema'] = df['close'].ewm(span=100).mean() # EMA lebih pendek untuk 1m
        tr = np.maximum(df['high']-df['low'], np.maximum(np.abs(df['high']-df['close'].shift()), np.abs(df['low']-df['close'].shift())))
        df['atr'] = tr.rolling(14).mean()
        df['l_min'] = df['low'].rolling(10).min(); df['h_max'] = df['high'].rolling(10).max() # Window lebih kecil
        
        df['lg_bull'] = (df['low'] < df['l_min'].shift(1)) & (df['close'] > df['l_min'].shift(1))
        df['lg_bear'] = (df['high'] > df['h_max'].shift(1)) & (df['close'] < df['h_max'].shift(1))
        
        wins=0; trades=0; pnl=0; pos=0; entry=0; tp=0; sl=0
        # MACHINE GUN SETTINGS:
        tp_m=1.2; sl_m=1.0; thresh=20 # Lebih agresif
        
        for i in range(20, len(df)):
            row = df.iloc[i]
            if pos != 0:
                if pos == 1:
                    if row['high'] >= tp: wins += 1; trades += 1; pnl += (tp-entry)/entry; pos = 0
                    elif row['low'] <= sl: trades += 1; pnl -= (entry-sl)/entry; pos = 0
                elif pos == -1:
                    if row['low'] <= tp: wins += 1; trades += 1; pnl += (entry-tp)/entry; pos = 0
                    elif row['high'] >= sl: trades += 1; pnl -= (sl-entry)/entry; pos = 0
                continue
            
            # Skor lebih gampang didapat
            l_score = (30 if row['lg_bull'] else 0) + (10 if row['close'] > row['ema'] else 0)
            s_score = (30 if row['lg_bear'] else 0) + (10 if row['close'] < row['ema'] else 0)
            
            if l_score >= thresh:
                pos = 1; entry = row['close']; tp = entry + (row['atr']*tp_m); sl = entry - (row['atr']*sl_m)
            elif s_score >= thresh:
                pos = -1; entry = row['close']; tp = entry - (row['atr']*tp_m); sl = entry + (row['atr']*sl_m)
        
        wr = (wins/trades*100) if trades > 0 else 0
        return {"Symbol": self.symbol, "WR%": round(wr,1), "Trades": trades, "PnL%": round(pnl*100,2)}

symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
results = []
print("[MACHINE GUN] Testing 1m high-frequency strategy...")
for s in symbols:
    auditor = MachineGunAuditor(s)
    auditor.fetch()
    res = auditor.run()
    if res: results.append(res)

final_df = pd.DataFrame(results)
print("\n--- MACHINE GUN REPORT (1m TF) ---")
print(final_df.to_string(index=False))
print(f"\nTOTAL TRADES IN 24h: {final_df['Trades'].sum()}")
print(f"ESTIMATED WEEKLY PNL (20x Lev): {round(final_df['PnL%'].sum() * 7 * 20, 2)}%")
