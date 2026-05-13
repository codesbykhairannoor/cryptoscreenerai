import requests
import pandas as pd
import time

def audit_binance_ls_impact(symbol="BTCUSDT"):
    print(f"[SENTIMENT] Auditing Binance Long/Short Impact for {symbol}...")
    
    # 1. Ambil data LS Ratio (15m)
    url_ls = f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={symbol}&period=15m&limit=100"
    r_ls = requests.get(url_ls, verify=False)
    ls_data = r_ls.json()
    
    # 2. Ambil data Harga (15m)
    url_price = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=100"
    r_price = requests.get(url_price, verify=False)
    price_data = r_price.json()
    
    # Merge data
    df_ls = pd.DataFrame(ls_data)
    df_price = pd.DataFrame(price_data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'cts', 'qvol', 'tr', 'tbb', 'tbq', 'i'])
    
    # Analisa: Apakah saat LS Ratio > 2.0 (Retail Long), harga cenderung turun?
    # Analisa: Apakah saat LS Ratio < 0.8 (Retail Short), harga cenderung naik?
    
    df_ls['longShortRatio'] = df_ls['longShortRatio'].astype(float)
    df_price['close'] = df_price['close'].astype(float)
    df_price['change'] = df_price['close'].pct_change().shift(-1) * 100 # Change di candle BERIKUTNYA
    
    # Gabungkan (berdasarkan urutan waktu karena limit sama)
    df_ls = df_ls.iloc[::-1].reset_index(drop=True) # Reverse agar urutan dari lama ke baru
    df_price = df_price.iloc[-len(df_ls):].reset_index(drop=True)
    
    results = pd.concat([df_ls['longShortRatio'], df_price['change']], axis=1)
    
    dump_when_long = results[results['longShortRatio'] > 1.8]['change'].mean()
    pump_when_short = results[results['longShortRatio'] < 0.9]['change'].mean()
    
    print("\n" + "="*50)
    print(f"SENTIMENT IMPACT REPORT: {symbol}")
    print("="*50)
    print(f"Avg Price Change when Retail is LONG  (Ratio > 1.8): {dump_when_long:.4f}%")
    print(f"Avg Price Change when Retail is SHORT (Ratio < 0.9): {pump_when_short:.4f}%")
    
    if dump_when_long < 0:
        print(">>> CONFIRMED: High LS Ratio leads to DUMPS. (Institutions Liquidation)")
    if pump_when_short > 0:
        print(">>> CONFIRMED: Low LS Ratio leads to PUMPS. (Short Squeeze)")

audit_binance_ls_impact("BTCUSDT")
audit_binance_ls_impact("SOLUSDT")
audit_binance_ls_impact("ETHUSDT")
