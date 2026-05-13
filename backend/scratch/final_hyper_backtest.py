import os
import sys
import pandas as pd
import time
from forex_executor import ForexExecutor

class FinalHyperTester(ForexExecutor):
    def __init__(self, data):
        super().__init__()
        self.all_data = data
        self.current_idx = {tf: 0 for tf in data}
        self._dxy_cache = {"change": 0.0, "trend": "NEUTRAL", "ts": 0}

    def _get_dxy_context(self): return self._dxy_cache
    def _get_gold_orderbook(self): return {"obi": 0.0, "whale": "NORMAL"}
    def _get_gold_whale_trades(self): return "NORMAL"
    def get_account_information(self): return {"balance": 1000, "equity": 1000}

    def get_candles(self, symbol=None, timeframe="30m", limit=100):
        df = self.all_data.get(timeframe)
        if df is None or df.empty: return []
        idx = self.current_idx[timeframe]
        return df.iloc[max(0, idx-limit+1):idx+1].to_dict('records')

    def run_final_test(self, min_score=45, sl_p=15, tp_p=20):
        print(f"=== HYPER-SCALP FINAL BACKTEST REPORT ===")
        print(f"Params: Score >= {min_score}, SL: {sl_p} ($1.5), TP: {tp_p} ($2.0)")
        
        df_main = self.all_data["1m"]
        self.current_idx = {tf: 0 for tf in self.all_data}
        trades = []
        
        active_trade = None
        for i in range(150, len(df_main)):
            current_time = df_main.iloc[i]['dt']
            for tf in self.all_data:
                tf_df = self.all_data[tf]
                sync_idx = tf_df[tf_df['dt'] <= current_time].index.max()
                self.current_idx[tf] = int(sync_idx) if not pd.isna(sync_idx) else 0
            
            if active_trade:
                high, low = df_main.iloc[i]['high'], df_main.iloc[i]['low']
                if (active_trade['side'] == 'buy' and low <= active_trade['sl']) or \
                   (active_trade['side'] == 'sell' and high >= active_trade['sl']):
                    active_trade['status'] = 'LOSS'
                    active_trade['exit_time'] = current_time
                    trades.append(active_trade)
                    active_trade = None
                    continue
                elif (active_trade['side'] == 'buy' and high >= active_trade['tp']) or \
                     (active_trade['side'] == 'sell' and low <= active_trade['tp']):
                    active_trade['status'] = 'WIN'
                    active_trade['exit_time'] = current_time
                    trades.append(active_trade)
                    active_trade = None
                    continue
                continue

            # Debug candle counts
            # ind = self._calc_indicators(timeframe="1m")
            # We bypass the check in the backtester for speed and debugging
            candles = self.get_candles(timeframe="1m", limit=100)
            if len(candles) < 20: continue
            
            # Manual calculation for debug
            ind = self._calc_indicators(timeframe="1m")
            if not ind or 'rsi' not in ind:
                if i == 200:
                    for tf in self.all_data:
                        print(f"      [DEBUG] TF:{tf} Candles:{len(self.get_candles(timeframe=tf, limit=100))}")
                continue
            
            buy_s = self._score_setup(ind, "buy", 2.5)
            sell_s = self._score_setup(ind, "sell", 2.5)
            
            if i % 100 == 0:
                print(f"      [SCORE] {current_time} Buy:{buy_s:.1f} Sell:{sell_s:.1f} Vel:{ind.get('velocity',0):.4f}")

            side = None
            score = 0
            if buy_s >= sell_s and buy_s >= min_score: side = "buy"; score = buy_s
            elif sell_s > buy_s and sell_s >= min_score: side = "sell"; score = sell_s
            
            if side:
                vel = ind.get("velocity", 0)
                if vel > 0.001:
                    entry_p = df_main.iloc[i]['close']
                    active_trade = {
                        'side': side,
                        'entry_time': current_time,
                        'entry_price': entry_p,
                        'sl': entry_p - sl_p*0.1 if side == 'buy' else entry_p + sl_p*0.1,
                        'tp': entry_p + tp_p*0.1 if side == 'buy' else entry_p - tp_p*0.1,
                        'score': score,
                        'vel': vel
                    }
                    print(f"    [TRADE] {side.upper()} @ {entry_p} Score:{score:.1f} Vel:{vel:.4f}")

        self.report(trades)

    def report(self, trades):
        if not trades:
            print("No trades triggered.")
            return
        
        df = pd.DataFrame(trades)
        wins = len(df[df['status'] == 'WIN'])
        losses = len(df[df['status'] == 'LOSS'])
        total = wins + losses
        wr = (wins/total*100) if total > 0 else 0
        
        # PnL in units (TP 2.0 / SL 1.5)
        # Each win = 1.33 units (20/15), each loss = 1 unit
        pnl = (wins * (20/15)) - losses
        
        print("\n" + "="*40)
        print(f"Total Trades: {total}")
        print(f"Wins:         {wins}")
        print(f"Losses:       {losses}")
        print(f"Win Rate:     {wr:.2f}%")
        print(f"Net PnL (RR): {pnl:.2f} units")
        print("="*40)
        
        print("\nLast 10 Trades Detail:")
        for _, t in df.tail(10).iterrows():
            print(f"[{t['entry_time']}] {t['side'].upper()} Score:{t['score']:.1f} Vel:{t['vel']:.4f} -> {t['status']}")

if __name__ == "__main__":
    fx = ForexExecutor()
    data = {}
    for tf in ["1m", "5m", "30m", "1h", "4h"]:
        print(f"Fetching {tf}...")
        c = fx.get_candles(timeframe=tf, limit=2000)
        df = pd.DataFrame(c)
        df['dt'] = pd.to_datetime(df['time'])
        data[tf] = df
    
    tester = FinalHyperTester(data)
    tester.run_final_test(min_score=20)
