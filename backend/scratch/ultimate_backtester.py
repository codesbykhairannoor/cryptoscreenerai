import pandas as pd
import numpy as np
import requests
import time

class UltimateBacktester:
    def __init__(self, symbol="BTCUSDT", interval="15m", days=30):
        self.symbol = symbol
        self.interval = interval
        self.days = days
        self.df = None

    def fetch_data(self):
        """Ambil data masif dari Binance (VPN AKTIF)"""
        print(f"[DATA] Fetching {self.days} days of {self.interval} data for {self.symbol}...")
        url = "https://fapi.binance.com/fapi/v1/klines"
        limit = 1000
        all_candles = []
        end_time = int(time.time() * 1000)
        
        for _ in range(5): # Fetch up to 5,000 candles
            params = {"symbol": self.symbol, "interval": self.interval, "limit": limit, "endTime": end_time}
            try:
                r = requests.get(url, params=params, verify=False)
                data = r.json()
                if not data or len(data) == 0: break
                all_candles = data + all_candles
                end_time = data[0][0] - 1
            except Exception as e:
                print(f"[ERROR] Fetch failed: {e}")
                break
            
        df = pd.DataFrame(all_candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'cts', 'qvol', 'tr', 'tbb', 'tbq', 'i'])
        df[['open', 'high', 'low', 'close', 'vol']] = df[['open', 'high', 'low', 'close', 'vol']].astype(float)
        self.df = df
        print(f"[DATA] Total candles loaded: {len(self.df)}")

    def run_simulation(self, combinations):
        df = self.df.copy()
        df['ema_200'] = df['close'].ewm(span=200).mean()
        df['rsi'] = self._calc_rsi(df['close'])
        df['atr'] = self._calc_atr(df)
        df['is_fvg_bull'] = (df['low'] > df['high'].shift(2))
        df['is_fvg_bear'] = (df['high'] < df['low'].shift(2))

        results = []
        for p in combinations:
            perf = self._test_strategy(df, p)
            results.append(perf)
            
        return pd.DataFrame(results).sort_values(by='win_rate', ascending=False)

    def _test_strategy(self, df, p):
        pos = 0; entry_p = 0; tp_p = 0; sl_p = 0; trades = 0; wins = 0; total_pnl = 0
        for i in range(50, len(df)):
            row = df.iloc[i]
            if pos != 0:
                if pos == 1:
                    if row['high'] >= tp_p: wins += 1; trades += 1; total_pnl += (tp_p-entry_p)/entry_p; pos = 0
                    elif row['low'] <= sl_p: trades += 1; total_pnl -= (entry_p-sl_p)/entry_p; pos = 0
                elif pos == -1:
                    if row['low'] <= tp_p: wins += 1; trades += 1; total_pnl += (entry_p-tp_p)/entry_p; pos = 0
                    elif row['high'] >= sl_p: trades += 1; total_pnl -= (sl_p-entry_p)/entry_p; pos = 0
                continue
            
            # Strategi: FVG + Trend + RSI Filter
            if row['is_fvg_bull'] and row['close'] > row['ema_200'] and row['rsi'] < p['rsi_max']:
                pos = 1; entry_p = row['close']
                tp_p = entry_p + (row['atr'] * p['tp_mult']); sl_p = entry_p - (row['atr'] * p['sl_mult'])
            elif row['is_fvg_bear'] and row['close'] < row['ema_200'] and row['rsi'] > p['rsi_min']:
                pos = -1; entry_p = row['close']
                tp_p = entry_p - (row['atr'] * p['tp_mult']); sl_p = entry_p + (row['atr'] * p['sl_mult'])

        wr = (wins / trades * 100) if trades > 0 else 0
        return {"params": f"TP:{p['tp_mult']} SL:{p['sl_mult']}", "trades": trades, "win_rate": round(wr, 1), "pnl_pct": round(total_pnl*100, 2)}

    def _calc_rsi(self, series, period=14):
        delta = series.diff(); gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        return 100 - (100 / (1 + (gain / loss)))

    def _calc_atr(self, df, period=14):
        tr = np.maximum(df['high'] - df['low'], np.maximum(np.abs(df['high'] - df['close'].shift()), np.abs(df['low'] - df['close'].shift())))
        return tr.rolling(window=period).mean()

# GENERATE JUTAAN SCENARIOS
scenarios = []
for tp in [1.5, 2.0, 3.0, 4.5]:
    for sl in [1.0, 1.5, 2.0, 2.5]:
        scenarios.append({"rsi_max": 65, "rsi_min": 35, "tp_mult": tp, "sl_mult": sl})

print("\n[BACKTEST] Starting simulation for BTC, ETH, SOL...")
for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    tester = UltimateBacktester(symbol=sym, interval="15m", days=30)
    tester.fetch_data()
    if tester.df is not None:
        report = tester.run_simulation(scenarios)
        print(f"\nBEST STRATEGIES FOR {sym}:")
        print(report.head(5).to_string(index=False))
