import requests
import pandas as pd
import numpy as np

print("\n" + "="*80)
print("X-RAY MARKET: MENCARI POLA KORELASI MURNI (10 HARI TERAKHIR)")
print("="*80)

def get_hot_symbols():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    try:
        r = requests.get(url).json()
        df = pd.DataFrame(r)
        df['quoteVolume'] = df['quoteVolume'].astype(float)
        df = df[df['symbol'].str.endswith('USDT')]
        return df.sort_values(by='quoteVolume', ascending=False).head(15)['symbol'].tolist()
    except: return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

def fetch_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1000"
    try:
        r = requests.get(url, timeout=10).json()
        df = pd.DataFrame(r, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        
        # Hitung Indikator Dasar
        df['ema_9'] = df['c'].ewm(span=9).mean()
        df['ema_21'] = df['c'].ewm(span=21).mean()
        df['ema_dist_pct'] = (df['ema_9'] - df['ema_21']) / df['ema_21'] * 100
        
        df['vwap'] = (df['c'] * df['v']).cumsum() / df['v'].cumsum()
        df['vwap_dist_pct'] = (df['c'] - df['vwap']) / df['vwap'] * 100
        
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        
        df['rvol'] = df['v'] / df['v'].rolling(20).mean()
        df['atr_pct'] = ((df['h'] - df['l']) / df['c']).rolling(14).mean() * 100
        
        # TARGET: Apakah dalam 4 candle ke depan (1 Jam), harga naik minimal 4%?
        df['future_max'] = df['h'].rolling(window=4).max().shift(-4)
        df['pump_pct'] = (df['future_max'] - df['c']) / df['c'] * 100
        df['is_pump'] = df['pump_pct'] >= 4.0
        
        return symbol, df.dropna()
    except Exception as e: 
        return symbol, None

def analyze_patterns():
    symbols = get_hot_symbols()
    print(f"Mengumpulkan data dari {len(symbols)} koin paling liquid...\n")
    
    all_pumps = []
    all_duds = []
    
    for sym in symbols:
        _, df = fetch_data(sym)
        if df is not None:
            pumps = df[df['is_pump'] == True]
            duds = df[df['is_pump'] == False].sample(n=len(pumps)*2, replace=True) if len(pumps) > 0 else df.sample(10)
            
            for _, row in pumps.iterrows(): all_pumps.append(row)
            for _, row in duds.iterrows(): all_duds.append(row)
            
    if not all_pumps:
        print("Tidak ada pergerakan Pump signifikan dalam 10 hari terakhir.")
        return
        
    df_pumps = pd.DataFrame(all_pumps)
    df_duds = pd.DataFrame(all_duds)
    
    print("=== PROFIL DATA SEBELUM LEDAKAN HARGA (PUMP > 4%) ===")
    print(f"Total Sampel Ledakan Ditemukan: {len(df_pumps)} momen\n")
    
    # 1. RSI Profiling
    rsi_median = df_pumps['rsi'].median()
    rsi_25 = df_pumps['rsi'].quantile(0.25)
    rsi_75 = df_pumps['rsi'].quantile(0.75)
    print(f"[RSI]        Median: {rsi_median:.1f} | Sebagian besar meledak di range RSI: {rsi_25:.1f} - {rsi_75:.1f}")
    
    # 2. VWAP Profiling
    vwap_median = df_pumps['vwap_dist_pct'].median()
    vwap_25 = df_pumps['vwap_dist_pct'].quantile(0.25)
    vwap_75 = df_pumps['vwap_dist_pct'].quantile(0.75)
    print(f"[VWAP DIST]  Median: {vwap_median:.2f}% | Range ideal: {vwap_25:.2f}% hingga {vwap_75:.2f}% (Jarak dari VWAP)")
    
    # 3. EMA Profiling
    ema_median = df_pumps['ema_dist_pct'].median()
    ema_25 = df_pumps['ema_dist_pct'].quantile(0.25)
    ema_75 = df_pumps['ema_dist_pct'].quantile(0.75)
    print(f"[EMA 9-21]   Median: {ema_median:.2f}% | Range ideal: {ema_25:.2f}% hingga {ema_75:.2f}% (Jarak EMA9 ke EMA21)")
    
    # 4. RVOL Profiling
    rvol_median = df_pumps['rvol'].median()
    rvol_75 = df_pumps['rvol'].quantile(0.75)
    print(f"[RVOL]       Median Volume: {rvol_median:.2f}x lipat dari rata-rata | Kuartil Atas: {rvol_75:.2f}x")
    
    # 5. ATR (Volatility) Profiling
    atr_median = df_pumps['atr_pct'].median()
    print(f"[VOLATILITAS] Median ATR: {atr_median:.2f}% per candle\n")
    
    # CORRELATION (Noise Detection)
    print("=== FEATURE IMPORTANCE (Korelasi Indikator vs Persentase Pump) ===")
    print("Angka mendekati 1.0 atau -1.0 berarti SANGAT PENTING. Angka mendekati 0 berarti NOISE / SAMPAH.\n")
    
    corr_matrix = df_pumps[['pump_pct', 'rsi', 'vwap_dist_pct', 'ema_dist_pct', 'rvol', 'atr_pct']].corr()
    pump_corr = corr_matrix['pump_pct'].sort_values(ascending=False).drop('pump_pct')
    
    for idx, val in pump_corr.items():
        importance = "PENTING" if abs(val) > 0.15 else "NOISE"
        print(f"Korelasi {idx:<15}: {val:>6.3f} => {importance}")
        
    print("\n" + "="*80)

if __name__ == "__main__":
    analyze_patterns()
