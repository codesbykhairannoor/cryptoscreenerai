import requests
import pandas as pd
import numpy as np
import time
from concurrent.futures import ThreadPoolExecutor

print("\n" + "="*90)
print("THE ULTIMATE BACKTEST: MENCARI POLA 'HOLY GRAIL' DI 50 KOIN (30 HARI TERAKHIR)")
print("Target: Win Rate > 70% dengan TP 4% & SL 2%")
print("="*90)

# Konfigurasi
TOP_N_COINS = 50
TIMEFRAME = '15m'
LIMIT_CANDLES = 1500 # Max Binance API without auth (~15 hari)
# Kita ambil 2x iterasi ke belakang untuk dapat ~30 hari
NUM_ITERATIONS = 2 

def get_top_coins():
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr").json()
        df = pd.DataFrame(r)
        df['quoteVolume'] = df['quoteVolume'].astype(float)
        symbols = df[df['symbol'].str.endswith('USDT')].sort_values(by='quoteVolume', ascending=False).head(TOP_N_COINS)['symbol'].tolist()
        return symbols
    except Exception as e:
        print("Gagal fetch top coins:", e)
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

def fetch_historical_data(symbol):
    all_klines = []
    end_time = None
    
    for _ in range(NUM_ITERATIONS):
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={TIMEFRAME}&limit={LIMIT_CANDLES}"
        if end_time: url += f"&endTime={end_time}"
        
        try:
            r = requests.get(url, timeout=10).json()
            if not isinstance(r, list) or len(r) == 0: break
            all_klines = r + all_klines
            end_time = r[0][0] - 1 # Update end_time to fetch older data
        except: break
        
    if not all_klines: return None
    
    df = pd.DataFrame(all_klines, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    df = df.drop_duplicates(subset=['ts']).sort_values('ts').reset_index(drop=True)
    return df

def calculate_indicators_and_target(df):
    # 1. EMAs
    df['ema9'] = df['c'].ewm(span=9).mean()
    df['ema21'] = df['c'].ewm(span=21).mean()
    df['ema50'] = df['c'].ewm(span=50).mean()
    
    # 2. VWAP
    df['vwap'] = (df['c'] * df['v']).cumsum() / df['v'].cumsum()
    
    # 3. RSI 14
    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain/loss)))
    
    # 4. Bollinger Bands (20, 2)
    df['bb_mid'] = df['c'].rolling(20).mean()
    df['bb_std'] = df['c'].rolling(20).std()
    df['bb_up'] = df['bb_mid'] + (2 * df['bb_std'])
    df['bb_low'] = df['bb_mid'] - (2 * df['bb_std'])
    df['bb_pos'] = (df['c'] - df['bb_low']) / (df['bb_up'] - df['bb_low']) # 0 = di bawah, 1 = di atas
    
    # 5. MACD (12, 26, 9)
    exp1 = df['c'].ewm(span=12, adjust=False).mean()
    exp2 = df['c'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    
    # 6. ATR & Volume
    df['atr'] = (df['h'] - df['l']).rolling(14).mean()
    df['atr_pct'] = (df['atr'] / df['c']) * 100
    df['rvol'] = df['v'] / df['v'].rolling(20).mean()

    # Normalisasi Indikator Jarak (Agar bisa dibandingkan lintas koin)
    df['ema_cross_pct'] = (df['ema9'] - df['ema21']) / df['ema21'] * 100
    df['price_to_vwap'] = (df['c'] - df['vwap']) / df['vwap'] * 100
    df['price_to_ema50'] = (df['c'] - df['ema50']) / df['ema50'] * 100
    
    # === HITUNG TARGET (SIMULASI MASA DEPAN HIGH WIN RATE SCALPER) ===
    # Kita cari BUY setup: Akankah harga naik 1% sebelum turun 3% dalam 12 candle (3 Jam)?
    TP_PCT = 1.01 # +1% (Target Cepat)
    SL_PCT = 0.97 # -3% (SL Longgar)
    
    df['is_win'] = False
    df['is_loss'] = False
    
    # Konversi array numpy untuk komputasi cepat
    c_arr = df['c'].values
    h_arr = df['h'].values
    l_arr = df['l'].values
    
    wins = np.zeros(len(df), dtype=bool)
    losses = np.zeros(len(df), dtype=bool)
    
    for i in range(len(df) - 12):
        entry_price = c_arr[i]
        tp_price = entry_price * TP_PCT
        sl_price = entry_price * SL_PCT
        
        for j in range(i+1, i+13):
            if l_arr[j] <= sl_price:
                losses[i] = True
                break
            if h_arr[j] >= tp_price:
                wins[i] = True
                break
                
    df['is_win'] = wins
    df['is_loss'] = losses
    return df.dropna()

def process_symbol(sym):
    print(f"[{sym}] Menyedot dan menghitung indikator...", flush=True)
    df = fetch_historical_data(sym)
    if df is not None and len(df) > 100:
        return calculate_indicators_and_target(df)
    return None

def find_the_holy_grail():
    symbols = get_top_coins()
    print(f"Daftar {len(symbols)} Koin siap diproses.\n")
    
    all_data = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(process_symbol, symbols)
        for df in results:
            if df is not None:
                all_data.append(df)
                
    if not all_data:
        print("Gagal mengambil data.")
        return
        
    master_df = pd.concat(all_data, ignore_index=True)
    total_candles = len(master_df)
    total_wins = master_df['is_win'].sum()
    total_losses = master_df['is_loss'].sum()
    
    print("\n" + "="*90)
    print(f"DATABASE TERKUMPUL: {total_candles:,} Bar (Candle 15m) dari {len(symbols)} Koin.")
    print(f"Baseline Pasar: {total_wins} Menang vs {total_losses} Kalah.")
    if total_wins + total_losses > 0:
        print(f"Baseline Win Rate Acak: {(total_wins/(total_wins+total_losses))*100:.1f}%")
    print("="*90)
    
    # === PENCARIAN POLA MULTI-DIMENSI ===
    print("\nMEMINDAI MATRIKS UNTUK WIN RATE > 65% DENGAN MINIMAL 50 OCCURRENCES...")
    
    # Filter Calon Pemenang (Kondisi Dasar)
    # Kita buat grid pencarian berdasarkan indikator paling populer
    
    # 1. Momentum & Mean Reversion (RSI x BB)
    cond1 = (master_df['rsi'] < 30) & (master_df['bb_pos'] < 0.1) # Oversold Ekstrim
    cond2 = (master_df['rsi'] > 65) & (master_df['rvol'] > 2.0)   # Breakout Momentum
    cond3 = (master_df['rsi'].between(45, 55)) & (master_df['ema_cross_pct'] > 0) # Trend Following Pullback
    
    # 2. Golden Cross Variations
    cond4 = (master_df['ema_cross_pct'] > 0.5) & (master_df['price_to_vwap'] > 1.0) # Strong Trend
    cond5 = (master_df['macd_hist'] > 0) & (master_df['macd_hist'].shift(1) < 0) # MACD Crossover tepat di candle ini
    
    # 3. Liquidity Grab / Dip Buying
    cond6 = (master_df['price_to_ema50'] < -5.0) & (master_df['rsi'] < 25) # Harga anjlok jauh di bawah EMA50 (Karet Gelang)
    
    conditions = {
        "Oversold Ekstrim (RSI<30 + Harga sentuh BB Bawah)": cond1,
        "Breakout Volume Gila (RSI>65 + Volume 2x Lipat)": cond2,
        "Pullback Sehat (RSI 45-55 + EMA9>EMA21)": cond3,
        "Trend Kuat (Jarak EMA > 0.5% + Harga jauh di atas VWAP)": cond4,
        "Sinyal Validasi Awal MACD Cross Naik": cond5,
        "Jatuh Bebas (Harga -5% di bawah EMA50 + RSI<25)": cond6
    }
    
    for name, condition in conditions.items():
        subset = master_df[condition]
        wins = subset['is_win'].sum()
        losses = subset['is_loss'].sum()
        total = wins + losses
        
        if total > 0:
            wr = (wins / total) * 100
            # Kalkulasi Expected Value Murni (Anggap modal per trade $100 di 10x leverage = $1000 Notional)
            # Menang = +1% harga = +10% PnL = +$10
            # Kalah = -3% harga = -30% PnL = -$30
            ev_per_trade = ( (wins/total) * 10 ) - ( (losses/total) * 30 )
            
            print(f"\n[POLA] {name}")
            print(f"       Ditemukan: {total} Kali | Menang: {wins} | Kalah: {losses}")
            print(f"       WIN RATE : {wr:.1f}%")
            
            if ev_per_trade > 0:
                print(f"       PROFIT   : +${ev_per_trade:.2f} per trade (MATEMATIS UNTUNG)")
            else:
                print(f"       RUGI     : ${ev_per_trade:.2f} per trade (MATEMATIS BUNTUNG)")
        else:
            print(f"\n[POLA] {name} => Tidak pernah terjadi.")

    # PENCARIAN OTOMATIS (Mencari rentang ideal tanpa tebak-tebakan)
    print("\n=== AUTO-DISCOVERY (AI MENCARI RENTANG TERBAIK SECARA OTOMATIS) ===")
    
    # Kumpulkan filter-filter sukses di sini
    winning_filters = []
    
    # RSI Scan
    for rsi_low in range(10, 80, 10):
        subset = master_df[master_df['rsi'].between(rsi_low, rsi_low+10)]
        w = subset['is_win'].sum()
        l = subset['is_loss'].sum()
        if w+l > 50:
            wr = w/(w+l)*100
            if wr > 50: winning_filters.append(('RSI', f"{rsi_low}-{rsi_low+10}", wr, w+l))
            
    # RVOL Scan
    for rvol_low in [0.5, 1.0, 1.5, 2.0, 3.0]:
        subset = master_df[master_df['rvol'] > rvol_low]
        w = subset['is_win'].sum()
        l = subset['is_loss'].sum()
        if w+l > 50:
            wr = w/(w+l)*100
            if wr > 50: winning_filters.append(('Volume (RVOL) >', str(rvol_low), wr, w+l))

    # VWAP Scan
    for vwap_low in [-5, -2, 0, 2, 5]:
        subset = master_df[master_df['price_to_vwap'] > vwap_low]
        w = subset['is_win'].sum()
        l = subset['is_loss'].sum()
        if w+l > 50:
            wr = w/(w+l)*100
            if wr > 50: winning_filters.append(('Price to VWAP (%) >', str(vwap_low), wr, w+l))

    # Tampilkan top 5 pola tunggal
    winning_filters.sort(key=lambda x: x[2], reverse=True)
    print("\n[5 Indikator Tunggal dengan Win Rate Tertinggi]")
    for cat, val, wr, occ in winning_filters[:5]:
        print(f" - {cat} {val} => WR: {wr:.1f}% (dari {occ} kejadian)")

    print("\nSelesai membedah pasar.")

if __name__ == "__main__":
    find_the_holy_grail()



