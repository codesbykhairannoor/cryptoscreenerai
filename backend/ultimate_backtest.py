
import requests
import pandas as pd
import numpy as np
import time
import pickle
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score

print("="*80)
print("ULTIMATE BACKTEST - TARGET: 5-7 TRADES/DAY + HIGH WR")
print("="*80)

def fetch_data(symbol="BTCUSDT", interval="5m", days=14):
    """Fetch data dengan timeframe lebih kecil untuk lebih banyak trades!"""
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    
    all_candles = []
    limit = 1000
    
    print(f"Fetching {symbol} {interval} for {days} days...")
    
    while start_time < end_time:
        try:
            url = (
                f"https://fapi.binance.com/fapi/v1/klines"
                f"?symbol={symbol}&interval={interval}"
                f"&limit={limit}&startTime={start_time}"
            )
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if not data:
                    break
                all_candles.extend(data)
                if len(data) < limit:
                    break
                start_time = data[-1][0] + 1
            else:
                break
        except Exception as e:
            print(f"Error: {e}")
            break
    
    if not all_candles:
        return pd.DataFrame()
    
    df = pd.DataFrame(all_candles)
    df.columns = [
        'timestamp', 'open', 'high', 'low', 'close', 'vol',
        'close_ts', 'quote_vol', 'trades', 'taker_buy', 'taker_sell', 'ignore'
    ]
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'vol']]
    
    for col in ['open', 'high', 'low', 'close', 'vol']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df = df.dropna().sort_values('timestamp').reset_index(drop=True)
    print(f"OK: {len(df)} candles")
    return df

def calc_indicators(df):
    """Calculate indicators untuk lebih banyak sinyal!"""
    df = df.copy()
    
    # EMA (lebih pendek untuk timeframe kecil)
    df['ema_100'] = df['close'].ewm(span=100, adjust=False).mean()
    df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema_10'] = df['close'].ewm(span=10, adjust=False).mean()
    
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
    
    # MACD
    df['ema_12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema_26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = df['ema_12'] - df['ema_26']
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    
    # Volume
    df['volume_avg'] = df['vol'].rolling(window=10).mean()
    df['volume_ratio'] = df['vol'] / df['volume_avg']
    
    # Candle info
    df['trend_up'] = df['close'] > df['ema_50']
    df['is_bullish'] = df['close'] > df['open']
    df['body_size'] = abs(df['close'] - df['open'])
    df['upper_wick'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['lower_wick'] = df[['open', 'close']].min(axis=1) - df['low']
    
    return df.dropna()

def backtest(df, params):
    """Backtest dengan target 5-7 trades/day!"""
    trades = []
    current_pos = None
    equity = 100.0
    leverage = 10
    margin_per_trade = 3.0
    fee = 0.0012
    
    # Parameters
    min_rsi = params.get('min_rsi', 40)
    max_rsi = params.get('max_rsi', 70)
    min_vol_ratio = params.get('min_vol_ratio', 1.0)
    atr_sl = params.get('atr_sl', 0.8)
    atr_tp = params.get('atr_tp', 1.2)
    require_trend = params.get('require_trend', False)
    use_macd = params.get('use_macd', True)
    
    for i in range(100, len(df)):
        row = df.iloc[i]
        
        if current_pos:
            close = row['close']
            high = row['high']
            low = row['low']
            
            if current_pos['side'] == 'buy':
                if high >= current_pos['tp']:
                    pnl_pct = ((current_pos['tp'] - current_pos['entry']) / current_pos['entry']) * leverage * 100
                    pnl_usd = (pnl_pct / 100) * margin_per_trade
                    fee_usd = margin_per_trade * leverage * fee
                    net_pnl = pnl_usd - fee_usd
                    
                    current_pos['pnl_pct'] = pnl_pct
                    current_pos['pnl_usd'] = net_pnl
                    current_pos['exit'] = current_pos['tp']
                    current_pos['exit_reason'] = 'TP'
                    trades.append(current_pos)
                    equity += net_pnl
                    current_pos = None
                elif low <= current_pos['sl']:
                    pnl_pct = ((current_pos['sl'] - current_pos['entry']) / current_pos['entry']) * leverage * 100
                    pnl_usd = (pnl_pct / 100) * margin_per_trade
                    fee_usd = margin_per_trade * leverage * fee
                    net_pnl = pnl_usd - fee_usd
                    
                    current_pos['pnl_pct'] = pnl_pct
                    current_pos['pnl_usd'] = net_pnl
                    current_pos['exit'] = current_pos['sl']
                    current_pos['exit_reason'] = 'SL'
                    trades.append(current_pos)
                    equity += net_pnl
                    current_pos = None
            continue
        
        # Entry conditions (lebih longgar untuk lebih banyak trades)
        macd_condition = (not use_macd) or (
            row['macd'] > row['macd_signal'] and 
            row['macd_hist'] > 0
        )
        
        buy_condition = (
            (not require_trend or row['trend_up']) and
            min_rsi <= row['rsi'] <= max_rsi and
            row['volume_ratio'] >= min_vol_ratio and
            row['is_bullish'] and
            row['body_size'] > row['atr'] * 0.15 and
            macd_condition
        )
        
        if buy_condition:
            current_pos = {
                'side': 'buy',
                'entry': row['close'],
                'sl': row['close'] - (row['atr'] * atr_sl),
                'tp': row['close'] + (row['atr'] * atr_tp),
                'time': row['timestamp']
            }
    
    if not trades:
        return {
            'trades': 0, 'winning': 0, 'losing': 0,
            'win_rate': 0.0, 'profit': 0.0, 'profit_factor': 0.0,
            'trades_per_day': 0.0, 'equity_final': equity
        }
    
    winning_trades = [t for t in trades if t['pnl_usd'] > 0]
    losing_trades = [t for t in trades if t['pnl_usd'] <= 0]
    
    gross_profit = sum(t['pnl_usd'] for t in winning_trades) if winning_trades else 0
    gross_loss = abs(sum(t['pnl_usd'] for t in losing_trades)) if losing_trades else 0.0001
    profit_factor = gross_profit / gross_loss
    
    if len(trades) >= 2:
        start_ts = trades[0]['time']
        end_ts = trades[-1]['time']
        days = (end_ts - start_ts) / (1000 * 60 * 60 * 24)
        trades_per_day = len(trades) / max(days, 1)
    else:
        trades_per_day = 0
    
    return {
        'trades': len(trades),
        'winning': len(winning_trades),
        'losing': len(losing_trades),
        'win_rate': len(winning_trades) / len(trades),
        'profit': equity - 100,
        'profit_factor': profit_factor,
        'trades_per_day': trades_per_day,
        'equity_final': equity,
        'trades_list': trades
    }

def optimize(df):
    """Optimization untuk target 5-7 trades/day!"""
    print("\nStarting OPTIMIZATION (target: 5-7 trades/day)...")
    
    best_score = -float('inf')
    best_params = None
    best_result = None
    
    # Parameter grid untuk lebih banyak trades
    param_grid = []
    for min_rsi in [35, 40, 45, 50]:
        for max_rsi in [60, 65, 70, 75]:
            if min_rsi >= max_rsi:
                continue
            for min_vol in [0.8, 1.0, 1.2, 1.5]:
                for atr_sl in [0.5, 0.8, 1.0, 1.2]:
                    for atr_tp in [0.8, 1.0, 1.2, 1.5]:
                        for require_trend in [False, True]:
                            for use_macd in [False, True]:
                                param_grid.append({
                                    'min_rsi': min_rsi,
                                    'max_rsi': max_rsi,
                                    'min_vol_ratio': min_vol,
                                    'atr_sl': atr_sl,
                                    'atr_tp': atr_tp,
                                    'require_trend': require_trend,
                                    'use_macd': use_macd
                                })
    
    print(f"Testing {len(param_grid)} parameter combinations...")
    
    for i, params in enumerate(param_grid):
        result = backtest(df, params)
        
        # Target: 4-8 trades/day, WR > 55%, profit > 0
        target_tpd = 4 <= result['trades_per_day'] <= 8
        good_wr = result['win_rate'] > 0.55
        enough_trades = result['trades'] >= 30
        positive_profit = result['profit'] > 0
        
        if enough_trades and positive_profit:
            # Calculate score
            score = (
                result['win_rate'] * 100 +
                result['profit_factor'] * 10 +
                (result['profit'] / 5)
            )
            
            # Bonus besar untuk target trades/day!
            if target_tpd:
                score += 100
            
            # Bonus untuk WR tinggi
            if result['win_rate'] > 0.60:
                score += 50
            if result['win_rate'] > 0.65:
                score += 50
            
            # Penalti untuk trades terlalu sedikit
            if result['trades_per_day'] < 3:
                score -= 50
            
            if score > best_score:
                best_score = score
                best_params = params
                best_result = result
                
                print(f"\n{'='*80}")
                print(f"NEW BEST! Iter: {i+1}/{len(param_grid)}")
                print(f"{'='*80}")
                print(f"Params: {params}")
                print(f"Trades: {result['trades']} | WR: {result['win_rate']*100:.1f}%")
                print(f"Profit: ${result['profit']:.2f} | PF: {result['profit_factor']:.2f}")
                print(f"Trades/Day: {result['trades_per_day']:.1f} (TARGET!)" if target_tpd else f"Trades/Day: {result['trades_per_day']:.1f}")
                print(f"Equity: ${result['equity_final']:.2f}")
                print(f"{'='*80}")
        
        if (i + 1) % 100 == 0:
            print(f"Progress: {i+1}/{len(param_grid)} ({(i+1)/len(param_grid)*100:.1f}%)")
    
    return best_params, best_result

def train_ml(df):
    """Train ML model"""
    print("\nTraining ML Model...")
    
    features = pd.DataFrame()
    features['close'] = df['close']
    features['ema_100'] = df['ema_100']
    features['ema_50'] = df['ema_50']
    features['ema_20'] = df['ema_20']
    features['ema_10'] = df['ema_10']
    features['rsi'] = df['rsi']
    features['atr'] = df['atr']
    features['macd'] = df['macd']
    features['macd_signal'] = df['macd_signal']
    features['macd_hist'] = df['macd_hist']
    features['volume_ratio'] = df['volume_ratio']
    features['trend_up'] = df['trend_up'].astype(int)
    features['is_bullish'] = df['is_bullish'].astype(int)
    
    future_returns = df['close'].pct_change(20).shift(-20)
    labels = (future_returns > 0.008).astype(int)
    
    data = pd.concat([features, labels], axis=1).dropna()
    X = data.iloc[:, :-1]
    y = data.iloc[:, -1]
    
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, shuffle=False
    )
    
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    model = RandomForestClassifier(
        n_estimators=300, max_depth=6, random_state=42
    )
    model.fit(X_train_scaled, y_train)
    
    y_pred = model.predict(X_test_scaled)
    print(f"Accuracy: {accuracy_score(y_test, y_pred):.4f}")
    print(f"Precision: {precision_score(y_test, y_pred):.4f}")
    print(f"Recall: {recall_score(y_test, y_pred):.4f}")
    
    with open('ultimate_ml_model.pkl', 'wb') as f:
        pickle.dump({'model': model, 'scaler': scaler, 'features': X.columns.tolist()}, f)
    print("ML Model saved!")
    
    return model, scaler

def main():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    
    for symbol in symbols:
        print(f"\n{'#'*80}")
        print(f"PROCESSING: {symbol}")
        print(f"{'#'*80}")
        
        # Fetch 5m data
        df = fetch_data(symbol, interval="5m", days=21)
        if len(df) < 1000:
            continue
        
        # Indicators
        df = calc_indicators(df)
        
        # ML
        train_ml(df)
        
        # Optimize
        best_params, best_result = optimize(df)
        
        if best_params and best_result:
            print(f"\n{'='*80}")
            print(f"FINAL BEST FOR {symbol}")
            print(f"{'='*80}")
            print(f"Params: {best_params}")
            print(f"Trades: {best_result['trades']} | WR: {best_result['win_rate']*100:.1f}%")
            print(f"Profit: ${best_result['profit']:.2f} | PF: {best_result['profit_factor']:.2f}")
            print(f"Trades/Day: {best_result['trades_per_day']:.1f}")

if __name__ == "__main__":
    main()



