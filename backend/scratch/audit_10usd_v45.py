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
#  AUDIT 10 USD STRESS TEST v45.0 (500+ LINES)
#  GOAL: CAN WE GROW $10 WITH $3 MARGIN?
# ============================================================================-

SCAN_COUNT = 50
DAYS = 15
INITIAL_WALLET = 10.0
MARGIN_PER_TRADE = 3.0
LEVERAGE = 10
COMMISSION = 0.0004

def generate_market_data(symbol, days=15):
    np.random.seed(sum(ord(c) for c in symbol))
    periods = days * 1440
    base_price = 100.0 if "BTC" not in symbol else 65000.0
    # Volatility realistic for mid-caps
    vol = np.random.uniform(0.0008, 0.0025)
    returns = np.random.normal(0, vol, periods)
    price_path = base_price * np.exp(np.cumsum(returns))
    dates = pd.date_range(end=datetime.now(), periods=periods, freq='1min')
    return pd.DataFrame({
        'timestamp': dates, 'close': price_path,
        'high': price_path * (1 + abs(np.random.normal(0, 0.0015, periods))),
        'low': price_path * (1 - abs(np.random.normal(0, 0.0015, periods))),
        'volume': np.random.uniform(1000, 20000, periods)
    })

def run_10usd_audit():
    print("\n" + "="*80)
    print("=" + " "*28 + "AUDIT 10 USD STRESS TEST" + " "*26 + "=")
    print("=" + " "*24 + "WALLET: $10 | MARGIN: $3 | RR: 1:1" + " "*20 + "=")
    print("="*80 + "\n")

    wallet = INITIAL_WALLET
    # Simulate fetching symbols
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"] + [f"COIN_{i}USDT" for i in range(4, SCAN_COUNT + 1)]
    
    # Load all data first for speed
    print(f"[1/3] Loading Market Data for {len(symbols)} Symbols...")
    market_dfs = {s: generate_market_data(s, DAYS) for s in symbols}
    
    active_positions = []
    trade_history = []
    daily_balance = []

    print(f"[2/3] Simulating 15 Days of Live Trading...")

    # Iterate through time (minute by minute)
    # To speed up, we step every 5 minutes (engine scan interval)
    total_minutes = DAYS * 1440
    for t_idx in range(100, total_minutes, 5):
        current_time = market_dfs['BTCUSDT'].iloc[t_idx]['timestamp']
        
        # 1. Update Existing Positions
        for pos in active_positions[:]:
            df = market_dfs[pos['symbol']]
            row = df.iloc[t_idx]
            
            exit_price = None
            if pos['side'] == "buy":
                if row['high'] >= pos['tp']: exit_price = pos['tp']
                elif row['low'] <= pos['sl']: exit_price = pos['sl']
            else:
                if row['low'] <= pos['tp']: exit_price = pos['tp']
                elif row['high'] >= pos['sl']: exit_price = pos['sl']
            
            if exit_price:
                # Calculate PnL
                raw_pnl_pct = ((exit_price - pos['entry']) / pos['entry']) if pos['side'] == "buy" else ((pos['entry'] - exit_price) / pos['entry'])
                pnl_usd = (raw_pnl_pct * MARGIN_PER_TRADE * LEVERAGE) - (MARGIN_PER_TRADE * LEVERAGE * COMMISSION * 2)
                
                wallet += pnl_usd
                pos['exit_price'] = exit_price
                pos['pnl_usd'] = pnl_usd
                pos['wallet_after'] = wallet
                trade_history.append(pos)
                active_positions.remove(pos)

        # 2. Scan for New Opportunities (If we have margin left)
        # With $10 wallet and $3 margin, max positions = floor(wallet/3)
        max_pos = int(wallet // MARGIN_PER_TRADE)
        
        if len(active_positions) < max_pos:
            for symbol in symbols:
                if any(p['symbol'] == symbol for p in active_positions): continue
                if len(active_positions) >= max_pos: break
                
                df = market_dfs[symbol]
                row = df.iloc[t_idx]
                
                # Simple Indicators (Mock real engine)
                mss_bull = row['close'] > df['high'].iloc[t_idx-20:t_idx].max()
                mss_bear = row['close'] < df['low'].iloc[t_idx-20:t_idx].min()
                rvol = np.random.uniform(0.3, 2.5)
                rsi = 50 + (10 if mss_bull else (-10 if mss_bear else 0))
                
                tech = {
                    'mss_bullish': mss_bull, 'mss_bearish': mss_bear,
                    'fvg': 'BULLISH' if mss_bull and rvol > 1.2 else ('BEARISH' if mss_bear and rvol > 1.2 else 'NONE'),
                    'rvol': rvol, 'atr': row['high'] - row['low']
                }
                
                side, reason, score = _determine_trade_side(tech, rsi, 0.0, "NEUTRAL", row['close'], 50, 50)
                
                if side and rvol > 0.4:
                    tp, sl = _calc_tp_sl(row['close'], side, tech)
                    active_positions.append({
                        'symbol': symbol, 'side': side, 'entry': row['close'],
                        'tp': tp, 'sl': sl, 'time': current_time, 'reason': reason
                    })

        if t_idx % 1440 == 0: # Daily Snapshot
            daily_balance.append({'date': current_time.date(), 'wallet': wallet})

    # --- FINAL REPORT ---
    print(f"\n[3/3] Finalizing Audit Results...")
    tdf = pd.DataFrame(trade_history)
    
    print("\n" + "="*80)
    print("=" + " "*28 + "GRAND AUDIT SUMMARY" + " "*32 + "=")
    print("="*80)
    print(f"  Starting Balance   : ${INITIAL_WALLET:.2f}")
    print(f"  Ending Balance     : ${wallet:.2f}")
    print(f"  Total PnL (%)      : {((wallet-INITIAL_WALLET)/INITIAL_WALLET*100):+.2f}%")
    print(f"  Total Trades       : {len(tdf)}")
    print(f"  Win Rate (%)       : {(len(tdf[tdf['pnl_usd'] > 0])/len(tdf)*100 if len(tdf)>0 else 0):.2f}%")
    print(f"  Max Wallet Peak    : ${tdf['wallet_after'].max():.2f}")
    print(f"  Max Drawdown (Min) : ${tdf['wallet_after'].min():.2f}")
    print("="*80)

    print("\n[DAILY BALANCE GROWTH]")
    for d in daily_balance:
        print(f"  {d['date']} | Wallet: ${d['wallet']:.2f}")

    print("\n[LAST 10 TRADES AUDIT]")
    if not tdf.empty:
        print(tdf[['time', 'symbol', 'side', 'pnl_usd', 'wallet_after']].tail(10).to_string(index=False))
    
    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    run_10usd_audit()
