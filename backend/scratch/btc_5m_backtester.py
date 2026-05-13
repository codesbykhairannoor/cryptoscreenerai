import pandas as pd
import numpy as np
import requests
import time

class BTCBacktester:
    def __init__(self, symbol="BTCUSDT"):
        self.symbol = symbol
        self.df = None

    def fetch_data(self):
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {"symbol": self.symbol, "interval": "5m", "limit": 1500}
        r = requests.get(url, params=params, verify=False)
        data = r.json()
        df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'cts', 'qvol', 'tr', 'tbb', 'tbq', 'i'])
        df[['open', 'high', 'low', 'close', 'vol']] = df[['open', 'high', 'low', 'close', 'vol']].astype(float)
        self.df = df

    def run_test(self):
        df = self.df.copy()
        df['ema_200'] = df['close'].ewm(span=200).mean()
        df['atr'] = self._calc_atr(df)
        df['low_min'] = df['low'].rolling(20).min()
        df['high_max'] = df['high'].rolling(20).max()
        
        df['s_lg_bull'] = np.where((df['low'] < df['low_min'].shift(1)) & (df['close'] > df['low_min'].shift(1)), 25, 0)
        df['s_lg_bear'] = np.where((df['high'] > df['high_max'].shift(1)) & (df['close'] < df['high_max'].shift(1)), 25, 0)
        df['s_fvg_bull'] = np.where((df['low'] > df['high'].shift(2)), 15, 0)
        df['s_fvg_bear'] = np.where((df['high'] < df['low'].shift(2)), 15, 0)
        df['s_trend_bull'] = np.where(df['close'] > df['ema_200'], 10, 0)
        df['s_trend_bear'] = np.where(df['close'] < df['ema_200'], 10, 0)

        results = []
        for thresh in [30, 35, 40]:
            for tp_m in [1.0, 1.5, 2.0]:
                for sl_m in [1.5, 2.0]:
                    res = self._simulate(df, thresh, tp_m, sl_m)
                    results.append(res)
        
        final = pd.DataFrame(results).sort_values(by='WR', ascending=False)
        print(f"\n--- BTC 5M SCALPING REPORT ---")
        print(final.to_string(index=False))

    def _simulate(self, df, threshold, tp_m, sl_m):
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
            l_score = row['s_lg_bull'] + row['s_fvg_bull'] + row['s_trend_bull']
            s_score = row['s_lg_bear'] + row['s_fvg_bear'] + row['s_trend_bear']
            if l_score >= threshold:
                pos = 1; entry = row['close']; tp = entry + (row['atr'] * tp_m); sl = entry - (row['atr'] * sl_m)
            elif s_score >= threshold:
                pos = -1; entry = row['close']; tp = entry - (row['atr'] * tp_m); sl = entry + (row['atr'] * sl_m)
        wr = (wins/trades*100) if trades > 0 else 0
        return {"Thresh": threshold, "TP": tp_m, "SL": sl_m, "WR": round(wr,1), "Trades": trades, "PnL%": round(pnl*100,1)}

    def _calc_atr(self, df, period=14):
        tr = np.maximum(df['high'] - df['low'], np.maximum(np.abs(df['high'] - df['close'].shift()), np.abs(df['low'] - df['close'].shift())))
        return tr.rolling(window=period).mean()

bt = BTCBacktester()
bt.fetch_data()
bt.run_test()
