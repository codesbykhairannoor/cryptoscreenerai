import os
import sys
import pandas as pd
from forex_executor import ForexExecutor

class DebugScalp(ForexExecutor):
    def __init__(self, data):
        super().__init__()
        self.all_data = data
        self.current_idx = {tf: 0 for tf in data}
    def get_candles(self, symbol=None, timeframe="30m", limit=100):
        df = self.all_data[timeframe]
        idx = self.current_idx[timeframe]
        return df.iloc[max(0, idx-limit+1):idx+1].to_dict('records')

def debug():
    fx = ForexExecutor()
    data = {}
    for tf in ["1m", "5m", "30m", "1h", "4h"]:
        print(f"Fetch {tf}...")
        c = fx.get_candles(timeframe=tf, limit=500)
        df = pd.DataFrame(c)
        df['dt'] = pd.to_datetime(df['time'])
        data[tf] = df
    
    dbg = DebugScalp(data)
    # Set current index to the middle of the data
    for tf in data:
        dbg.current_idx[tf] = 400
        
    print("\nRunning _calc_indicators(1m)...")
    ind = dbg._calc_indicators(timeframe="1m")
    print(f"Result Keys: {list(ind.keys())}")
    print(f"RSI: {ind.get('rsi')}")
    print(f"Velocity: {ind.get('velocity')} ({ind.get('velocity_direction')})")
    
    print("\nRunning Score Check (Buy)...")
    score = dbg._score_setup(ind, "buy", 2.5)
    print(f"Buy Score: {score}")

if __name__ == "__main__":
    debug()
