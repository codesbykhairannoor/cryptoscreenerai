
"""
TEST BACKTESTING ENGINE - Sederhana
"""

import sys
import os

# Import modul kita
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest_engine import (
    fetch_historical_data,
    calculate_indicators,
    run_backtest,
    CryptoMLModel
)

def main():
    print("Testing Backtest Engine...")
    
    # 1. Fetch data BTCUSDT
    symbol = "BTCUSDT"
    print(f"\nFetching {symbol} data...")
    df = fetch_historical_data(symbol, interval="15m", days=7)
    
    if len(df) &lt; 100:
        print("Data tidak cukup!")
        return
    
    print(f"Data berhasil diambil: {len(df)} candles")
    
    # 2. Hitung indikator
    print("\nCalculating indicators...")
    df = calculate_indicators(df)
    print(f"Indikator selesai: {len(df)} data points")
    
    # 3. Test backtest sederhana
    print("\nRunning simple backtest...")
    params = {
        'min_rsi': 50,
        'max_rsi': 65,
        'min_volume_ratio': 1.5,
        'atr_sl_mult': 1.0,
        'atr_tp_mult': 1.5,
        'require_trend': True
    }
    
    result = run_backtest(df, symbol, params)
    
    print("\n" + "="*50)
    print("BACKTEST RESULT")
    print("="*50)
    print(f"Total Trades: {result.total_trades}")
    print(f"Winning Trades: {result.winning_trades}")
    print(f"Losing Trades: {result.losing_trades}")
    print(f"Win Rate: {result.win_rate*100:.1f}%")
    print(f"Total Profit: ${result.total_pnl_usd:.2f}")
    print(f"Profit Factor: {result.profit_factor:.2f}")
    print(f"Trades/Day: {result.trades_per_day:.1f}")
    print(f"Max Drawdown: {result.max_drawdown_pct:.1f}%")
    print("="*50)
    
    # 4. Test ML model
    print("\nTesting ML Model...")
    ml_model = CryptoMLModel()
    ml_model.train(df)
    ml_model.save("test_ml_model.pkl")
    print("\n[OK] Test selesai!")

if __name__ == "__main__":
    main()



