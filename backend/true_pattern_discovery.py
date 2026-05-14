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
        
        # TARGET EXTREME: MEGA PUMP (>10%) atau MEGA DUMP (<-10%) dalam 4 candle (1 Jam)
        # Di leverage 10x, pergerakan 10% = 100% PnL (Home Run / Margin Call)
        df['future_max'] = df['h'].rolling(window=4).max().shift(-4)
        df['future_min'] = df['l'].rolling(window=4).min().shift(-4)
        
        df['pump_pct'] = (df['future_max'] - df['c']) / df['c'] * 100
        df['dump_pct'] = (df['future_min'] - df['c']) / df['c'] * 100
        
        # Kita ambil pergerakan paling ekstrim (absolute percentage)
        df['extreme_move_pct'] = np.where(abs(df['pump_pct']) > abs(df['dump_pct']), df['pump_pct'], df['dump_pct'])
        
        # Flagging: Apakah terjadi Tsunami Harga (PUMP/DUMP > 10% di harga aslinya)?
        df['is_mega_move'] = abs(df['extreme_move_pct']) >= 10.0
        
        return symbol, df.dropna()
    except Exception as e: 
        return symbol, None

def analyze_patterns():
    symbols = get_hot_symbols()
    print(f"Mencari TSUNAMI HARGA (MEGA PUMP/DUMP > 10%) dari {len(symbols)} koin paling liquid...\n")
    
    all_megas = []
    all_duds = []
    
    for sym in symbols:
        _, df = fetch_data(sym)
        if df is not None:
            megas = df[df['is_mega_move'] == True]
            # Kita ambil random noise untuk pembanding
            duds = df[df['is_mega_move'] == False].sample(n=len(megas)*2, replace=True) if len(megas) > 0 else df.sample(10)
            
            for _, row in megas.iterrows(): all_megas.append(row)
            for _, row in duds.iterrows(): all_duds.append(row)
            
    if not all_megas:
        print("TIDAK ADA MEGA PUMP/DUMP (>10%) DALAM 10 HARI TERAKHIR PADA KOIN TOP!")
        return
        
    df_megas = pd.DataFrame(all_megas)
    df_duds = pd.DataFrame(all_duds)
    
    print("=== PROFIL DATA SEBELUM TSUNAMI HARGA (>10% HARGA ASLI / 100% PnL) ===")
    print(f"Total Sampel Ledakan Ekstrim Ditemukan: {len(df_megas)} momen\n")
    
    # 1. RSI Profiling
    rsi_median = df_megas['rsi'].median()
    rsi_25 = df_megas['rsi'].quantile(0.25)
    rsi_75 = df_megas['rsi'].quantile(0.75)
    print(f"[RSI]        Median: {rsi_median:.1f} | Sebagian besar meledak di range RSI: {rsi_25:.1f} - {rsi_75:.1f}")
    
    # 2. VWAP Profiling
    vwap_median = df_megas['vwap_dist_pct'].median()
    vwap_25 = df_megas['vwap_dist_pct'].quantile(0.25)
    vwap_75 = df_megas['vwap_dist_pct'].quantile(0.75)
    print(f"[VWAP DIST]  Median: {vwap_median:.2f}% | Range ideal: {vwap_25:.2f}% hingga {vwap_75:.2f}% (Jarak dari VWAP)")
    
    # 3. EMA Profiling
    ema_median = df_megas['ema_dist_pct'].median()
    ema_25 = df_megas['ema_dist_pct'].quantile(0.25)
    ema_75 = df_megas['ema_dist_pct'].quantile(0.75)
    print(f"[EMA 9-21]   Median: {ema_median:.2f}% | Range ideal: {ema_25:.2f}% hingga {ema_75:.2f}% (Jarak EMA9 ke EMA21)")
    
    # 4. RVOL Profiling
    rvol_median = df_megas['rvol'].median()
    rvol_75 = df_megas['rvol'].quantile(0.75)
    print(f"[RVOL]       Median Volume: {rvol_median:.2f}x lipat dari rata-rata | Kuartil Atas: {rvol_75:.2f}x")
    
    # 5. ATR (Volatility) Profiling
    atr_median = df_megas['atr_pct'].median()
    print(f"[VOLATILITAS] Median ATR: {atr_median:.2f}% per candle\n")
    
    # CORRELATION (Noise Detection)
    print("=== FEATURE IMPORTANCE (Korelasi Indikator vs Persentase Ekstrim) ===")
    print("Angka mendekati 1.0 atau -1.0 berarti SANGAT PENTING. Angka mendekati 0 berarti NOISE / SAMPAH.\n")
    
    # Kita absolutekan karena ada Mega Pump (+) dan Mega Dump (-)
    df_megas['abs_extreme'] = df_megas['extreme_move_pct'].abs()
    
    corr_matrix = df_megas[['abs_extreme', 'rsi', 'vwap_dist_pct', 'ema_dist_pct', 'rvol', 'atr_pct']].corr()
    pump_corr = corr_matrix['abs_extreme'].sort_values(ascending=False).drop('abs_extreme')
    
    for idx, val in pump_corr.items():
        importance = "PENTING" if abs(val) > 0.15 else "NOISE"
        print(f"Korelasi {idx:<15}: {val:>6.3f} => {importance}")
        
    print("\n" + "="*80)

if __name__ == "__main__":
    analyze_patterns()



