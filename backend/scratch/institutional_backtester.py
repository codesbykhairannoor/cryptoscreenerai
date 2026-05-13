import pandas as pd
import numpy as np
import requests
import time

class InstitutionalBacktester:
    def __init__(self, symbol="BTCUSDT", interval="15m"):
        self.symbol = symbol
        self.interval = interval
        self.df = None

    def fetch_data(self):
        print(f"[DATA] Fetching {self.symbol}...", flush=True)
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {"symbol": self.symbol, "interval": self.interval, "limit": 1500}
        try:
            r = requests.get(url, params=params, verify=False)
            if r.status_code != 200: return
            data = r.json()
            df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'cts', 'qvol', 'tr', 'tbb', 'tbq', 'i'])
            df[['open', 'high', 'low', 'close', 'vol']] = df[['open', 'high', 'low', 'close', 'vol']].astype(float)
            self.df = df
        except Exception as e: print(f"[ERROR] {e}", flush=True)

    def _calc_atr(self, df, period=14):
        tr = np.maximum(df['high'] - df['low'], np.maximum(np.abs(df['high'] - df['close'].shift()), np.abs(df['low'] - df['close'].shift())))
        return tr.rolling(window=period).mean()

    def run_simulation(self):
        if self.df is None or len(self.df) < 100: return
        df = self.df.copy()
        df['ema_200'] = df['close'].ewm(span=200).mean()
        df['atr'] = self._calc_atr(df)
        df['high_max'] = df['high'].rolling(20).max()
        df['low_min'] = df['low'].rolling(20).min()
        df['liq_grab_bull'] = (df['low'] < df['low_min'].shift(1)) & (df['close'] > df['low_min'].shift(1))
        df['liq_grab_bear'] = (df['high'] > df['high_max'].shift(1)) & (df['close'] < df['high_max'].shift(1))
        df['fvg_bull'] = (df['low'] > df['high'].shift(2))
        df['fvg_bear'] = (df['high'] < df['low'].shift(2))

        best_wr = 0; best_p = ""
        for tp_m in [2.0, 3.5, 5.0]:
            for sl_m in [1.0, 1.5, 2.0]:
                wins = 0; trades = 0; pnl = 0; pos = 0; entry = 0; tp = 0; sl = 0
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
                    if row['liq_grab_bull'] and row['fvg_bull'] and row['close'] > row['ema_200']:
                        pos = 1; entry = row['close']; tp = entry + (row['atr'] * tp_m); sl = entry - (row['atr'] * sl_m)
                    elif row['liq_grab_bear'] and row['fvg_bear'] and row['close'] < row['ema_200']:
                        pos = -1; entry = row['close']; tp = entry - (row['atr'] * tp_m); sl = entry + (row['atr'] * sl_m)
                wr = (wins/trades*100) if trades > 0 else 0
                if wr > best_wr:
                    best_wr = wr; best_p = f"TP:{tp_m} SL:{sl_m} | Trades:{trades} | PnL:{round(pnl*100,1)}%"
        print(f"RESULTS {self.symbol}: Best WR: {round(best_wr,1)}% ({best_p})", flush=True)

print("[BACKTEST START]", flush=True)
for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    bt = InstitutionalBacktester(symbol=s)
    bt.fetch_data()
    bt.run_simulation()
