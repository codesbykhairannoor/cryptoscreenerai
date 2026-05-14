import requests
import pandas as pd
import numpy as np

# --- PATTERN DISCOVERY ENGINE v32.0 ---
# Mencari "DNA Kemenangan" dari Koin-Koin Gainer Terakhir

def get_market_winners():
    """Ambil koin yang naik paling tinggi di market saat ini"""
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    r = requests.get(url).json()
    df = pd.DataFrame(r)
    df['priceChangePercent'] = df['priceChangePercent'].astype(float)
    # Koin yang naik > 5% dalam 24 jam terakhir
    winners = df[df['symbol'].str.endswith('USDT') & (df['priceChangePercent'] > 5)]
    return winners.sort_values(by='priceChangePercent', ascending=False).head(10)['symbol'].tolist()

def analyze_winner_dna(symbol):
    """Bedah apa yang terjadi tepat sebelum koin ini meledak"""
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=100"
    try:
        r = requests.get(url).json()
        df = pd.DataFrame(r, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
        
        # Cari moment ledakan (kenaikan > 3% dalam 1 candle 15m)
        df['change'] = ((df['c'] - df['o']) / df['o']) * 100
        explosion_idx = df[df['change'] > 3].index
        
        if len(explosion_idx) == 0: return None
        
        dna_results = []
        for idx in explosion_idx:
            if idx < 10: continue
            # Ambil data TEPAT 1 candle sebelum ledakan (T-1)
            before = df.iloc[idx-1]
            
            # Ekstrak DNA
            ema9 = df['c'].ewm(span=9).mean()
            ema21 = df['c'].ewm(span=21).mean()
            rsi = 100 - (100 / (1 + (df['c'].diff().where(df['c'].diff() > 0, 0).rolling(14).mean() / -df['c'].diff().where(df['c'].diff() < 0, 0).rolling(14).mean())))
            vwap = (df['c'] * df['v']).cumsum() / df['v'].cumsum()
            
            dna = {
                'ema_cross': ema9.iloc[idx-1] > ema21.iloc[idx-1],
                'rsi_before': round(rsi.iloc[idx-1], 2),
                'below_vwap': before['c'] < vwap.iloc[idx-1],
                'vol_spike': before['v'] > df['v'].iloc[idx-10:idx-1].mean() * 1.5
            }
            dna_results.append(dna)
        return dna_results
    except: return None

def main():
    print("\n" + "="*80)
    print("PATTERN DISCOVERY ENGINE: MEMBONGKAR DNA PARA PEMENANG")
    print("="*80)
    
    winners = get_market_winners()
    print(f"Menganalisis {len(winners)} koin pemenang: {winners}")
    
    all_dna = []
    for s in winners:
        dna = analyze_winner_dna(s)
        if dna: all_dna.extend(dna)
    
    if not all_dna:
        print("Tidak ditemukan pola ledakan yang cukup jelas.")
        return

    # Hitung Statistik DNA (Filter out NaNs)
    all_dna = [d for d in all_dna if not np.isnan(d['rsi_before'])]
    total = len(all_dna)
    if total == 0:
        print("Tidak ditemukan data DNA yang valid.")
        return

    ema_match = len([d for d in all_dna if d['ema_cross']]) / total * 100
    vwap_match = len([d for d in all_dna if d['below_vwap']]) / total * 100
    vol_match = len([d for d in all_dna if d['vol_spike']]) / total * 100
    avg_rsi = sum([d['rsi_before'] for d in all_dna]) / total
    
    print("\n" + "="*80)
    print(f"HASIL ANALISIS POLA (Berdasarkan {total} Kejadian Ledakan):")
    print("-" * 80)
    print(f"1. EMA 9 > 21 (Golden Cross)   : {ema_match:.1f}% Kejadian")
    print(f"2. Harga DI BAWAH VWAP         : {vwap_match:.1f}% Kejadian")
    print(f"3. Lonjakan Volume (Volume+)   : {vol_match:.1f}% Kejadian")
    print(f"4. Rata-rata RSI Sebelum Pump  : {avg_rsi:.1f}")
    print("="*80)
    
    print("\nKESIMPULAN DNA PEMENANG:")
    pattern = "CARI KOIN YANG: "
    if ema_match > 60: pattern += "EMA 9 > 21 + "
    if vwap_match < 50: pattern += "DI ATAS VWAP (Trend+) + "
    if vol_match > 50: pattern += "VOLUME MELEDAK + "
    pattern += f"RSI Sekitar {round(avg_rsi)}"
    print(f" >> {pattern}")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
