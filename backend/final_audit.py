import pandas as pd
import numpy as np
import requests
import warnings
warnings.filterwarnings("ignore")

class HonestAuditor:
    def __init__(self, symbol):
        self.symbol = symbol
        self.df = None

    def fetch(self):
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={self.symbol}&interval=15m&limit=1000"
        try:
            r = requests.get(url, verify=False, timeout=10)
            data = r.json()
            df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'cts', 'qvol', 'tr', 'tbb', 'tbq', 'i'])
            df[['open', 'high', 'low', 'close', 'vol']] = df[['open', 'high', 'low', 'close', 'vol']].astype(float)
            self.df = df
        except: pass

    def run(self):
        if self.df is None: return None
        df = self.df.copy()
        df['ema'] = df['close'].ewm(span=200).mean()
        tr = np.maximum(df['high']-df['low'], np.maximum(np.abs(df['high']-df['close'].shift()), np.abs(df['low']-df['close'].shift())))
        df['atr'] = tr.rolling(14).mean()
        df['l_min'] = df['low'].rolling(20).min(); df['h_max'] = df['high'].rolling(20).max()
        df['lg_bull'] = (df['low'] < df['l_min'].shift(1)) & (df['close'] > df['l_min'].shift(1))
        df['lg_bear'] = (df['high'] > df['h_max'].shift(1)) & (df['close'] < df['h_max'].shift(1))
        df['fvg_bull'] = (df['low'] > df['high'].shift(2)); df['fvg_bear'] = (df['high'] < df['low'].shift(2))
        
        wins=0; trades=0; pnl=0; pos=0; entry=0; tp=0; sl=0
        tp_m=1.0; sl_m=2.0; thresh=30
        
        for i in range(50, len(df)):
            row = df.iloc[i]
            if pos != 0:
                if pos == 1:
                    if row['high'] >= tp: wins += 1; trades += 1; pnl += (tp-entry)/entry; pos = 0
                    elif row['low'] <= sl: trades += 1; pnl -= (entry-sl)/entry; pos = 0
                elif pos == -1:
                    if row['low'] <= tp: wins += 1; trades += 1; pnl += (entry-tp)/entry; pos = 0
                    elif row['high'] >= sl: trades += 1; pnl -= (sl-entry)/entry; pos = 0
                continue
            
            # Sesuai Engine v26.37
            l_score = (25 if row['lg_bull'] else 0) + (15 if row['fvg_bull'] else 0) + (10 if row['close'] > row['ema'] else 0)
            s_score = (25 if row['lg_bear'] else 0) + (15 if row['fvg_bear'] else 0) + (10 if row['close'] < row['ema'] else 0)
            
            if l_score >= thresh:
                pos = 1; entry = row['close']; tp = entry + (row['atr']*tp_m); sl = entry - (row['atr']*sl_m)
            elif s_score >= thresh:
                pos = -1; entry = row['close']; tp = entry - (row['atr']*tp_m); sl = entry + (row['atr']*sl_m)
        
        wr = (wins/trades*100) if trades > 0 else 0
        return {"Symbol": self.symbol, "WR%": round(wr,1), "Trades": trades, "PnL%": round(pnl*100,2)}

symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT", "DOGEUSDT"]
results = []
print("[AUDIT] Running final performance check...")
for s in symbols:
    a = HonestAuditor(s)
    a.fetch()
    res = a.run()
    if res: results.append(res)

print("\n" + "="*50)
print("FINAL HONEST STRATEGY REPORT (v26.37)")
print("="*50)
print(pd.DataFrame(results).to_string(index=False))
print("="*50)
print(f"OVERALL AVG WIN RATE: {round(pd.DataFrame(results)['WR%'].mean(), 2)}%")
