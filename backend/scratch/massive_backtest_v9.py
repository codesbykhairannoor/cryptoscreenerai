import os
import sys
import pandas as pd
import time
from datetime import datetime
from forex_executor import ForexExecutor

class MassiveForexBacktester(ForexExecutor):
    def __init__(self, historical_data):
        super().__init__()
        self.all_data = historical_data
        self.current_idx = {tf: 0 for tf in historical_data}
        self._dxy_cache = {"change": 0.0, "trend": "NEUTRAL", "ts": 0}

    # Override methods to use historical data instead of API
    def get_live_price(self, symbol=None):
        df = self.all_data["1m"]
        idx = self.current_idx["1m"]
        row = df.iloc[idx]
        return {"bid": row['close'], "ask": row['close'], "spread_points": 2.5, "mid": row['close']}

    def get_candles(self, symbol=None, timeframe="30m", limit=100):
        df = self.all_data.get(timeframe)
        if df is None: return []
        idx = self.current_idx[timeframe]
        # Return slice up to current sync index
        start = max(0, idx - limit + 1)
        return df.iloc[start:idx+1].to_dict('records')

    def _get_dxy_context(self): return self._dxy_cache
    def _get_gold_orderbook(self): return {"obi": 0.0, "whale": "NORMAL"}
    def _get_gold_whale_trades(self): return "NORMAL"
    def get_account_information(self): return {"balance": 1000, "equity": 1000}

    def run_simulation(self, min_score, sl_p, tp_p):
        df_main = self.all_data["1m"]
        self.current_idx = {tf: 0 for tf in self.all_data}
        trades = []
        active_trade = None
        
        # Start from candle 200 to have warmup data
        for i in range(200, len(df_main)):
            current_time = df_main.iloc[i]['dt']
            # Sync all timeframes to current 1m time
            for tf in self.all_data:
                tf_df = self.all_data[tf]
                # Find the latest candle in TF that is before or at current_time
                sync_idx = tf_df[tf_df['dt'] <= current_time].index.max()
                self.current_idx[tf] = int(sync_idx) if not pd.isna(sync_idx) else 0
            
            if active_trade:
                high, low = df_main.iloc[i]['high'], df_main.iloc[i]['low']
                # Check exit
                if (active_trade['side'] == 'buy' and low <= active_trade['sl']) or \
                   (active_trade['side'] == 'sell' and high >= active_trade['sl']):
                    trades.append(-1)
                    active_trade = None
                elif (active_trade['side'] == 'buy' and high >= active_trade['tp']) or \
                     (active_trade['side'] == 'sell' and low <= active_trade['tp']):
                    trades.append(tp_p / sl_p) # RR based profit
                    active_trade = None
                continue

            # Check Entry
            ind = self._calc_indicators(timeframe="1m")
            if not ind or 'rsi' not in ind: continue
            
            # Simple simulation of _determine_side
            buy_s = self._score_setup(ind, "buy", 2.5)
            sell_s = self._score_setup(ind, "sell", 2.5)
            
            side = None
            if buy_s >= sell_s and buy_s >= min_score: side = "buy"
            elif sell_s > buy_s and sell_s >= min_score: side = "sell"
            
            if side:
                entry_p = df_main.iloc[i]['close']
                active_trade = {
                    'side': side,
                    'sl': entry_p - sl_p*0.1 if side == 'buy' else entry_p + sl_p*0.1,
                    'tp': entry_p + tp_p*0.1 if side == 'buy' else entry_p - tp_p*0.1
                }

        if not trades: return 0, 0
        wr = len([t for t in trades if t > 0]) / len(trades) * 100
        pnl = sum(trades)
        return pnl, len(trades), wr

def perform_massive_test():
    print("Loading data for XAUUSD (Massive Backtest)...")
    fx = ForexExecutor()
    all_data = {}
    for tf in ["1m", "5m", "30m", "1h", "4h"]:
        print(f"  Fetching {tf}...", flush=True)
        # Fetching 2000 candles for 1m (~33 hours), 1000 for others
        limit = 3000 if tf == "1m" else 1000
        data = fx.get_candles(timeframe=tf, limit=limit)
        df = pd.DataFrame(data)
        df['dt'] = pd.to_datetime(df['time'])
        all_data[tf] = df

    tester = MassiveForexBacktester(all_data)
    
    results = []
    print("\nStarting Grid Search (Score x SL x TP)...")
    for score_th in [40, 50, 60]:
        for sl in [15, 20, 25]:
            for tp in [30, 40, 50]:
                pnl, count, wr = tester.run_simulation(score_th, sl, tp)
                results.append({
                    'score': score_th, 'sl': sl, 'tp': tp,
                    'pnl': round(pnl, 2), 'trades': count, 'wr': round(wr, 1)
                })
                print(f"  Score:{score_th} SL:{sl} TP:{tp} -> PnL:{pnl:.1f} Trades:{count} WR:{wr:.1f}%", flush=True)

    df_res = pd.DataFrame(results).sort_values(by='pnl', ascending=False)
    print("\nTOP 5 BEST PARAMETERS:")
    print(df_res.head(5))

if __name__ == "__main__":
    perform_massive_test()
