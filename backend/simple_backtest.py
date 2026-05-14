
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
print("BACKTESTING ENGINE - SIMPLE VERSION")
print("="*80)

def fetch_data(symbol, interval="15m", days=30):
    """Fetch historical data dari Bitget"""
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    
    all_candles = []
    limit = 1000
    
    print(f"Fetching {symbol}...")
    
    while start_time < end_time:
        try:
            url = (
                f"https://api.bitget.com/api/v2/mix/market/history-candles"
                f"?symbol={symbol}&granularity={interval}&limit={limit}"
                f"&productType=USDT-FUTURES&startTime={start_time}"
            )
            r = requests.get(url, timeout=10, verify=False)
            if r.status_code == 200:
                data = r.json().get('data', [])
                if not data:
                    break
                all_candles.extend(data)
                if len(data) < limit:
                    break
                start_time = int(data[-1][0]) + 1
            else:
                break
        except Exception as e:
            print(f"Error: {e}")
            break
    
    if not all_candles:
        return pd.DataFrame()
    
    df = pd.DataFrame(all_candles)
    df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'vol', 'quote_vol']
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
    
    # Trend
    df['trend_up'] = df['close'] > df['ema_200']
    df['is_bullish'] = df['close'] > df['open']
    df['body_size'] = abs(df['close'] - df['open'])
    
    return df.dropna()

def backtest(df, params):
    """Run backtest"""
    trades = []
    current_pos = None
    equity = 100.0
    peak_equity = 100.0
    max_dd = 0.0
    
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
                    pnl = ((current_pos['tp'] - current_pos['entry']) / current_pos['entry']) * 10 * 100
                    current_pos['pnl'] = pnl
                    current_pos['exit'] = current_pos['tp']
                    trades.append(current_pos)
                    equity += (pnl / 100) * 3.0
                    equity -= 0.036  # Fee
                    current_pos = None
                elif low <= current_pos['sl']:
                    pnl = ((current_pos['sl'] - current_pos['entry']) / current_pos['entry']) * 10 * 100
                    current_pos['pnl'] = pnl
                    current_pos['exit'] = current_pos['sl']
                    trades.append(current_pos)
                    equity += (pnl / 100) * 3.0
                    equity -= 0.036  # Fee
                    current_pos = None
            continue
        
        # Entry conditions
        buy_cond = (
            (not require_trend or row['trend_up']) and
            min_rsi <= row['rsi'] <= max_rsi and
            row['volume_ratio'] >= min_vol_ratio and
            row['is_bullish'] and
            row['body_size'] > row['atr'] * 0.3
        )
        
        if buy_cond:
            current_pos = {
                'side': 'buy',
                'entry': row['close'],
                'sl': row['close'] - (row['atr'] * atr_sl),
                'tp': row['close'] + (row['atr'] * atr_tp),
                'time': row['timestamp']
            }
    
    # Hitung metrics
    if not trades:
        return {
            'trades': 0, 'win_rate': 0, 'profit': 0, 'pf': 0,
            'trades_per_day': 0, 'max_dd': 0
        }
    
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    
    total_pnl = sum(t['pnl'] for t in trades)
    gross_profit = sum(t['pnl'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 1
    profit_factor = gross_profit / gross_loss
    
    if len(trades) >= 2:
        start_t = trades[0]['time']
        end_t = trades[-1]['time']
        days = (end_t - start_t) / (1000 * 60 * 60 * 24)
        tpd = len(trades) / max(days, 1)
    else:
        tpd = 0
    
    return {
        'trades': len(trades),
        'win_rate': len(wins) / len(trades),
        'profit': equity - 100,
        'pf': profit_factor,
        'trades_per_day': tpd,
        'max_dd': max_dd,
        'trades_list': trades
    }

def optimize(df):
    """Optimize parameters"""
    print("\nOptimizing...")
    
    best_score = -float('inf')
    best_params = None
    best_result = None
    
    # Parameter grid
    params_list = []
    for min_rsi in [45, 50, 52, 55]:
        for max_rsi in [60, 65, 70]:
            if min_rsi >= max_rsi:
                continue
            for min_vol in [1.2, 1.5, 1.8]:
                for atr_sl in [0.8, 1.0, 1.2]:
                    for atr_tp in [1.0, 1.5, 2.0]:
                        for require_trend in [True, False]:
                            params_list.append({
                                'min_rsi': min_rsi,
                                'max_rsi': max_rsi,
                                'min_vol_ratio': min_vol,
                                'atr_sl': atr_sl,
                                'atr_tp': atr_tp,
                                'require_trend': require_trend
                            })
    
    print(f"Total combinations: {len(params_list)}")
    
    for i, params in enumerate(params_list):
        result = backtest(df, params)
        
        # Target: 5-7 trades/day, WR > 55%
        target_tpd = 5 <= result['trades_per_day'] <= 7
        good_wr = result['win_rate'] > 0.55
        enough_trades = result['trades'] >= 10
        
        if enough_trades:
            score = (
                result['win_rate'] * 100 +
                result['pf'] * 10 +
                (result['profit'] / 10)
            )
            
            if target_tpd:
                score += 50
            
            if score > best_score:
                best_score = score
                best_params = params
                best_result = result
                
                print(f"\nNEW BEST! Iter {i+1}/{len(params_list)}")
                print(f"Params: {params}")
                print(f"Trades: {result['trades']} | WR: {result['win_rate']*100:.1f}%")
                print(f"Profit: ${result['profit']:.2f} | PF: {result['pf']:.2f}")
                print(f"Trades/day: {result['trades_per_day']:.1f}")
                print("-"*80)
        
        if (i+1) % 100 == 0:
            print(f"Progress: {i+1}/{len(params_list)} ({(i+1)/len(params_list)*100:.1f}%)")
    
    return best_params, best_result

def train_ml_model(df):
    """Train ML model untuk prediksi profit"""
    print("\nTraining ML Model...")
    
    # Features
    features = pd.DataFrame()
    features['close'] = df['close']
    features['ema_200'] = df['ema_200']
    features['ema_50'] = df['ema_50']
    features['rsi'] = df['rsi']
    features['atr'] = df['atr']
    features['volume_ratio'] = df['volume_ratio']
    features['trend_up'] = df['trend_up'].astype(int)
    features['is_bullish'] = df['is_bullish'].astype(int)
    
    # Labels: apakah harga naik 1% dalam 10 candle
    future_returns = df['close'].pct_change(10).shift(-10)
    labels = (future_returns > 0.01).astype(int)
    
    # Drop NaN
    data = pd.concat([features, labels], axis=1).dropna()
    X = data.iloc[:, :-1]
    y = data.iloc[:, -1]
    
    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, shuffle=False
    )
    
    # Scale
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Train
    model = GradientBoostingClassifier(
        n_estimators=200, learning_rate=0.1, max_depth=5, random_state=42
    )
    model.fit(X_train_scaled, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test_scaled)
    acc = accuracy_score(y_test, y_pred)
    print(f"ML Accuracy: {acc:.4f}")
    
    # Save
    with open('ml_model.pkl', 'wb') as f:
        pickle.dump({'model': model, 'scaler': scaler}, f)
    print("ML Model saved!")
    
    return model, scaler

def main():
    # 1. Fetch data
    df = fetch_data("BTCUSDT", days=30)
    if len(df) < 500:
        print("Data tidak cukup!")
        return
    
    # 2. Hitung indikator
    df = calc_indicators(df)
    
    # 3. Train ML
    train_ml_model(df)
    
    # 4. Optimize
    best_params, best_result = optimize(df)
    
    if best_params and best_result:
        print("\n" + "="*80)
        print("FINAL BEST RESULT")
        print("="*80)
        print(f"Best Params: {best_params}")
        print(f"Total Trades: {best_result['trades']}")
        print(f"Win Rate: {best_result['win_rate']*100:.1f}%")
        print(f"Total Profit: ${best_result['profit']:.2f}")
        print(f"Profit Factor: {best_result['pf']:.2f}")
        print(f"Trades/Day: {best_result['trades_per_day']:.1f}")
        print("="*80)
    else:
        print("Tidak ada hasil yang bagus!")

if __name__ == "__main__":
    main()
