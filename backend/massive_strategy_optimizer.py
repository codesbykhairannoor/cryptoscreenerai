import requests
import pandas as pd
import time
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CONFIG OPTIMIZER ---
COINS_TO_TEST = 50
SCENARIOS = [
    # (TP%, SL%, RSI, RVOL)
    (2.0, 2.0, 65, 2.0),
    (3.0, 3.0, 65, 2.0),
    (4.0, 4.0, 65, 2.0),
    (4.0, 5.0, 65, 2.0), # Current Champion (v39.0)
    (5.0, 5.0, 70, 2.5), # Ultra Conservative
    (2.0, 1.5, 60, 1.5), # Aggressive Scalp
    (6.0, 4.0, 65, 2.0), # High RR
    (4.0, 2.0, 65, 2.0), # Tight SL
    (2.0, 4.0, 65, 2.0), # Wide SL
]

def fetch_data(symbol):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        # Limit 200 candle (lebih aman dibanding 1000)
        url = f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&granularity=15m&limit=200&productType=USDT-FUTURES"
        r = requests.get(url, timeout=10, verify=False, headers=headers)
        if r.status_code != 200:
            print(f"[DEBUG] {symbol} Failed: HTTP {r.status_code}")
            return symbol, None
        
        rj = r.json()
        if rj.get('code') != '00000':
            print(f"[DEBUG] {symbol} API Error: {rj.get('msg')}")
            return symbol, None

        data = rj.get('data', [])
        if not data: return symbol, None
        
        df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'vol_usd'])
        df[['open', 'high', 'low', 'close', 'vol']] = df[['open', 'high', 'low', 'close', 'vol']].astype(float)
        df = df.iloc[::-1].reset_index(drop=True)
        return symbol, df
    except:
        pass
    return symbol, None

def run_backtest(df, tp_pct, sl_pct, rsi_min, rvol_min):
    if df is None or len(df) < 50: return 0, 0, 0
    
    trades = 0
    wins = 0
    total_pnl = 0
    in_position_until = 0
    
    closes = df['close']
    delta = closes.diff()
    gain = (delta.where(delta > 0, 0)).ewm(span=14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(span=14, adjust=False).mean()
    rs = gain / loss
    rsi_vals = 100 - (100 / (1 + rs))

    for i in range(30, len(df) - 1):
        if i < in_position_until: continue # SEDANG DALAM TRADE, SKIP.

        rsi = rsi_vals.iloc[i]
        avg_vol = df['vol'].iloc[i-20:i].mean()
        cur_vol = df['vol'].iloc[i]
        rvol = cur_vol / avg_vol if avg_vol > 0 else 1
        
        if rsi > rsi_min and rvol > rvol_min:
            entry_p = df['close'].iloc[i]
            tp_p = entry_p * (1 + tp_pct/100)
            sl_p = entry_p * (1 - sl_pct/100)
            
            trades += 1
            # Cari candle mana yang kena duluan (TP atau SL)
            outcome_found = False
            for j in range(i+1, len(df)):
                if df['high'].iloc[j] >= tp_p:
                    wins += 1
                    total_pnl += tp_pct
                    in_position_until = j + 1
                    outcome_found = True
                    break
                if df['low'].iloc[j] <= sl_p:
                    total_pnl -= sl_pct
                    in_position_until = j + 1
                    outcome_found = True
                    break
            
            if not outcome_found:
                in_position_until = len(df)
                
    return trades, wins, total_pnl

print(f"\n{'='*65}")
print(f"   STRATEGY OPTIMIZER MASSAL - 50 KOIN (5 HARI DATA)")
print(f"{'='*65}")

# Get liquid candidates
try:
    url_tickers = "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
    r_t = requests.get(url_tickers, verify=False)
    tickers = r_t.json().get('data', [])
    if tickers:
        print(f"[DEBUG] Full ticker sample: {tickers[0]}")
    # Filter koin dengan volume harian > $5M (agar lebih banyak koin masuk)
    candidates = [t['symbol'] for t in tickers if float(t.get('baseVolume', 0)) > 5000000][:COINS_TO_TEST]
    if not candidates:
        print(f"[DEBUG] Tickers found: {len(tickers)}, but none match volume > $5M")
except Exception as e:
    print(f"[ERROR] Gagal ambil list koin: {e}")
    exit()

print(f"[1/2] Menarik data history {len(candidates)} koin...")
print(f"[DEBUG] Sampel kandidat: {candidates[:5]}")
all_data = {}
with ThreadPoolExecutor(max_workers=15) as executor:
    futures = [executor.submit(fetch_data, s) for s in candidates]
    for f in as_completed(futures):
        sym, df = f.result()
        if df is not None:
            all_data[sym] = df
        else:
            # Silent fail for now, but we know 0 koin means all failed
            pass

print(f"{'TP%':<6} {'SL%':<6} {'RSI':<6} {'RVOL':<6} | {'TRADES':<8} {'WIN%':<8} {'PnL':<10}")
print("-" * 65)
results = []
for tp, sl, rsi_m, rvol_m in SCENARIOS:
    total_t = 0
    total_w = 0
    total_p = 0
    for sym, df in all_data.items():
        t, w, p = run_backtest(df, tp, sl, rsi_m, rvol_m)
        total_t += t
        total_w += w
        total_p += p
    
    wr = (total_w / total_t * 100) if total_t > 0 else 0
    print(f"{tp:<6.1f} {sl:<6.1f} {rsi_m:<6} {rvol_m:<6.1f} | {total_t:<8} {wr:<8.1f}% {total_p:<+10.1f}%")
    results.append({'tp': tp, 'sl': sl, 'rsi': rsi_m, 'rvol': rvol_m, 'pnl': total_p, 'trades': total_t})

print("-" * 65)
if not results:
    print("[ERROR] Tidak ada hasil simulasi.")
    exit()

best = max(results, key=lambda x: x['pnl'])
print(f"\n[HASIL OPTIMASI]")
print(f"WINNER: TP:{best['tp']}% | SL:{best['sl']}% | RSI:{best['rsi']} | RVOL:{best['rvol']}")
print(f"TOTAL PnL: {best['pnl']:+.1f}%")
print(f"TOTAL TRADES: {best['trades']} trades")
print("-" * 65)
