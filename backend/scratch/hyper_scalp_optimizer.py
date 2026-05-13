import os
import sys
import pandas as pd
import time
from forex_executor import ForexExecutor

class HyperScalpOptimizer(ForexExecutor):
    def __init__(self, all_data):
        super().__init__()
        self.all_data = all_data
        self._dxy_cache = {"change": 0.0, "trend": "NEUTRAL", "ts": 0}

    def _get_dxy_context(self): return self._dxy_cache
    def _get_gold_orderbook(self): return {"obi": 0.0, "whale": "NORMAL"}
    def _get_gold_whale_trades(self): return "NORMAL"
    def get_account_information(self): return {"balance": 1000, "equity": 1000}

    def get_candles(self, symbol=None, timeframe="30m", limit=100):
        if timeframe not in self.all_data:
            # Fallback for HTF if not loaded
            return []
        df_tf = self.all_data[timeframe]
        idx = self.current_idx[timeframe]
        return df_tf.iloc[max(0, idx-limit+1):idx+1].to_dict('records')

    def run_simulation(self, min_score, sl_p, tp_p):
        df_main = self.all_data["1m"]
        self.current_idx = {tf: 0 for tf in self.all_data}
        trades = []
        active_trade = None
        
        # Start from 150 to ensure indicators have warmup
        for i in range(150, len(df_main)):
            current_time = df_main.iloc[i]['dt']
            for tf in self.all_data:
                tf_df = self.all_data[tf]
                # Find index in this timeframe that is <= current_time
                sync_idx = tf_df[tf_df['dt'] <= current_time].index.max()
                self.current_idx[tf] = int(sync_idx) if not pd.isna(sync_idx) else 0
            
            if active_trade:
                high, low = df_main.iloc[i]['high'], df_main.iloc[i]['low']
                if (active_trade['side'] == 'buy' and low <= active_trade['sl']) or \
                   (active_trade['side'] == 'sell' and high >= active_trade['sl']):
                    trades.append(-1)
                    active_trade = None
                elif (active_trade['side'] == 'buy' and high >= active_trade['tp']) or \
                     (active_trade['side'] == 'sell' and low <= active_trade['tp']):
                    trades.append(tp_p / sl_p)
                    active_trade = None
                continue

            self._last_known_price = df_main.iloc[i]['close']
            self._last_known_spread = 2.5
            ind = self._calc_indicators(timeframe="1m")
            if not ind or 'rsi' not in ind: continue
            
            buy_s = self._score_setup(ind, "buy", 2.5)
            sell_s = self._score_setup(ind, "sell", 2.5)
            
            side = None
            if buy_s >= sell_s and buy_s >= min_score: side = "buy"; score = buy_s
            elif sell_s > buy_s and sell_s >= min_score: side = "sell"; score = sell_s
                
            if side:
                vel = ind.get("velocity", 0)
                vel_dir = ind.get("velocity_direction", "")
                if vel > 0.001 and vel_dir == side.upper():
                    entry_p = df_main.iloc[i]['close']
                    active_trade = {
                        'side': side,
                        'sl': entry_p - sl_p*0.1 if side == 'buy' else entry_p + sl_p*0.1,
                        'tp': entry_p + tp_p*0.1 if side == 'buy' else entry_p - tp_p*0.1
                    }
                    print(f"    [TRADE] {side.upper()} @ {entry_p} Score:{score:.1f} Vel:{vel:.4f}", flush=True)

        return sum(trades), len(trades)

def optimize_hyper_scalp():
    print("Loading data for Hyper-Scalp (1m focus)...")
    fx = ForexExecutor()
    all_data = {}
    for tf in ["1m", "5m", "30m", "1h", "4h"]:
        print(f"  Fetching {tf}...", flush=True)
        data = fx.get_candles(timeframe=tf, limit=500)
        df = pd.DataFrame(data)
        df['dt'] = pd.to_datetime(df['time'])
        all_data[tf] = df

    optimizer = HyperScalpOptimizer(all_data)
    results = []
    
    # Fast Scalp Grid
    scores = [40, 50, 60]
    sls = [10, 15, 25]
    tps = [20, 35, 50]
    
    print("Starting Hyper-Scalp Grid Search...", flush=True)
    for s in scores:
        for sl in sls:
            for tp in tps:
                print(f"  Testing S:{s} SL:{sl} TP:{tp}...", end="", flush=True)
                pnl, count = optimizer.run_simulation(s, sl, tp)
                print(f" Done. Trades: {count}, PnL: {pnl:.2f}", flush=True)
                results.append({'score': s, 'sl': sl, 'tp': tp, 'pnl': pnl, 'count': count})
    
    df_res = pd.DataFrame(results).sort_values(by='pnl', ascending=False)
    print("\nTOP HYPER-SCALP STRATEGIES:")
    print(df_res.head(5))
    
    if not df_res.empty:
        best = df_res.iloc[0]
        print(f"\nBEST FAST CONFIG: Score {best['score']}, SL {best['sl']}, TP {best['tp']}")
        print(f"PnL: {best['pnl']} units | Total Trades: {best['count']}")

if __name__ == "__main__":
    optimize_hyper_scalp()
