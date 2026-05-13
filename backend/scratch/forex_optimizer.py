import os
import sys
import pandas as pd
import time
from forex_executor import ForexExecutor

class StrategyOptimizer(ForexExecutor):
    def __init__(self, all_data):
        super().__init__()
        self.all_data = all_data
        self._dxy_cache = {"change": 0.0, "trend": "NEUTRAL", "ts": 0}

    def _get_dxy_context(self): return self._dxy_cache
    def _get_gold_orderbook(self): return {"obi": 0.0, "whale": "NORMAL"}
    def _get_gold_whale_trades(self): return "NORMAL"
    def get_account_information(self): return {"balance": 1000, "equity": 1000}

    def get_candles(self, symbol=None, timeframe="30m", limit=100):
        df_tf = self.all_data[timeframe]
        idx = self.current_idx[timeframe]
        return df_tf.iloc[max(0, idx-limit+1):idx+1].to_dict('records')

    def _determine_side(self, ind, spread_points):
        # Silently run scoring for speed
        buy_score  = self._score_setup(ind, "buy",  spread_points)
        sell_score = self._score_setup(ind, "sell", spread_points)
        
        in_demand = ind.get("in_demand", False)
        in_supply = ind.get("in_supply", False)
        
        if buy_score >= sell_score and buy_score >= 50:
            if not in_supply: return "buy", buy_score, 1
        elif sell_score > buy_score and sell_score >= 50:
            if not in_demand: return "sell", sell_score, 1
        return None, 0, 0

    def run_simulation(self, min_score, sl_p, tp_p, mtf_min):
        df_main = self.all_data["30m"]
        self.current_idx = {tf: 0 for tf in self.all_data}
        trades = []
        active_trade = None
        for i in range(150, len(df_main)):
            current_time = df_main.iloc[i]['dt']
            for tf in self.all_data:
                tf_df = self.all_data[tf]
                sync_idx = tf_df[tf_df['dt'] <= current_time].index.max()
                self.current_idx[tf] = sync_idx if not pd.isna(sync_idx) else 0
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
            ind = self._calc_indicators()
            if not ind: continue
            side, score, _ = self._determine_side(ind, self._last_known_spread)
            if side and score >= min_score:
                mtf = self._get_mtf_confluence(side)
                if mtf["aligned_count"] >= mtf_min:
                    entry_p = df_main.iloc[i]['close']
                    sl = entry_p - sl_p*0.1 if side == 'buy' else entry_p + sl_p*0.1
                    tp = entry_p + tp_p*0.1 if side == 'buy' else entry_p - tp_p*0.1
                    active_trade = {'side': side, 'sl': sl, 'tp': tp}
        return sum(trades), len(trades)

def optimize():
    print("Loading data...")
    fx = ForexExecutor()
    all_data = {}
    for tf in ["30m", "1h", "4h"]:
        data = fx.get_candles(timeframe=tf, limit=1000)
        df = pd.DataFrame(data)
        df['dt'] = pd.to_datetime(df['time'])
        all_data[tf] = df
    optimizer = StrategyOptimizer(all_data)
    results = []
    scores = [65, 75]
    sls = [20, 35, 50]
    tps = [40, 70, 100]
    mtfs = [1, 2]
    print(f"Starting Grid Search...")
    for s in scores:
        for sl in sls:
            for tp in tps:
                for m in mtfs:
                    pnl, count = optimizer.run_simulation(s, sl, tp, m)
                    results.append({'score': s, 'sl': sl, 'tp': tp, 'mtf': m, 'pnl': pnl, 'count': count})
    df_res = pd.DataFrame(results).sort_values(by='pnl', ascending=False)
    print("\nTOP 5 STRATEGIES:")
    print(df_res.head(5))
    
    best = df_res.iloc[0]
    print(f"\nBEST CONFIGURATION: Score >= {best['score']}, SL: {best['sl']}, TP: {best['tp']}, MTF >= {best['mtf']}")
    print(f"Projected PnL: {best['pnl']} units over {best['count']} trades.")

if __name__ == "__main__":
    optimize()
