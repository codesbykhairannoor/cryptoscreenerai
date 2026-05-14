
import requests
import pandas as pd
import numpy as np
import time
import pickle
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

print("="*80)
print("BACKTESTING ENGINE - BINANCE VERSION")
print("="*80)

def fetch_data(symbol="BTCUSDT", interval="15m", days=30):
    """Fetch historical data dari Binance (lebih stabil!)"""
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    
    all_candles = []
    limit = 1000
    
    print(f"Fetching {symbol} from Binance...")
    
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
                print(f"API Error: {r.status_code}")
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
    """Calculate technical indicators"""
    df = df.copy()
    
    # EMA
    df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
    
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
    
    # Volume ratio
    df['volume_avg'] = df['vol'].rolling(window=20).mean()
    df['volume_ratio'] = df['vol'] / df['volume_avg']
    
    # Trend and candle info
    df['trend_up'] = df['close'] > df['ema_200']
    df['is_bullish'] = df['close'] > df['open']
    df['body_size'] = abs(df['close'] - df['open'])
    
    return df.dropna()

def backtest(df, params):
    """Run backtest simulation"""
    trades = []
    current_pos = None
    equity = 100.0
    leverage = 10
    margin_per_trade = 3.0
    fee = 0.0012  # 0.12% round trip
    
    min_rsi = params.get('min_rsi', 50)
    max_rsi = params.get('max_rsi', 65)
    min_vol_ratio = params.get('min_vol_ratio', 1.5)
    atr_sl = params.get('atr_sl', 1.0)
    atr_tp = params.get('atr_tp', 1.5)
    require_trend = params.get('require_trend', True)
    
    for i in range(200, len(df)):
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
        
        # Entry conditions
        buy_condition = (
            (not require_trend or row['trend_up']) and
            min_rsi <= row['rsi'] <= max_rsi and
            row['volume_ratio'] >= min_vol_ratio and
            row['is_bullish'] and
            row['body_size'] > row['atr'] * 0.3
        )
        
        if buy_condition:
            current_pos = {
                'side': 'buy',
                'entry': row['close'],
                'sl': row['close'] - (row['atr'] * atr_sl),
                'tp': row['close'] + (row['atr'] * atr_tp),
                'time': row['timestamp']
            }
    
    # Calculate metrics
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
    """Find optimal parameters"""
    print("\nStarting parameter optimization...")
    
    best_score = -float('inf')
    best_params = None
    best_result = None
    
    # Parameter combinations to test
    param_grid = []
    for min_rsi in [45, 50, 52, 55]:
        for max_rsi in [60, 65, 70, 75]:
            if min_rsi >= max_rsi:
                continue
            for min_vol in [1.2, 1.5, 1.8, 2.0]:
                for atr_sl in [0.8, 1.0, 1.2, 1.5]:
                    for atr_tp in [1.0, 1.5, 2.0, 2.5]:
                        for require_trend in [True, False]:
                            param_grid.append({
                                'min_rsi': min_rsi,
                                'max_rsi': max_rsi,
                                'min_vol_ratio': min_vol,
                                'atr_sl': atr_sl,
                                'atr_tp': atr_tp,
                                'require_trend': require_trend
                            })
    
    print(f"Testing {len(param_grid)} parameter combinations...")
    
    for i, params in enumerate(param_grid):
        result = backtest(df, params)
        
        # Check if this is a good result
        target_tpd = 5 <= result['trades_per_day'] <= 7
        good_wr = result['win_rate'] > 0.55
        enough_trades = result['trades'] >= 20
        positive_profit = result['profit'] > 0
        
        if enough_trades and positive_profit:
            # Calculate score
            score = (
                result['win_rate'] * 100 +
                result['profit_factor'] * 10 +
                (result['profit'] / 5)
            )
            
            # Bonus for hitting target trades per day
            if target_tpd:
                score += 50
            
            # Bonus for high win rate
            if result['win_rate'] > 0.65:
                score += 30
            
            if score > best_score:
                best_score = score
                best_params = params
                best_result = result
                
                print(f"\n{'='*80}")
                print(f"NEW BEST RESULT! Iteration: {i+1}/{len(param_grid)}")
                print(f"{'='*80}")
                print(f"Parameters: {params}")
                print(f"Total Trades: {result['trades']}")
                print(f"Winning: {result['winning']} | Losing: {result['losing']}")
                print(f"Win Rate: {result['win_rate']*100:.1f}%")
                print(f"Total Profit: ${result['profit']:.2f}")
                print(f"Profit Factor: {result['profit_factor']:.2f}")
                print(f"Trades Per Day: {result['trades_per_day']:.1f}")
                print(f"Final Equity: ${result['equity_final']:.2f}")
                print(f"{'='*80}")
        
        if (i + 1) % 50 == 0:
            print(f"Progress: {i+1}/{len(param_grid)} ({(i+1)/len(param_grid)*100:.1f}%)")
    
    return best_params, best_result

def train_ml_model(df):
    """Train ML model for trade prediction"""
    print("\nTraining ML model...")
    
    # Prepare features
    features = pd.DataFrame()
    features['close'] = df['close']
    features['ema_200'] = df['ema_200']
    features['ema_50'] = df['ema_50']
    features['ema_20'] = df['ema_20']
    features['rsi'] = df['rsi']
    features['atr'] = df['atr']
    features['volume_ratio'] = df['volume_ratio']
    features['trend_up'] = df['trend_up'].astype(int)
    features['is_bullish'] = df['is_bullish'].astype(int)
    
    # Prepare labels: will price rise >1% in next 10 candles?
    future_returns = df['close'].pct_change(10).shift(-10)
    labels = (future_returns > 0.01).astype(int)
    
    # Drop NaN values
    data = pd.concat([features, labels], axis=1).dropna()
    X = data.iloc[:, :-1]
    y = data.iloc[:, -1]
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, shuffle=False
    )
    
    # Scale features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Train model
    model = GradientBoostingClassifier(
        n_estimators=200,
        learning_rate=0.1,
        max_depth=5,
        random_state=42
    )
    model.fit(X_train_scaled, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test_scaled)
    accuracy = accuracy_score(y_test, y_pred)
    print(f"ML Model Accuracy: {accuracy:.4f}")
    
    # Feature importance
    print("\nTop 10 Features:")
    importances = sorted(
        zip(X.columns, model.feature_importances_),
        key=lambda x: x[1], reverse=True
    )[:10]
    for name, imp in importances:
        print(f"  {name}: {imp:.4f}")
    
    # Save model
    with open('crypto_ml_model.pkl', 'wb') as f:
        pickle.dump({'model': model, 'scaler': scaler}, f)
    print("\nML Model saved to crypto_ml_model.pkl")
    
    return model, scaler

def main():
    # List of symbols to test
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    
    all_results = []
    
    for symbol in symbols:
        print(f"\n{'#'*80}")
        print(f"PROCESSING: {symbol}")
        print(f"{'#'*80}")
        
        # 1. Fetch data
        df = fetch_data(symbol, days=60)
        if len(df) < 500:
            print(f"Skipping {symbol} - insufficient data")
            continue
        
        # 2. Calculate indicators
        df = calc_indicators(df)
        
        # 3. Train ML model
        train_ml_model(df)
        
        # 4. Optimize parameters
        best_params, best_result = optimize(df)
        
        if best_params and best_result:
            all_results.append({
                'symbol': symbol,
                'params': best_params,
                'result': best_result
            })
    
    # Print final summary
    print(f"\n{'='*80}")
    print("FINAL SUMMARY - ALL SYMBOLS")
    print(f"{'='*80}")
    
    for res in all_results:
        symbol = res['symbol']
        result = res['result']
        params = res['params']
        print(f"\n{symbol}:")
        print(f"  Best Params: {params}")
        print(f"  Trades: {result['trades']} | WR: {result['win_rate']*100:.1f}%")
        print(f"  Profit: ${result['profit']:.2f} | PF: {result['profit_factor']:.2f}")
        print(f"  Trades/Day: {result['trades_per_day']:.1f}")

if __name__ == "__main__":
    main()
