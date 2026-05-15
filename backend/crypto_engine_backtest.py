
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# === KONFIGURASI (SAMA DENGAN crypto_engine.py) ===
VERSION_TAG = "v26.16-FORCE-BOOT"
ADX_PERIOD           = 14
LEVERAGE             = 10
MAX_POSITIONS        = 1
RISK_PER_TRADE_USDT  = 0.50
FIXED_MARGIN_USDT    = 5.0
MIN_MOMENTUM_SCORE   = 30
MIN_PUMP_SCORE       = 15
MIN_TECH_SCORE       = 20
ATR_SL_MULT     = 2.0
ATR_TP_MIN_MULT = 4.0
TRAIL_GAP_ATR   = 2.5
SCALP_TP_PCT         = 0.08
SCALP_SL_PCT         = 0.015
BITGET_FEE_PCT          = 0.0012
MIN_EXPECTED_VALUE      = 0.015

# === FETCH HISTORICAL DATA (USE BINANCE - MORE STABLE) ===
def fetch_historical_data(symbol: str, interval: str = "15m", days: int = 7, exchange: str = "binance"):
    print(f"[BACKTEST] Fetching {days} days of {interval} data for {symbol} (Binance)...")
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    limit = 1500
    all_candles = []
    
    while start_time < end_time:
        try:
            url = (
                f"https://fapi.binance.com/fapi/v1/klines"
                f"?symbol={symbol.replace('USDT', '')}USDT&interval={interval}"
                f"&limit={limit}&startTime={start_time}"
            )
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if not data:
                    break
                all_candles.extend(data)
                if len(data) < limit:
                    break
                start_time = data[-1][0] + 1
            else:
                print(f"[FETCH WARNING] Status {r.status_code} for {symbol}")
                break
        except Exception as e:
            print(f"[FETCH ERROR] {symbol}: {e}")
            break
    
    if not all_candles:
        return pd.DataFrame()
    
    df = pd.DataFrame(all_candles)
    df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'vol', 
                  'close_ts', 'quote_vol', 'trades', 'taker_buy', 'taker_sell', 'ignore']
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'vol']]
    for col in ['open', 'high', 'low', 'close', 'vol']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna().sort_values('timestamp').reset_index(drop=True)
    print(f"[BACKTEST] Fetched {len(df)} candles for {symbol}")
    return df

# === INDICATORS (Simplified) ===
def calculate_indicators_for_backtest(df):
    df = df.copy()
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()
    
    # Volume Ratio (RVol)
    df['vol_avg_20'] = df['vol'].rolling(window=20).mean()
    df['rvol'] = df['vol'] / df['vol_avg_20']
    
    # EMA 9 & 21
    df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    # VWAP (simple)
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    cum_pv = (typical_price * df['vol']).cumsum()
    cum_v = df['vol'].cumsum()
    df['vwap'] = cum_pv / cum_v
    
    return df.dropna()

# === SIMULASI ENTRY LOGIC (Sama dengan crypto_engine.py) ===
def should_enter_trade(row, previous_row=None):
    rsi = row['rsi']
    rvol = row['rvol']
    ema_9 = row['ema_9']
    ema_21 = row['ema_21']
    close = row['close']
    atr = row['atr']
    vwap = row['vwap']
    
    # Thresholds (Sesuai yang kita optimize!)
    score_threshold = 50
    rvol_threshold = 0.8
    tech_score_threshold = 40
    
    side = None
    tech_score = 0
    
    # MSS (Market Structure Shift - simplified)
    if previous_row is not None:
        if close > previous_row['high']:
            tech_score += 40
            side = "buy"
        elif close < previous_row['low']:
            tech_score += 40
            side = "sell"
    
    # RSI & VWAP Filters
    if side == "buy":
        if 45 <= rsi <= 65:
            tech_score += 20
        if close >= vwap:
            tech_score += 10
    elif side == "sell":
        if 35 <= rsi <= 55:
            tech_score += 20
        if close <= vwap:
            tech_score += 10
    
    # Combined score simplification (Pump score = 50, tech score as calculated)
    pump_score = 50
    combined_score = round((pump_score * 0.5) + (tech_score * 0.5))
    
    # Check all conditions
    if (side is not None 
        and tech_score >= tech_score_threshold 
        and combined_score >= score_threshold 
        and rvol >= rvol_threshold):
        
        # EMA Filter
        if side == "buy" and ema_9 < ema_21:
            return None, None, None, None
        if side == "sell" and ema_9 > ema_21:
            return None, None, None, None
        
        # ATR Junk Filter
        atr_pct = (atr / close) * 100
        if atr_pct > 5.0:
            return None, None, None, None
        
        # TP/SL (Sesuai crypto_engine.py: TP +4%, SL -5%)
        if side == "buy":
            tp = close * 1.04
            sl = close * 0.95
        else:
            tp = close * 0.96
            sl = close * 1.05
        
        return side, combined_score, tp, sl
    
    return None, None, None, None

# === BACKTEST RUNNER ===
def run_backtest_on_symbol(symbol, df):
    print(f"\n[BACKTEST] Starting backtest for {symbol}...")
    
    initial_balance = 100.0
    balance = initial_balance
    position = None
    trades = []
    
    df = calculate_indicators_for_backtest(df)
    
    for i in range(1, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i-1]
        
        # Handle open position
        if position is not None:
            exit_price = None
            exit_reason = None
            
            if position['side'] == 'buy':
                if row['low'] <= position['sl']:
                    exit_price = position['sl']
                    exit_reason = 'SL'
                elif row['high'] >= position['tp']:
                    exit_price = position['tp']
                    exit_reason = 'TP'
            else:
                if row['high'] >= position['sl']:
                    exit_price = position['sl']
                    exit_reason = 'SL'
                elif row['low'] <= position['tp']:
                    exit_price = position['tp']
                    exit_reason = 'TP'
            
            if exit_price is not None:
                # Hitung PnL
                if position['side'] == 'buy':
                    pnl_pct = ((exit_price - position['entry']) / position['entry']) * LEVERAGE * 100
                else:
                    pnl_pct = ((position['entry'] - exit_price) / position['entry']) * LEVERAGE * 100
                
                # Hitung PnL USD dan kurangi fee
                pnl_usd = (pnl_pct / 100) * FIXED_MARGIN_USDT
                fee_usd = FIXED_MARGIN_USDT * LEVERAGE * BITGET_FEE_PCT
                net_pnl = pnl_usd - fee_usd
                
                balance += net_pnl
                
                trades.append({
                    'timestamp': row['timestamp'],
                    'symbol': symbol,
                    'side': position['side'],
                    'entry': position['entry'],
                    'exit': exit_price,
                    'reason': exit_reason,
                    'pnl_pct': pnl_pct,
                    'pnl_usd': net_pnl
                })
                
                position = None
                continue
        
        # Cari entry
        side, score, tp, sl = should_enter_trade(row, prev_row)
        if side is not None and position is None:
            position = {
                'side': side,
                'entry': row['close'],
                'tp': tp,
                'sl': sl,
                'score': score,
                'entry_timestamp': row['timestamp']
            }
    
    # Hitung Metrics
    total_trades = len(trades)
    winning_trades = len([t for t in trades if t['pnl_usd'] > 0])
    losing_trades = total_trades - winning_trades
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
    total_pnl = balance - initial_balance
    total_pnl_pct = (total_pnl / initial_balance) * 100
    
    # Trades per day
    if total_trades >= 2:
        start_ts = trades[0]['timestamp']
        end_ts = trades[-1]['timestamp']
        days = (end_ts - start_ts) / (1000 * 60 * 60 * 24)
        trades_per_day = total_trades / max(days, 1)
    else:
        trades_per_day = 0
    
    print(f"\n[BACKTEST] Hasil untuk {symbol}:")
    print(f"  Total Trades       : {total_trades}")
    print(f"  Winning Trades     : {winning_trades}")
    print(f"  Losing Trades      : {losing_trades}")
    print(f"  Win Rate           : {win_rate:.1f}%")
    print(f"  Total PnL          : ${total_pnl:.2f} ({total_pnl_pct:.1f}%)")
    print(f"  Final Balance      : ${balance:.2f}")
    print(f"  Trades per Day     : {trades_per_day:.1f}")
    
    return {
        'symbol': symbol,
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'total_pnl_pct': total_pnl_pct,
        'final_balance': balance,
        'trades_per_day': trades_per_day,
        'trades': trades
    }

# === MAIN ===
def main():
    print("\n" + "="*80)
    print("BACKTEST CRYPTO ENGINE - STRATEGI YANG SAMA DENGAN LIVE BOT")
    print("="*80)
    
    # Symbol yang akan di-backtest (pilih beberapa koin populer)
    symbols = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
        "PEPEUSDT", "WIFUSDT", "BONKUSDT"
    ]
    
    all_results = []
    
    for symbol in symbols:
        try:
            df = fetch_historical_data(symbol, interval="15m", days=14)
            if len(df) < 100:
                print(f"[SKIP] {symbol}: Data tidak cukup")
                continue
            
            result = run_backtest_on_symbol(symbol, df)
            all_results.append(result)
        except Exception as e:
            print(f"[ERROR] {symbol}: {e}")
    
    # Summary Keseluruhan
    if all_results:
        print("\n" + "="*80)
        print("SUMMARY BACKTEST KESELURUHAN")
        print("="*80)
        
        total_trades_all = sum(r['total_trades'] for r in all_results)
        winning_trades_all = sum(r['winning_trades'] for r in all_results)
        total_pnl_all = sum(r['total_pnl'] for r in all_results)
        avg_win_rate = sum(r['win_rate'] for r in all_results) / len(all_results)
        avg_trades_per_day = sum(r['trades_per_day'] for r in all_results) / len(all_results)
        
        print(f"\nTotal Trades Semua Symbol : {total_trades_all}")
        print(f"Total Winning Trades      : {winning_trades_all}")
        print(f"Rata-rata Win Rate        : {avg_win_rate:.1f}%")
        print(f"Total PnL Semua Symbol    : ${total_pnl_all:.2f}")
        print(f"Rata-rata Trades/Hari     : {avg_trades_per_day:.1f}")
        print("="*80)

if __name__ == "__main__":
    main()
