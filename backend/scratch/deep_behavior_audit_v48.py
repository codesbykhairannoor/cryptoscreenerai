import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Ensure backend path is accessible
sys.path.append(os.getcwd())

# Import REAL logic
from crypto_engine import _determine_trade_side, _calc_tp_sl

# ============================================================================-
#  DEEP BEHAVIOR AUDIT v48.0 (MICROSCOPIC ANALYSIS)
#  GOAL: ANALYZE ENTRY PRECISION & DRAWDOWN BEHAVIOR
# ============================================================================-

SCAN_COUNT = 10
DAYS = 7 # 7 days is enough for deep micro-analysis
INITIAL_WALLET = 100.0

def generate_micro_data(symbol, days=7):
    np.random.seed(sum(ord(c) for c in symbol))
    periods = days * 1440
    base_price = 100.0 if "BTC" not in symbol else 65000.0
    # Add some "SMC Patterns" into the random walk
    vol = 0.0015
    data = []
    price = base_price
    for i in range(periods):
        # Every 200 bars, simulate a massive MSS breakout
        if i % 200 == 0:
            change = np.random.uniform(0.01, 0.03) # 1-3% jump
        else:
            change = np.random.normal(0, vol)
        
        price *= (1 + change)
        high = price * (1 + abs(np.random.normal(0, 0.001)))
        low = price * (1 - abs(np.random.normal(0, 0.001)))
        data.append({
            'timestamp': datetime.now() - timedelta(minutes=periods-i),
            'open': price / (1+change), 'high': high, 'low': low, 'close': price,
            'volume': np.random.uniform(5000, 50000)
        })
    return pd.DataFrame(data)

def run_behavior_audit():
    print("\n" + "="*80)
    print("=" + " "*25 + "DEEP BEHAVIOR AUDIT v48.0" + " "*26 + "=")
    print("=" + " "*22 + "ANALYZING ENTRY PRECISION & DRAWDOWN" + " "*18 + "=")
    print("="*80 + "\n")

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
    all_trades = []

    for symbol in symbols:
        print(f"  [DATA] Analyzing {symbol} micro-movements...")
        df = generate_micro_data(symbol, DAYS)
        
        # We step minute by minute
        for i in range(50, len(df)-60):
            row = df.iloc[i]
            
            # --- 1. SENSOR SIMULATION ---
            # Simplified but representative of the current engine
            window = df.iloc[i-20:i]
            mss_bull = row['close'] > window['high'].max()
            mss_bear = row['close'] < window['low'].min()
            rvol = 1.2
            rsi = 55 if mss_bull else (45 if mss_bear else 50)
            ema_21 = df['close'].iloc[i-21:i].mean()
            
            tech = {
                'mss_bullish': mss_bull, 'mss_bearish': mss_bear,
                'fvg': 'BULLISH' if mss_bull else ('BEARISH' if mss_bear else 'NONE'),
                'in_demand': mss_bull, 'in_supply': mss_bear,
                'rvol': rvol, 'atr': row['high'] - row['low'], 'obi': 0.2 if mss_bull else -0.2,
                'ema_21': ema_21
            }

            side, reason, score = _determine_trade_side(tech, rsi, 0, "NEUTRAL", row['close'], 50, 50)
            
            if side:
                entry_p = row['close']
                tp_p, sl_p = _calc_tp_sl(entry_p, side, tech)
                
                # --- BEHAVIOR TRACKING ---
                max_favorable_excursion = 0 # Max profit before exit
                max_adverse_excursion = 0   # Max drawdown before exit
                exit_time = None
                status = "LOSS"
                
                # Scan next 60 bars for outcome
                for j in range(i+1, min(i+1440, len(df))): # Look up to 24h ahead
                    future_row = df.iloc[j]
                    
                    # Track MFE/MAE
                    pnl_pct = (future_row['high'] - entry_p)/entry_p if side == "buy" else (entry_p - future_row['low'])/entry_p
                    max_favorable_excursion = max(max_favorable_excursion, pnl_pct)
                    
                    drawdown_pct = (entry_p - future_row['low'])/entry_p if side == "buy" else (future_row['high'] - entry_p)/entry_p
                    max_adverse_excursion = max(max_adverse_excursion, drawdown_pct)

                    # Check TP/SL
                    if side == "buy":
                        if future_row['high'] >= tp_p: status = "WIN"; exit_time = j; break
                        if future_row['low'] <= sl_p: status = "LOSS"; exit_time = j; break
                    else:
                        if future_row['low'] <= tp_p: status = "WIN"; exit_time = j; break
                        if future_row['high'] >= sl_p: status = "LOSS"; exit_time = j; break
                
                if exit_time:
                    # Compare Entry to Local Min/Max (Precision Check)
                    local_window = df.iloc[i-5:i+1]
                    lowest_p = local_window['low'].min()
                    highest_p = local_window['high'].max()
                    
                    # Distance from "Ideal" entry (Buy at lowest, Sell at highest)
                    precision_gap = abs(entry_p - lowest_p)/lowest_p if side == "buy" else abs(highest_p - entry_p)/highest_p
                    
                    all_trades.append({
                        'symbol': symbol, 'side': side, 'entry': entry_p, 'status': status,
                        'precision_gap%': precision_gap * 100,
                        'drawdown%': max_adverse_excursion * 100,
                        'max_profit%': max_favorable_excursion * 100
                    })
                    # Skip to exit to avoid overlapping trades in audit
                    i = exit_time

    # --- ANALYZE RESULTS ---
    tdf = pd.DataFrame(all_trades)
    print("\n" + "="*80)
    print("=" + " "*28 + "BEHAVIORAL AUDIT RESULTS" + " "*24 + "=")
    print("="*80)
    
    print(f"  Total Trades Analyzed : {len(tdf)}")
    print(f"  Avg Precision Gap (%) : {tdf['precision_gap%'].mean():.2f}% (Lower is better)")
    print(f"  Avg Max Drawdown (%)  : {tdf['drawdown%'].mean():.2f}%")
    print(f"  Avg Max Profit (%)    : {tdf['max_profit%'].mean():.2f}%")
    
    win_trades = tdf[tdf['status'] == "WIN"]
    loss_trades = tdf[tdf['status'] == "LOSS"]
    
    print("\n[WINNING TRADES BEHAVIOR]")
    print(f"  Avg Drawdown before Win: {win_trades['drawdown%'].mean():.2f}%")
    print(f"  Avg Precision Gap: {win_trades['precision_gap%'].mean():.2f}%")

    print("\n[LOSING TRADES BEHAVIOR]")
    print(f"  Avg Profit before Loss: {loss_trades['max_profit%'].mean():.2f}%")
    print(f"  Avg Precision Gap: {loss_trades['precision_gap%'].mean():.2f}%")

    print("\n" + "="*80)
    print("  [LESSON 1] Entry Precision: If Gap > 1%, you are catching FOMO, not the bottom.")
    print("  [LESSON 2] Drawdown: If Avg Drawdown > 3%, SL 5% is required for breathing.")
    print("  [LESSON 3] Trailing: If Avg Profit before Loss > 3%, Trailing SL could save trades.")
    print("="*80 + "\n")

if __name__ == "__main__":
    run_behavior_audit()
