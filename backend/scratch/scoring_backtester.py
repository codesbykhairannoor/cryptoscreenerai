import pandas as pd
import numpy as np
import requests
import time

class ScoringBacktester:
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

    def run_scoring_test(self):
        df = self.df.copy()
        df['ema_200'] = df['close'].ewm(span=200).mean()
        df['atr'] = self._calc_atr(df)
        df['low_min'] = df['low'].rolling(20).min()
        df['high_max'] = df['high'].rolling(20).max()
        df['rsi'] = self._calc_rsi(df['close'])
        
        # Scoring Components
        df['score_lg_bull'] = np.where((df['low'] < df['low_min'].shift(1)) & (df['close'] > df['low_min'].shift(1)), 15, 0)
        df['score_lg_bear'] = np.where((df['high'] > df['high_max'].shift(1)) & (df['close'] < df['high_max'].shift(1)), 15, 0)
        df['score_fvg_bull'] = np.where((df['low'] > df['high'].shift(2)), 10, 0)
        df['score_fvg_bear'] = np.where((df['high'] < df['low'].shift(2)), 10, 0)
        df['score_trend_bull'] = np.where(df['close'] > df['ema_200'], 10, 0)
        df['score_trend_bear'] = np.where(df['close'] < df['ema_200'], 10, 0)
        df['score_rsi_bull'] = np.where(df['rsi'] < 35, 15, 0)
        df['score_rsi_bear'] = np.where(df['rsi'] > 65, 15, 0)

        print(f"\n--- INSTITUTIONAL SCORING REPORT: {self.symbol} ---", flush=True)
        
        for threshold in [20, 30, 40, 50]:
            self._simulate_scoring(df, threshold)

    def _simulate_scoring(self, df, threshold):
        wins = 0; trades = 0; pnl = 0; pos = 0; entry = 0; tp = 0; sl = 0
        tp_m = 4.5; sl_m = 1.5
        
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
            
            # TOTAL SCORE CALCULATION
            long_score = row['score_lg_bull'] + row['score_fvg_bull'] + row['score_trend_bull'] + row['score_rsi_bull']
            short_score = row['score_lg_bear'] + row['score_fvg_bear'] + row['score_trend_bear'] + row['score_rsi_bear']
            
            if long_score >= threshold:
                pos = 1; entry = row['close']; tp = entry + (row['atr'] * tp_m); sl = entry - (row['atr'] * sl_m)
            elif short_score >= threshold:
                pos = -1; entry = row['close']; tp = entry - (row['atr'] * tp_m); sl = entry + (row['atr'] * sl_m)
        
        wr = (wins/trades*100) if trades > 0 else 0
        print(f"[Threshold: {threshold}+] WR: {round(wr,1)}% | Trades: {trades} | PnL: {round(pnl*100,1)}%", flush=True)

    def _calc_atr(self, df, period=14):
        tr = np.maximum(df['high'] - df['low'], np.maximum(np.abs(df['high'] - df['close'].shift()), np.abs(df['low'] - df['close'].shift())))
        return tr.rolling(window=period).mean()

    def _calc_rsi(self, series, period=14):
        delta = series.diff(); gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        return 100 - (100 / (1 + (gain / loss)))

for s in ["BTCUSDT", "SOLUSDT", "ETHUSDT"]:
    bt = ScoringBacktester(symbol=s)
    bt.fetch_data()
    bt.run_scoring_test()
