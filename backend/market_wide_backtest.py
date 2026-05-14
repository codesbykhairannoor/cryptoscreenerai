import requests
import pandas as pd
import numpy as np
import concurrent.futures

# --- MARKET-WIDE AUTONOMOUS BACKTEST v31.7 ---
# Bot memilih koin sendiri dari seluruh market Bitget/Binance

def get_all_hot_symbols():
    """Ambil top 30 koin dengan volume tertinggi saat ini (Real-time Scanner)"""
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    r = requests.get(url).json()
    # Filter: Volume > $20M dan simbol USDT
    df = pd.DataFrame(r)
    df['quoteVolume'] = df['quoteVolume'].astype(float)
    df = df[df['symbol'].str.endswith('USDT')]
    top_df = df.sort_values(by='quoteVolume', ascending=False).head(30)
    return top_df['symbol'].tolist()

def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1000"
    try:
        r = requests.get(url, timeout=10)
        df = pd.DataFrame(r.json(), columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
        return symbol, df.dropna()
    except:
        return symbol, None

def run_simulation(symbol, df):
    """Simulasi Strategi v31.7 per koin"""
    if df is None or len(df) < 200: return None
    
    # Pre-calculate Tech
    df['ema_9'] = df['c'].ewm(span=9).mean()
    df['ema_21'] = df['c'].ewm(span=21).mean()
    df['atr'] = (df['h'] - df['l']).rolling(14).mean()
    df['rvol'] = df['v'] / df['v'].rolling(20).mean()
    df['is_bullish'] = df['c'] > df['o']
    
    balance = 10.0
    margin = 3.0
    lev = 10
    fee = 0.0006
    in_pos = None
    trades = []
    tsl_saves = 0
    
    for i in range(50, len(df)):
        row = df.iloc[i]
        
        if in_pos:
            cpnl = ((row['c'] - in_pos['ent'])/in_pos['ent']) * lev * 100
            if in_pos['side'] == 'sell': cpnl = -cpnl
            if cpnl > in_pos['peak']: in_pos['peak'] = cpnl
            
            # Step-Trailing SL 10%
            if in_pos['peak'] >= 10:
                locked = (int(in_pos['peak'] / 10) * 10) - 5
                new_sl = in_pos['ent'] * (1 + (locked/100)/lev) if in_pos['side'] == 'buy' else in_pos['ent'] * (1 - (locked/100)/lev)
                if in_pos['side'] == 'buy':
                    if new_sl > in_pos['sl']: in_pos['sl'] = new_sl
                else:
                    if new_sl < in_pos['sl']: in_pos['sl'] = new_sl

            # Exit logic
            exit_price = 0
            if in_pos['side'] == 'buy':
                if row['l'] <= in_pos['sl']: exit_price = in_pos['sl']
                elif row['h'] >= in_pos['tp']: exit_price = in_pos['tp']
            else:
                if row['h'] >= in_pos['sl']: exit_price = in_pos['sl']
                elif row['l'] <= in_pos['tp']: exit_price = in_pos['tp']
            
            if exit_price > 0:
                final_pnl = ((exit_price - in_pos['ent'])/in_pos['ent']) * lev * 100
                if in_pos['side'] == 'sell': final_pnl = -final_pnl
                net = (final_pnl/100 * margin) - (margin * lev * fee * 2)
                balance += net
                if net > 0 and exit_price == in_pos['sl']: tsl_saves += 1
                trades.append(net)
                in_pos = None
            continue

        # Entry Logic (Mock Pump Score based on momentum)
        if row['ema_9'] > row['ema_21'] and row['rvol'] > 1.5 and row['is_bullish']:
            in_pos = {
                'side': 'buy', 'ent': row['c'], 'peak': 0, 
                'sl': row['c'] - (row['atr'] * 1.5), 
                'tp': row['c'] + (row['atr'] * 4.0)
            }
            
    return {
        'symbol': symbol,
        'final_balance': round(balance, 2),
        'total_trades': len(trades),
        'win_rate': round(len([t for t in trades if t > 0]) / len(trades) * 100, 1) if trades else 0,
        'tsl_saves': tsl_saves
    }

def main():
    print("\n" + "="*85)
    print("MARKET-WIDE AUTONOMOUS BACKTEST: THE PREDATOR'S AUDIT")
    print("Bot Memilih Sendiri Top 30 Koin Paling Aktif di Market Saat Ini")
    print("="*85)
    
    symbols = get_all_hot_symbols()
    print(f"Scanning {len(symbols)} koin paling hot...")
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_data = {executor.submit(fetch_data, s): s for s in symbols}
        for future in concurrent.futures.as_completed(future_to_data):
            sym, df = future.result()
            res = run_simulation(sym, df)
            if res: results.append(res)
    
    # Sort by profit
    results.sort(key=lambda x: x['final_balance'], reverse=True)
    
    print(f"\n{'RANK':<4} | {'SYMBOL':<12} | {'FINAL BAL':<10} | {'TRADES':<7} | {'WR %':<7} | {'TSL SAVES'}")
    print("-" * 85)
    for idx, r in enumerate(results[:20]):
        print(f"{idx+1:<4} | {r['symbol']:<12} | ${r['final_balance']:<9} | {r['total_trades']:<7} | {r['win_rate']:<7} | {r['tsl_saves']}x")
    
    print("="*85)
    avg_bal = sum([r['final_balance'] for r in results]) / len(results)
    total_trades = sum([r['total_trades'] for r in results])
    print(f"RATA-RATA SALDO AKHIR PER KOIN (15 HARI): ${avg_bal:.2f}")
    print(f"ESTIMASI TOTAL TRADE HARIAN (Market Wide): {round(total_trades/15)} trade/hari")
    print("="*85 + "\n")

if __name__ == "__main__":
    main()
