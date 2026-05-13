import os
import sys
import pandas as pd
from forex_executor import ForexExecutor

class QuickBacktest(ForexExecutor):
    def __init__(self, data):
        super().__init__()
        self.all_data = data
        self.current_idx = {tf: 0 for tf in data}
        self._dxy_cache = {"change": 0.0, "trend": "NEUTRAL", "ts": 0}

    def get_candles(self, symbol=None, timeframe="30m", limit=100):
        df = self.all_data.get(timeframe)
        if df is None: return []
        idx = self.current_idx[timeframe]
        return df.iloc[max(0, idx-limit+1):idx+1].to_dict('records')

    def run(self):
        df_main = self.all_data["1m"]
        self.current_idx = {tf: 0 for tf in self.all_data}
        trades = []
        active_trade = None
        
        # Testing parameters from the final production code
        min_score = 60
        tp_p = 40
        sl_p = 20
        
        print(f"Running Quick Backtest on last {len(df_main)} minutes...")
        
        for i in range(100, len(df_main)):
            current_time = df_main.iloc[i]['dt']
            for tf in self.all_data:
                tf_df = self.all_data[tf]
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
                    trades.append(2.0) # RR 2:1
                    active_trade = None
                continue

            ind = self._calc_indicators(timeframe="1m")
            if not ind or 'rsi' not in ind: continue
            
            buy_s = self._score_setup(ind, "buy", 2.5)
            sell_s = self._score_setup(ind, "sell", 2.5)
            
            side = None
            if buy_s >= sell_s and buy_s >= min_score: side = "buy"
            elif sell_s > buy_s and sell_s >= min_score: side = "sell"
            
            if side:
                # MTF Confluence check (Strict)
                mtf = self._get_mtf_confluence(side)
                if mtf["aligned_count"] >= 2:
                    entry_p = df_main.iloc[i]['close']
                    active_trade = {
                        'side': side,
                        'sl': entry_p - sl_p*0.1 if side == 'buy' else entry_p + sl_p*0.1,
                        'tp': entry_p + tp_p*0.1 if side == 'buy' else entry_p - tp_p*0.1
                    }

        total = len(trades)
        wins = len([t for t in trades if t > 0])
        wr = (wins/total*100) if total > 0 else 0
        pnl = sum(trades)
        
        print("\n" + "="*40)
        print(f"QUICK BACKTEST SUMMARY (1m Mode)")
        print(f"Total Trades: {total}")
        print(f"Wins:         {wins}")
        print(f"Losses:       {total - wins}")
        print(f"Win Rate:     {wr:.2f}%")
        print(f"Net PnL:      {pnl:.2f} units")
        print("="*40)

if __name__ == "__main__":
    fx = ForexExecutor()
    data = {}
    for tf in ["1m", "5m", "15m", "30m", "1h", "4h"]:
        print(f"Fetch {tf}...")
        c = fx.get_candles(timeframe=tf, limit=500)
        df = pd.DataFrame(c)
        df['dt'] = pd.to_datetime(df['time'])
        data[tf] = df
    
    qb = QuickBacktest(data)
    qb.run()
