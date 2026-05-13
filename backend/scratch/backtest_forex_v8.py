import os
import sys
import time
import datetime
import pandas as pd
from forex_executor import ForexExecutor

class ForexBacktester(ForexExecutor):
    def __init__(self):
        super().__init__()
        self.history = []
        self.trades = []
        self.current_candles = []
        self._dxy_cache = {"change": 0.0, "trend": "NEUTRAL", "ts": 0}

    def _get_dxy_context(self):
        return self._dxy_cache

    def _get_gold_orderbook(self):
        return {"obi": 0.0, "whale": "NORMAL"}

    def _get_gold_whale_trades(self):
        return "NORMAL"
        
    def get_account_information(self):
        return {"balance": 1000, "equity": 1000}
        
    def get_candles(self, symbol=None, timeframe="30m", limit=100):
        # Override to use the full history loaded for backtest
        # Find the candles in self.all_data that are before the "current" simulation time
        if not hasattr(self, 'all_data'):
            return super().get_candles(symbol, timeframe, limit)
        
        # Filter all_data based on timeframe
        df_tf = self.all_data[timeframe]
        # Return the last 'limit' candles from the slice currently being processed
        idx = self.current_idx[timeframe]
        return df_tf.iloc[max(0, idx-limit+1):idx+1].to_dict('records')

    def run_backtest(self, limit=1000):
        print(f"=== STARTING FOREX BACKTEST (XAUUSD) ===")
        print(f"Fetching {limit} candles for analysis...")
        
        # Load data for multiple timeframes to support confluence check
        self.all_data = {}
        for tf in ["1m", "5m", "15m", "30m", "1h", "4h"]:
            print(f"  Fetching {tf} candles...", flush=True)
            data = super().get_candles(timeframe=tf, limit=limit)
            print(f"    Done. Fetched {len(data)} candles.", flush=True)
            self.all_data[tf] = pd.DataFrame(data)
            # Convert time to datetime for syncing
            self.all_data[tf]['dt'] = pd.to_datetime(self.all_data[tf]['time'])
            
        print("Data loaded. Syncing timeframes...", flush=True)
        
        # We simulate based on 30m candles as the main signal
        main_tf = "30m"
        df_main = self.all_data[main_tf]
        
        self.current_idx = {tf: 0 for tf in self.all_data}
        self.trades = []
        active_trade = None
        
        print(f"Simulating {len(df_main)-100} iterations...", flush=True)
        # Start from candle 100 to have enough history for indicators
        for i in range(100, len(df_main)):
            if i % 50 == 0:
                print(f"  Iteration {i}/{len(df_main)}...", flush=True)
            current_time = df_main.iloc[i]['dt']
            # Mock time.time() for the engine to use simulated time
            sim_ts = current_time.timestamp()
            
            # 0. Mock DXY context to avoid network calls (return neutral for now)
            self._dxy_cache = {"change": 0.0, "trend": "NEUTRAL", "ts": sim_ts}
            
            # Sync other timeframes to this time
            for tf in self.all_data:
                # Find the last candle in this TF that is <= current_time
                tf_df = self.all_data[tf]
                sync_idx = tf_df[tf_df['dt'] <= current_time].index.max()
                self.current_idx[tf] = sync_idx if not pd.isna(sync_idx) else 0
            
            # 1. Manage Active Trade
            if active_trade:
                high = df_main.iloc[i]['high']
                low = df_main.iloc[i]['low']
                close = df_main.iloc[i]['close']
                
                # Check SL
                if (active_trade['side'] == 'buy' and low <= active_trade['sl']) or \
                   (active_trade['side'] == 'sell' and high >= active_trade['sl']):
                    active_trade['status'] = 'LOSS'
                    active_trade['exit_price'] = active_trade['sl']
                    active_trade['exit_time'] = current_time
                    self.trades.append(active_trade)
                    active_trade = None
                    continue
                    
                # Check TP
                if (active_trade['side'] == 'buy' and high >= active_trade['tp']) or \
                   (active_trade['side'] == 'sell' and low <= active_trade['tp']):
                    active_trade['status'] = 'WIN'
                    active_trade['exit_price'] = active_trade['tp']
                    active_trade['exit_time'] = current_time
                    self.trades.append(active_trade)
                    active_trade = None
                    continue

            # 2. Look for Entry (if no active trade)
            if not active_trade:
                # Mock the environment
                self._last_known_price = df_main.iloc[i]['close']
                self._last_known_spread = 2.5 # Assumption
                
                ind = self._calc_indicators()
                if not ind: continue
                
                side, score, _ = self._determine_side(ind, self._last_known_spread)
                
                if side:
                    # Run additional filters as in monitor_forex_market
                    adx = self._calc_adx_forex()
                    mtf = self._get_mtf_confluence(side)
                    e5m = self._get_5m_entry_quality()
                    
                    mtf_pass = (mtf["aligned_count"] >= 2) or (mtf["aligned_count"] >= 1 and e5m["quality"] >= 50)
                    
                    if score >= 60 and adx >= 18 and mtf_pass:
                        entry_price = df_main.iloc[i]['close']
                        atr = ind.get('atr', 1.5)
                        tp, sl = self._calc_tp_sl(entry_price, side, atr, self._last_known_spread)
                        
                        active_trade = {
                            'side': side,
                            'entry_price': entry_price,
                            'tp': tp,
                            'sl': sl,
                            'entry_time': current_time,
                            'score': score,
                            'reason': f"Score:{score} MTF:{mtf['aligned_count']} E5M:{e5m['quality']} T1h:{ind.get('trend_1h')} T4h:{ind.get('trend_4h')}",
                            'status': 'OPEN'
                        }

        self.report_results()

    def report_results(self):
        if not self.trades:
            print("No trades were taken during the backtest period.")
            return

        df = pd.DataFrame(self.trades)
        wins = len(df[df['status'] == 'WIN'])
        losses = len(df[df['status'] == 'LOSS'])
        total = wins + losses
        win_rate = (wins / total * 100) if total > 0 else 0
        
        # Estimate PnL (assuming RR 2:1 as in code)
        # Each win = +2 units, each loss = -1 unit
        pnl_units = (wins * 2) - losses
        
        print("\n" + "="*50)
        print("BACKTEST RESULTS")
        print("="*50)
        print(f"Total Trades: {total}")
        print(f"Wins:         {wins}")
        print(f"Losses:       {losses}")
        print(f"Win Rate:     {win_rate:.2f}%")
        print(f"Est. PnL:     {pnl_units} units (RR 2:1 basis)")
        print("="*50)
        
        print("\nTop 5 Failure Analysis (Losses with Highest Scores):")
        failures = df[df['status'] == 'LOSS'].sort_values(by='score', ascending=False).head(5)
        for _, f in failures.iterrows():
            print(f"[{f['entry_time']}] {f['side'].upper()} Score:{f['score']} | {f['reason']}")
            
        print("\nTop 5 Successes (Wins with Highest Scores):")
        successes = df[df['status'] == 'WIN'].sort_values(by='score', ascending=False).head(5)
        for _, s in successes.iterrows():
            print(f"[{s['entry_time']}] {s['side'].upper()} Score:{s['score']} | {s['reason']}")

if __name__ == "__main__":
    tester = ForexBacktester()
    tester.run_backtest(limit=500)
