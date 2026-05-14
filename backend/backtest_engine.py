
"""
BACKTESTING ENGINE GILA-GILAAN
==============================
Fitur:
- Fetch historical data dari Bitget/Binance
- Simulasi trading dengan berbagai parameter
- Optimasi parameter otomatis
- ML model untuk prediksi profit
- Visualisasi hasil backtest
"""

import requests
import pandas as pd
import numpy as np
import time
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
import pickle
import warnings
warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────────────────────────
LEVERAGE = 10
RISK_PER_TRADE = 0.50  # $0.50 per trade
FIXED_MARGIN = 3.0     # $3 per trade
COMMISSION_FEE = 0.0012  # 0.12% round trip

# ─────────────────────────────────────────────────────────────────────────────
#  DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Trade:
    timestamp: int
    symbol: str
    side: str
    entry_price: float
    sl_price: float
    tp_price: float
    size: float
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl_pct: Optional[float] = None
    pnl_usd: Optional[float] = None


@dataclass
class BacktestResult:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl_pct: float
    total_pnl_usd: float
    max_drawdown_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    trades_per_day: float
    best_trade: Trade
    worst_trade: Trade
    trades: List[Trade]


# ─────────────────────────────────────────────────────────────────────────────
#  HISTORICAL DATA FETCHER
# ─────────────────────────────────────────────────────────────────────────────
def fetch_historical_data(
    symbol: str,
    interval: str = "15m",
    days: int = 30,
    exchange: str = "bitget"
):
    """
    Fetch historical candle data dari Bitget atau Binance.
    """
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    
    limit = 1000
    all_candles = []
    
    while start_time &lt; end_time:
        try:
            if exchange.lower() == "bitget":
                url = (
                    f"https://api.bitget.com/api/v2/mix/market/history-candles"
                    f"?symbol={symbol}&amp;granularity={interval}&amp;limit={limit}"
                    f"&amp;productType=USDT-FUTURES&amp;startTime={start_time}"
                )
                r = requests.get(url, timeout=10, verify=False)
                if r.status_code == 200:
                    data = r.json().get('data', [])
                    if not data:
                        break
                    all_candles.extend(data)
                    if len(data) &lt; limit:
                        break
                    start_time = int(data[-1][0]) + 1
                else:
                    break
                    
            elif exchange.lower() == "binance":
                url = (
                    f"https://fapi.binance.com/fapi/v1/klines"
                    f"?symbol={symbol.replace('USDT', '')}USDT&amp;interval={interval}"
                    f"&amp;limit={limit}&amp;startTime={start_time}"
                )
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if not data:
                        break
                    all_candles.extend(data)
                    if len(data) &lt; limit:
                        break
                    start_time = data[-1][0] + 1
                else:
                    break
                    
        except Exception as e:
            print(f"[FETCH ERROR] {symbol}: {e}")
            break
    
    if not all_candles:
        return pd.DataFrame()
    
    # Convert ke DataFrame
    df = pd.DataFrame(all_candles)
    
    if exchange.lower() == "bitget":
        # Bitget format: [ts, open, high, low, close, vol, quoteVol]
        df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'vol', 'quote_vol']
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'vol']]
    else:
        # Binance format: [ts, open, high, low, close, vol, close_ts, quote_vol, trades, taker_buy, taker_sell, ignore]
        df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'vol', 
                      'close_ts', 'quote_vol', 'trades', 'taker_buy', 'taker_sell', 'ignore']
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'vol']]
    
    # Convert ke numeric
    for col in ['open', 'high', 'low', 'close', 'vol']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df = df.dropna()
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    print(f"[FETCH OK] {symbol} | {len(df)} candles | {interval} | {days} days")
    return df


# ─────────────────────────────────────────────────────────────────────────────
#  TECHNICAL INDICATORS
# ─────────────────────────────────────────────────────────────────────────────
def calculate_indicators(df):
    """
    Hitung semua indikator teknis yang diperlukan.
    """
    df = df.copy()
    
    # EMA
    df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta &gt; 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta &lt; 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()
    
    # VWAP (sederhana)
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    cum_pv = (typical_price * df['vol']).cumsum()
    cum_v = df['vol'].cumsum()
    df['vwap'] = cum_pv / cum_v
    
    # Volume ratio
    df['volume_avg_20'] = df['vol'].rolling(window=20).mean()
    df['volume_ratio'] = df['vol'] / df['volume_avg_20']
    
    # Candle patterns
    df['body_size'] = abs(df['close'] - df['open'])
    df['upper_wick'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['lower_wick'] = df[['open', 'close']].min(axis=1) - df['low']
    df['is_bullish'] = df['close'] &gt; df['open']
    df['is_bearish'] = df['close'] &lt; df['open']
    
    # Momentum
    df['change_1'] = df['close'].pct_change(1)
    df['change_3'] = df['close'].pct_change(3)
    df['change_5'] = df['close'].pct_change(5)
    
    # Trend
    df['trend_up'] = df['close'] &gt; df['ema_200']
    df['trend_down'] = df['close'] &lt; df['ema_200']
    
    return df.dropna()


# ─────────────────────────────────────────────────────────────────────────────
#  TRADING STRATEGY
# ─────────────────────────────────────────────────────────────────────────────
def should_entry(
    row,
    params
):
    """
    Menentukan apakah harus entry berdasarkan parameter.
    Return: (should_entry, side, entry_price, sl_price, tp_price)
    """
    close = row['close']
    ema_200 = row['ema_200']
    rsi = row['rsi']
    atr = row['atr']
    volume_ratio = row['volume_ratio']
    trend_up = row['trend_up']
    body_size = row['body_size']
    is_bullish = row['is_bullish']
    
    # Ambil parameter
    min_rsi = params.get('min_rsi', 50)
    max_rsi = params.get('max_rsi', 65)
    min_volume_ratio = params.get('min_volume_ratio', 1.5)
    atr_sl_mult = params.get('atr_sl_mult', 1.0)
    atr_tp_mult = params.get('atr_tp_mult', 1.0)
    require_trend = params.get('require_trend', True)
    
    # BUY logic
    buy_condition = (
        (not require_trend or trend_up) and
        min_rsi &lt;= rsi &lt;= max_rsi and
        volume_ratio &gt;= min_volume_ratio and
        is_bullish and
        body_size &gt; atr * 0.3
    )
    
    if buy_condition:
        side = "buy"
        entry_price = close
        sl_price = close - (atr * atr_sl_mult)
        tp_price = close + (atr * atr_tp_mult)
        return True, side, entry_price, sl_price, tp_price
    
    return False, "neutral", 0, 0, 0


# ─────────────────────────────────────────────────────────────────────────────
#  BACKTEST RUNNER
# ─────────────────────────────────────────────────────────────────────────────
def run_backtest(
    df,
    symbol: str,
    params,
    initial_capital: float = 100.0
):
    """
    Jalankan backtest pada dataframe dengan parameter tertentu.
    """
    trades = []
    current_position = None
    equity_curve = [initial_capital]
    peak_equity = initial_capital
    
    for i in range(200, len(df)):
        row = df.iloc[i]
        current_time = int(row['timestamp'])
        
        # Check exit untuk posisi yang sedang berjalan
        if current_position is not None:
            close = row['close']
            high = row['high']
            low = row['low']
            
            # Check TP
            if current_position['side'] == 'buy':
                if high &gt;= current_position['tp_price']:
                    # TP hit
                    exit_price = current_position['tp_price']
                    exit_reason = "TP"
                elif low &lt;= current_position['sl_price']:
                    # SL hit
                    exit_price = current_position['sl_price']
                    exit_reason = "SL"
                else:
                    # Hold
                    continue
            else:
                # Sell logic (jika diaktifkan)
                if low &lt;= current_position['tp_price']:
                    exit_price = current_position['tp_price']
                    exit_reason = "TP"
                elif high &gt;= current_position['sl_price']:
                    exit_price = current_position['sl_price']
                    exit_reason = "SL"
                else:
                    continue
            
            # Hitung PnL
            if current_position['side'] == 'buy':
                pnl_pct = ((exit_price - current_position['entry_price']) / current_position['entry_price']) * LEVERAGE * 100
            else:
                pnl_pct = ((current_position['entry_price'] - exit_price) / current_position['entry_price']) * LEVERAGE * 100
            
            pnl_usd = (pnl_pct / 100) * FIXED_MARGIN
            
            # Kurangi fee
            pnl_usd -= (FIXED_MARGIN * LEVERAGE * COMMISSION_FEE)
            
            # Update trade
            trade = current_position['trade_obj']
            trade.exit_price = exit_price
            trade.exit_reason = exit_reason
            trade.pnl_pct = pnl_pct
            trade.pnl_usd = pnl_usd
            
            trades.append(trade)
            
            # Update equity
            new_equity = equity_curve[-1] + pnl_usd
            equity_curve.append(new_equity)
            
            if new_equity &gt; peak_equity:
                peak_equity = new_equity
            
            current_position = None
            continue
        
        # Check entry
        should_trade, side, entry_price, sl_price, tp_price = should_entry(row, params)
        
        if should_trade:
            # Hitung size (fixed margin)
            size = (FIXED_MARGIN * LEVERAGE) / entry_price
            
            # Buat trade object
            trade = Trade(
                timestamp=current_time,
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                sl_price=sl_price,
                tp_price=tp_price,
                size=size
            )
            
            current_position = {
                'side': side,
                'entry_price': entry_price,
                'sl_price': sl_price,
                'tp_price': tp_price,
                'trade_obj': trade
            }
    
    # Hitung metrics
    if not trades:
        return BacktestResult(
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            total_pnl_pct=0.0,
            total_pnl_usd=0.0,
            max_drawdown_pct=0.0,
            avg_win_pct=0.0,
            avg_loss_pct=0.0,
            profit_factor=0.0,
            trades_per_day=0.0,
            best_trade=None,
            worst_trade=None,
            trades=[]
        )
    
    winning_trades = [t for t in trades if t.pnl_pct &gt; 0]
    losing_trades = [t for t in trades if t.pnl_pct &lt;= 0]
    
    total_pnl_usd = sum(t.pnl_usd for t in trades)
    total_pnl_pct = (total_pnl_usd / initial_capital) * 100
    
    # Max drawdown
    drawdowns = []
    current_peak = equity_curve[0]
    for eq in equity_curve:
        if eq &gt; current_peak:
            current_peak = eq
        drawdown = ((current_peak - eq) / current_peak) * 100
        drawdowns.append(drawdown)
    max_drawdown_pct = max(drawdowns) if drawdowns else 0
    
    avg_win_pct = np.mean([t.pnl_pct for t in winning_trades]) if winning_trades else 0
    avg_loss_pct = np.mean([t.pnl_pct for t in losing_trades]) if losing_trades else 0
    
    gross_profit = sum(t.pnl_usd for t in winning_trades) if winning_trades else 0
    gross_loss = abs(sum(t.pnl_usd for t in losing_trades)) if losing_trades else 1
    profit_factor = gross_profit / gross_loss if gross_loss &gt; 0 else float('inf')
    
    # Trades per day
    if len(trades) &gt;= 2:
        start_ts = trades[0].timestamp
        end_ts = trades[-1].timestamp
        days = (end_ts - start_ts) / (1000 * 60 * 60 * 24)
        trades_per_day = len(trades) / max(days, 1)
    else:
        trades_per_day = 0
    
    best_trade = max(trades, key=lambda t: t.pnl_pct) if trades else None
    worst_trade = min(trades, key=lambda t: t.pnl_pct) if trades else None
    
    return BacktestResult(
        total_trades=len(trades),
        winning_trades=len(winning_trades),
        losing_trades=len(losing_trades),
        win_rate=len(winning_trades) / len(trades) if trades else 0,
        total_pnl_pct=total_pnl_pct,
        total_pnl_usd=total_pnl_usd,
        max_drawdown_pct=max_drawdown_pct,
        avg_win_pct=avg_win_pct,
        avg_loss_pct=avg_loss_pct,
        profit_factor=profit_factor,
        trades_per_day=trades_per_day,
        best_trade=best_trade,
        worst_trade=worst_trade,
        trades=trades
    )


# ─────────────────────────────────────────────────────────────────────────────
#  PARAMETER OPTIMIZATION
# ─────────────────────────────────────────────────────────────────────────────
def optimize_parameters(
    df,
    symbol: str,
    target_trades_per_day = (5, 7)
):
    """
    Optimasi parameter untuk mendapatkan target trades per hari dengan WR tinggi.
    """
    print(f"\n[OPTIMIZE] Mulai optimasi untuk {symbol}...")
    print(f"[OPTIMIZE] Target: {target_trades_per_day[0]}-{target_trades_per_day[1]} trades/hari")
    
    best_params = None
    best_result = None
    best_score = -float('inf')
    
    # Parameter grid
    param_grid = {
        'min_rsi': [45, 50, 52, 55],
        'max_rsi': [60, 65, 70, 75],
        'min_volume_ratio': [1.2, 1.5, 1.8, 2.0],
        'atr_sl_mult': [0.8, 1.0, 1.2, 1.5],
        'atr_tp_mult': [1.0, 1.5, 2.0, 2.5],
        'require_trend': [True, False]
    }
    
    total_iterations = (len(param_grid['min_rsi']) * len(param_grid['max_rsi']) *
                       len(param_grid['min_volume_ratio']) * len(param_grid['atr_sl_mult']) *
                       len(param_grid['atr_tp_mult']) * len(param_grid['require_trend']))
    
    print(f"[OPTIMIZE] Total kombinasi: {total_iterations}")
    
    iteration = 0
    
    for min_rsi in param_grid['min_rsi']:
        for max_rsi in param_grid['max_rsi']:
            if min_rsi &gt;= max_rsi:
                continue
            for min_volume_ratio in param_grid['min_volume_ratio']:
                for atr_sl_mult in param_grid['atr_sl_mult']:
                    for atr_tp_mult in param_grid['atr_tp_mult']:
                        for require_trend in param_grid['require_trend']:
                            
                            params = {
                                'min_rsi': min_rsi,
                                'max_rsi': max_rsi,
                                'min_volume_ratio': min_volume_ratio,
                                'atr_sl_mult': atr_sl_mult,
                                'atr_tp_mult': atr_tp_mult,
                                'require_trend': require_trend
                            }
                            
                            result = run_backtest(df, symbol, params)
                            
                            # Score: kombinasi WR, profit factor, dan trades per day
                            trades_in_target = (target_trades_per_day[0] &lt;= result.trades_per_day &lt;= target_trades_per_day[1])
                            
                            if result.total_trades &gt;= 10 and result.win_rate &gt; 0.5:
                                # Hitung score
                                score = (
                                    result.win_rate * 100 +  # WR tinggi
                                    result.profit_factor * 10 +  # PF tinggi
                                    (result.total_pnl_usd / 10)  # Profit tinggi
                                )
                                
                                # Bonus jika trades per day sesuai target
                                if trades_in_target:
                                    score += 50
                                
                                # Penalti jika drawdown terlalu besar
                                if result.max_drawdown_pct &gt; 20:
                                    score -= 30
                                
                                if score &gt; best_score:
                                    best_score = score
                                    best_params = params
                                    best_result = result
                                    
                                    print(f"\n{'='*80}")
                                    print(f"[NEW BEST] Iterasi {iteration}/{total_iterations}")
                                    print(f"Params: {params}")
                                    print(f"Trades: {result.total_trades} | WR: {result.win_rate*100:.1f}%")
                                    print(f"Profit: ${result.total_pnl_usd:.2f} | PF: {result.profit_factor:.2f}")
                                    print(f"Trades/day: {result.trades_per_day:.1f} | Max DD: {result.max_drawdown_pct:.1f}%")
                                    print(f"{'='*80}")
                            
                            iteration += 1
                            if iteration % 100 == 0:
                                print(f"[OPTIMIZE] Progress: {iteration}/{total_iterations} ({iteration/total_iterations*100:.1f}%)")
    
    return best_params, best_result


# ─────────────────────────────────────────────────────────────────────────────
#  ML MODEL FOR TRADE PREDICTION
# ─────────────────────────────────────────────────────────────────────────────
class CryptoMLModel:
    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.feature_names = None
        self.is_trained = False
    
    def prepare_features(self, df):
        """
        Siapkan features untuk ML model.
        """
        df = df.copy()
        
        features = pd.DataFrame(index=df.index)
        
        # Price features
        features['close'] = df['close']
        features['open'] = df['open']
        features['high'] = df['high']
        features['low'] = df['low']
        
        # EMA features
        features['ema_200'] = df['ema_200']
        features['ema_50'] = df['ema_50']
        features['ema_20'] = df['ema_20']
        features['price_vs_ema200'] = (df['close'] - df['ema_200']) / df['ema_200']
        features['price_vs_ema50'] = (df['close'] - df['ema_50']) / df['ema_50']
        
        # RSI
        features['rsi'] = df['rsi']
        
        # ATR
        features['atr'] = df['atr']
        features['atr_pct'] = df['atr'] / df['close']
        
        # Volume
        features['volume'] = df['vol']
        features['volume_ratio'] = df['volume_ratio']
        
        # Candle features
        features['body_size'] = df['body_size']
        features['body_size_pct'] = df['body_size'] / df['close']
        features['upper_wick'] = df['upper_wick']
        features['lower_wick'] = df['lower_wick']
        features['is_bullish'] = df['is_bullish'].astype(int)
        
        # Momentum
        features['change_1'] = df['change_1']
        features['change_3'] = df['change_3']
        features['change_5'] = df['change_5']
        
        # VWAP
        features['vwap'] = df['vwap']
        features['price_vs_vwap'] = (df['close'] - df['vwap']) / df['vwap']
        
        return features
    
    def prepare_labels(self, df, forward_candles: int = 10):
        """
        Siapkan label: apakah harga akan naik X% dalam N candle ke depan.
        """
        future_returns = df['close'].pct_change(forward_candles).shift(-forward_candles)
        
        # Label: 1 jika return &gt; 1% (profit), 0 otherwise
        labels = (future_returns &gt; 0.01).astype(int)
        
        return labels
    
    def train(self, df, forward_candles: int = 10):
        """
        Train ML model.
        """
        print(f"\n[ML TRAIN] Mulai training model...")
        
        features = self.prepare_features(df)
        labels = self.prepare_labels(df, forward_candles)
        
        # Drop NaN
        data = pd.concat([features, labels], axis=1).dropna()
        features = data.iloc[:, :-1]
        labels = data.iloc[:, -1]
        
        self.feature_names = features.columns.tolist()
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            features, labels, test_size=0.2, shuffle=False
        )
        
        # Scale features
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # Train model
        self.model = GradientBoostingClassifier(
            n_estimators=200,
            learning_rate=0.1,
            max_depth=5,
            random_state=42
        )
        
        self.model.fit(X_train_scaled, y_train)
        
        # Evaluate
        y_pred = self.model.predict(X_test_scaled)
        
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred)
        recall = recall_score(y_test, y_pred)
        f1 = f1_score(y_test, y_pred)
        
        print(f"[ML TRAIN] Accuracy: {accuracy:.4f}")
        print(f"[ML TRAIN] Precision: {precision:.4f}")
        print(f"[ML TRAIN] Recall: {recall:.4f}")
        print(f"[ML TRAIN] F1 Score: {f1:.4f}")
        
        # Feature importance
        if hasattr(self.model, 'feature_importances_'):
            print(f"\n[ML TRAIN] Top 10 Features:")
            importance = sorted(
                zip(self.feature_names, self.model.feature_importances_),
                key=lambda x: x[1], reverse=True
            )[:10]
            for name, imp in importance:
                print(f"  {name}: {imp:.4f}")
        
        self.is_trained = True
        return self
    
    def predict(self, row):
        """
        Prediksi apakah trade akan profitable.
        Return: (probability, should_trade)
        """
        if not self.is_trained or self.model is None:
            return 0.5, True
        
        # Buat DataFrame dari satu row
        df = pd.DataFrame([row])
        features = self.prepare_features(df)
        
        # Scale
        features_scaled = self.scaler.transform(features)
        
        # Predict
        prob = self.model.predict_proba(features_scaled)[0][1]
        
        return prob, prob &gt; 0.6
    
    def save(self, filepath: str = "crypto_ml_model.pkl"):
        """Simpan model ke file."""
        with open(filepath, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'scaler': self.scaler,
                'feature_names': self.feature_names,
                'is_trained': self.is_trained
            }, f)
        print(f"[ML] Model disimpan ke {filepath}")
    
    def load(self, filepath: str = "crypto_ml_model.pkl"):
        """Load model dari file."""
        if os.path.exists(filepath):
            with open(filepath, 'rb') as f:
                data = pickle.load(f)
                self.model = data['model']
                self.scaler = data['scaler']
                self.feature_names = data['feature_names']
                self.is_trained = data['is_trained']
            print(f"[ML] Model di-load dari {filepath}")
        return self


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN: RUN FULL BACKTEST
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("\n" + "="*80)
    print("CRYPTO BOT BACKTESTING ENGINE GILA-GILAAN")
    print("="*80)
    
    # Symbol yang akan di-backtest
    symbols = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT"
    ]
    
    all_results = []
    
    for symbol in symbols[:2]:  # Mulai dengan 2 symbol dulu
        print(f"\n{'#'*80}")
        print(f"PROCESSING: {symbol}")
        print(f"{'#'*80}")
        
        # 1. Fetch historical data
        df = fetch_historical_data(symbol, interval="15m", days=30)
        
        if len(df) &lt; 500:
            print(f"[SKIP] {symbol}: Data tidak cukup")
            continue
        
        # 2. Hitung indikator
        df = calculate_indicators(df)
        
        # 3. Train ML model
        ml_model = CryptoMLModel()
        ml_model.train(df)
        
        # 4. Optimize parameters
        best_params, best_result = optimize_parameters(
            df, symbol, target_trades_per_day=(5, 7)
        )
        
        if best_params and best_result:
            all_results.append({
                'symbol': symbol,
                'params': best_params,
                'result': best_result
            })
            
            # Simpan ML model
            ml_model.save(f"{symbol}_ml_model.pkl")
    
    # Summary
    print(f"\n" + "="*80)
    print("BACKTEST SUMMARY")
    print("="*80)
    
    for res in all_results:
        symbol = res['symbol']
        result = res['result']
        print(f"\n{symbol}:")
        print(f"  Trades: {result.total_trades}")
        print(f"  Win Rate: {result.win_rate*100:.1f}%")
        print(f"  Total Profit: ${result.total_pnl_usd:.2f}")
        print(f"  Profit Factor: {result.profit_factor:.2f}")
        print(f"  Trades/Day: {result.trades_per_day:.1f}")
        print(f"  Max Drawdown: {result.max_drawdown_pct:.1f}%")


if __name__ == "__main__":
    main()
