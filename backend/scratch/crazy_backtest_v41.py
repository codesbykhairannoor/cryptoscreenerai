import sys
import os
import requests
import pandas as pd
import numpy as np
import time

# Pastikan path backend terbaca
sys.path.append(os.getcwd())

# Import fungsi asli dari engine v41.0
from crypto_engine import _determine_trade_side, _calc_tp_sl

def fetch_data(symbol, interval="15m", limit=1000):
    for i in range(3):
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            r = requests.get(url, timeout=20, verify=False)
            if r.status_code == 200:
                df = pd.DataFrame(r.json(), columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
                for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
                return df
            else:
                print(f"[FETCH ERROR] {symbol} Code {r.status_code}: {r.text[:50]}", flush=True)
        except Exception as e:
            print(f"[FETCH EXCEPTION] {symbol} try {i+1}: {e}", flush=True)
            time.sleep(5)
    return None

def run_crazy_backtest():
    print("\n" + "="*80, flush=True)
    print("=== THE CRAZY BACKTEST v41.0 (BALANCED SMC PREDATOR) ===", flush=True)
    print("Modal: $10 | Strategy: Pure v41.0 Logic | Data: Last 10-15 Days", flush=True)
    print("="*80, flush=True)
    
    symbols = ["SOLUSDT", "BTCUSDT", "XRPUSDT", "DOGSUSDT", "HYPEUSDT", "WLDUSDT", "ENAUSDT", "TRUMPUSDT", "RENDERUSDT", "SUIUSDT"]
    total_stats = {'trades': 0, 'wins': 0, 'losses': 0, 'profit': 0}
    
    print(f"{'SYMBOL':<10} | {'TRADES':<6} | {'WR%':<6} | {'PROFIT':<8} | {'AVG/DAY'}", flush=True)
    print("-" * 80, flush=True)

    for sym in symbols:
        print(f"[FETCHING] {sym}...", end="\r", flush=True)
        df = fetch_data(sym)
        if df is None: 
            print(f"[ERROR] {sym} fetch failed. Skipping.", flush=True)
            continue
        
        # Prepare indicators (Simulate the tech dict)
        df['ema_9'] = df['c'].ewm(span=9).mean()
        df['ema_21'] = df['c'].ewm(span=21).mean()
        df['rsi'] = 50 # Default middle
        # Simplified RSI calculation
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        df['atr'] = (df['h'] - df['l']).rolling(14).mean()
        df['rvol'] = df['v'] / df['v'].rolling(20).mean()
        df['vwap'] = (df['c'] * df['v']).cumsum() / df['v'].cumsum()
        df['vwap_dist'] = ((df['c'] - df['vwap']) / df['vwap']) * 100
        
        # Mocking SMC signals (MSS/FVG based on price action)
        df['mss_bullish'] = (df['c'] > df['h'].shift(1)) & (df['c'].shift(1) > df['h'].shift(2))
        df['fvg'] = np.where((df['l'] > df['h'].shift(2)), "BULLISH", "NONE")
        df['in_demand'] = df['l'] <= df['l'].rolling(20).min()
        
        # Simulation loop
        in_pos = None
        sym_trades = 0
        sym_wins = 0
        sym_profit = 0
        
        for i in range(50, len(df)):
            row = df.iloc[i]
            now_p = row['c']
            
            if in_pos:
                # Exit check
                if in_pos['side'] == 'buy':
                    if row['l'] <= in_pos['sl']:
                        pnl = ((in_pos['sl'] - in_pos['ent'])/in_pos['ent']) * 10 * 100
                        sym_profit += pnl
                        sym_trades += 1
                        in_pos = None
                    elif row['h'] >= in_pos['tp']:
                        pnl = ((in_pos['tp'] - in_pos['ent'])/in_pos['ent']) * 10 * 100
                        sym_profit += pnl
                        sym_wins += 1
                        sym_trades += 1
                        in_pos = None
                continue

            # Check Entry using the ACTUAL function from engine
            tech_dict = {
                'rvol': row['rvol'], 'atr': row['atr'], 'mss_bullish': row['mss_bullish'],
                'fvg': row['fvg'], 'in_demand': row['in_demand'], 'limit_price': now_p
            }
            
            side, reason, tech_score = _determine_trade_side(
                tech_dict, row['rsi'], row['vwap_dist'], "NEUTRAL", now_p, 70.0, 0.0
            )
            
            if side == "buy":
                tp, sl = _calc_tp_sl(now_p, side, tech_dict)
                in_pos = {'side': side, 'ent': now_p, 'tp': tp, 'sl': sl}
        
        wr = (sym_wins / sym_trades * 100) if sym_trades > 0 else 0
        days = len(df) * 15 / (60 * 24)
        t_per_day = sym_trades / days if days > 0 else 0
        
        print(f"{sym:<10} | {sym_trades:<6} | {wr:>5.1f}% | {sym_profit:>+7.1f}% | {t_per_day:>7.1f}")
        
        total_stats['trades'] += sym_trades
        total_stats['wins'] += sym_wins
        total_stats['profit'] += sym_profit

    print("-" * 80)
    total_wr = (total_stats['wins'] / total_stats['trades'] * 100) if total_stats['trades'] > 0 else 0
    print(f"TOTAL TRADES: {total_stats['trades']} | AVG WR: {total_wr:.1f}% | TOTAL PNL: {total_stats['profit']:.1f}%")
    print(f"ESTIMATED DAILY TRADES (Total Engine): {total_stats['trades'] / (1000 * 15 / (60 * 24)):.1f}")
    print("="*80 + "\n")

if __name__ == "__main__":
    run_crazy_backtest()
