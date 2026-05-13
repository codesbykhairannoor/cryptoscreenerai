import pandas as pd
import numpy as np
import requests
import time

class RuleBacktester:
    def __init__(self, symbol="BTCUSDT"):
        self.symbol = symbol
        self.df = None

    def fetch_data(self):
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {"symbol": self.symbol, "interval": "15m", "limit": 1500}
        r = requests.get(url, params=params, verify=False)
        data = r.json()
        df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'cts', 'qvol', 'tr', 'tbb', 'tbq', 'i'])
        df[['open', 'high', 'low', 'close', 'vol']] = df[['open', 'high', 'low', 'close', 'vol']].astype(float)
        self.df = df

    def run_rule_test(self):
        df = self.df.copy()
        df['ema_200'] = df['close'].ewm(span=200).mean()
        df['atr'] = self._calc_atr(df)
        df['low_min'] = df['low'].rolling(20).min()
        df['high_max'] = df['high'].rolling(20).max()
        df['liq_grab_bull'] = (df['low'] < df['low_min'].shift(1)) & (df['close'] > df['low_min'].shift(1))
        df['liq_grab_bear'] = (df['high'] > df['high_max'].shift(1)) & (df['close'] < df['high_max'].shift(1))
        df['fvg_bull'] = (df['low'] > df['high'].shift(2))
        df['fvg_bear'] = (df['high'] < df['low'].shift(2))

        rules = [
            {"name": "STRICT (LG+FVG+EMA)", "buy": (df['liq_grab_bull'] & df['fvg_bull'] & (df['close'] > df['ema_200'])), "sell": (df['liq_grab_bear'] & df['fvg_bear'] & (df['close'] < df['ema_200']))},
            {"name": "AGGR (LG+FVG)", "buy": (df['liq_grab_bull'] & df['fvg_bull']), "sell": (df['liq_grab_bear'] & df['fvg_bear'])},
            {"name": "FAST (LG ONLY)", "buy": df['liq_grab_bull'], "sell": df['liq_grab_bear']},
            {"name": "SCALP (FVG ONLY)", "buy": df['fvg_bull'], "sell": df['fvg_bear']}
        ]

        print(f"\n--- OPTIMIZATION REPORT: {self.symbol} ---", flush=True)
        for r in rules:
            self._simulate(df, r)

    def _simulate(self, df, rule):
        wins = 0; trades = 0; pnl = 0; pos = 0; entry = 0; tp = 0; sl = 0
        tp_m = 3.5; sl_m = 1.5
        
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
            
            if rule['buy'].iloc[i]:
                pos = 1; entry = row['close']; tp = entry + (row['atr'] * tp_m); sl = entry - (row['atr'] * sl_m)
            elif rule['sell'].iloc[i]:
                pos = -1; entry = row['close']; tp = entry - (row['atr'] * tp_m); sl = entry + (row['atr'] * sl_m)
        
        wr = (wins/trades*100) if trades > 0 else 0
        print(f"[{rule['name']}] WR: {round(wr,1)}% | Trades: {trades} | PnL: {round(pnl*100,1)}%", flush=True)

    def _calc_atr(self, df, period=14):
        tr = np.maximum(df['high'] - df['low'], np.maximum(np.abs(df['high'] - df['close'].shift()), np.abs(df['low'] - df['close'].shift())))
        return tr.rolling(window=period).mean()

for s in ["BTCUSDT", "SOLUSDT", "ETHUSDT"]:
    bt = RuleBacktester(symbol=s)
    bt.fetch_data()
    bt.run_rule_test()
