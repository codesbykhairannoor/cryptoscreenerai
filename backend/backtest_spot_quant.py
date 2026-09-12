"""
QUANTITATIVE SPOT BACKTEST ENGINE v1.0
========================================
Mesin Backtest Ilmiah untuk Pasar Kripto Spot:
- Data Historis Riil 15m (Bitget Spot dengan fallback otomatis ke Gate.io Spot)
- Top 50-80 Koin Spot Paling Likuid (Volume > $3M, membuang koin ilikuid/sampah)
- Menguji 5 Strategi Kuantitatif Mandiri:
  1. NFI_DIP_SNIPING (Freqtrade Style: Oversold + Wick Rejection + Support)
  2. TREND_MOMENTUM_BREAKOUT (EMA 21/50 + RVOL > 2.0x + ADX Regime)
  3. VWAP_MEAN_REVERSION (VWAP Oversold Pullback + Support Bounce)
  4. VOLATILITY_SQUEEZE_EXPLOSION (Bollinger Band Compression + Volume Blast)
  5. MULTI_CONFLUENCE_HYBRID (SMC Support + Multi-Factor Confluence)
- Memperhitungkan Biaya Riil Spot: Taker Fee 0.1% per side (0.2% round-trip)
- Output: Metrik Kuantitatif Lengkap (Win Rate, Profit Factor, Net PnL, Max Drawdown, Expectancy)
"""

import os
import sys
import time
import pickle
import requests
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

# ==============================================================================
# CONFIG
# ==============================================================================
INTERVAL      = "15m"
LOOKBACK      = 800         # 800 candle 15m = ~8 hari pergerakan pasar intensif
MIN_VOLUME    = 3_000_000   # Min $3M volume 24h (Sesuai Freqtrade standard)
MAX_COINS     = 50          # Top 50 koin spot paling likuid
SPOT_FEE      = 0.0010      # 0.10% Taker fee Bitget/Gate.io per transaksi
INITIAL_CASH  = 1000.0      # Saldo awal simulasi
TRADE_SIZE    = 150.0       # $150 per trade (Spot cash)

BITGET_BASE   = "https://api.bitget.com"
GATE_BASE     = "https://api.gateio.ws"

# ==============================================================================
# 1. DATA INGESTION (BITGET WITH GATE.IO FALLBACK)
# ==============================================================================
def fetch_top_spot_pairs(limit=MAX_COINS):
    """Ambil top spot pairs dengan volume > $3M."""
    print(f"[*] Mengunduh daftar Top Spot Tickers (Min Volume: ${MIN_VOLUME:,.0f})...", flush=True)
    
    # Coba Bitget Spot dulu
    try:
        url = f"{BITGET_BASE}/api/v2/spot/market/tickers"
        r = requests.get(url, timeout=4)
        if r.status_code == 200:
            data = r.json().get('data', [])
            valid = []
            for t in data:
                sym = t.get('symbol', '')
                if not sym.endswith('USDT'): continue
                vol = float(t.get('quoteVolume', 0) or 0)
                if vol >= MIN_VOLUME:
                    base = sym.replace('USDT', '')
                    if any(base.endswith(x) for x in ['UP', 'DOWN', 'BULL', 'BEAR', '3L', '3S']): continue
                    if base.startswith('R') and base not in {"RNDR", "ROSE", "RUNE", "RAY", "RENDER", "RONIN", "RDNT"}: continue
                    valid.append((sym, sym, vol, 'bitget'))
            valid.sort(key=lambda x: x[2], reverse=True)
            if len(valid) >= 10:
                print(f"[+] Bitget Spot API Terhubung! Memilih {min(limit, len(valid))} koin teratas.", flush=True)
                return valid[:limit]
    except Exception:
        pass

    # Fallback ke Gate.io Spot jika Bitget terblokir DNS lokal
    try:
        url = f"{GATE_BASE}/api/v4/spot/tickers"
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            data = r.json()
            valid = []
            for t in data:
                pair = t.get('currency_pair', '')
                if not pair.endswith('_USDT'): continue
                vol = float(t.get('quote_volume', 0) or 0)
                if vol >= MIN_VOLUME:
                    base = pair.replace('_USDT', '')
                    if any(base.endswith(x) for x in ['UP', 'DOWN', 'BULL', 'BEAR', '3L', '3S']): continue
                    if base.startswith('R') and base not in {"RNDR", "ROSE", "RUNE", "RAY", "RENDER", "RONIN", "RDNT"}: continue
                    clean_sym = pair.replace('_USDT', 'USDT')
                    valid.append((clean_sym, pair, vol, 'gateio'))
            valid.sort(key=lambda x: x[2], reverse=True)
            print(f"[+] Gate.io Spot API Terhubung (Fallback)! Memilih {min(limit, len(valid))} koin teratas.", flush=True)
            return valid[:limit]
    except Exception as e:
        print(f"[!] Error fetch spot tickers: {e}", flush=True)

    # Hardcoded default jika koneksi gagal total
    default = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "PEPEUSDT", "NEARUSDT", "SUIUSDT", "AVAXUSDT"]
    return [(s, s.replace("USDT", "_USDT"), 5000000, 'fallback') for s in default]


def fetch_spot_candles(pair_info, interval=INTERVAL, limit=LOOKBACK):
    """Ambil klines 15m spot riil."""
    clean_sym, alt_sym, vol, source = pair_info
    
    if source == 'bitget':
        try:
            url = f"{BITGET_BASE}/api/v2/spot/market/candles?symbol={clean_sym}&granularity=15min&limit={limit}"
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                data = r.json().get('data', [])
                if len(data) >= 50:
                    data.reverse()
                    df = pd.DataFrame(data, columns=["ts", "open", "high", "low", "close", "baseVol", "quoteVol"])
                    for c in ["open", "high", "low", "close", "baseVol", "quoteVol"]:
                        df[c] = pd.to_numeric(df[c], errors='coerce')
                    return df.dropna().reset_index(drop=True)
        except Exception:
            pass

    # Gate.io Spot Candles
    gate_pair = alt_sym if '_' in alt_sym else f"{alt_sym.replace('USDT', '')}_USDT"
    try:
        url = f"{GATE_BASE}/api/v4/spot/candlesticks?currency_pair={gate_pair}&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=6)
        if r.status_code == 200:
            data = r.json()
            if len(data) >= 50:
                # Gate format: [ts, quote_vol, close, high, low, open, base_vol]
                reordered = []
                for c in data:
                    reordered.append([c[0], c[5], c[3], c[4], c[2], c[6], c[1]])
                df = pd.DataFrame(reordered, columns=["ts", "open", "high", "low", "close", "baseVol", "quoteVol"])
                for col in ["open", "high", "low", "close", "baseVol", "quoteVol"]:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                return df.dropna().reset_index(drop=True)
    except Exception:
        pass

    return None


# ==============================================================================
# 2. FEATURE ENGINEERING & INDICATORS CALCULATION
# ==============================================================================
def compute_all_indicators(df):
    """Hitung semua indikator kuantitatif secara efisien."""
    c = df['close']
    h = df['high']
    l = df['low']
    v = df['quoteVol']

    # 1. RSI (14)
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

    # 2. EMAs & Trend Alignment
    df['ema21'] = c.ewm(span=21, adjust=False).mean()
    df['ema50'] = c.ewm(span=50, adjust=False).mean()
    df['trend_bullish'] = (c > df['ema21']) & (df['ema21'] > df['ema50'])
    df['trend_bearish'] = (c < df['ema21']) & (df['ema21'] < df['ema50'])

    # 3. Bollinger Bands (20, 2) & Squeeze
    df['bb_mid'] = c.rolling(20).mean()
    df['bb_std'] = c.rolling(20).std()
    df['bb_up']  = df['bb_mid'] + (df['bb_std'] * 2.0)
    df['bb_low'] = df['bb_mid'] - (df['bb_std'] * 2.0)
    df['bb_width_pct'] = (df['bb_up'] - df['bb_low']) / df['bb_mid'].replace(0, np.nan) * 100
    df['is_squeeze']   = df['bb_width_pct'] < 4.0

    # 4. ATR (14)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['atr_pct'] = df['atr'] / c.replace(0, np.nan) * 100

    # 5. RVOL (Relative Volume 20)
    df['rvol'] = v / v.rolling(20).mean().replace(0, np.nan)

    # 6. Lower Wick Ratio (Rejection Hunter)
    body = (c - df['open']).abs()
    lower_wick = np.minimum(df['open'], c) - l
    df['lower_wick_ratio'] = lower_wick / body.replace(0, 0.0001)

    # 7. Rolling VWAP (40 candles)
    typical = (h + l + c) / 3
    df['vwap'] = (typical * v).rolling(40).sum() / v.rolling(40).sum().replace(0, np.nan)
    df['vwap_dist'] = (c - df['vwap']) / df['vwap'].replace(0, np.nan) * 100

    # 8. 24h Change Approximation (96 candles 15m)
    df['chg_24h'] = (c - c.shift(96)) / c.shift(96).replace(0, np.nan) * 100

    return df.dropna().reset_index(drop=True)


# ==============================================================================
# 3. LIMA ARSITEKTUR STRATEGI KUANTITATIF (SPOT ONLY)
# ==============================================================================

def strat_nfi_dip_sniping(row):
    """
    STRATEGI 1: NFI BULLISH DIP SNIPING (Freqtrade NFI Style)
    - Hanya buy dip saat tren jangka menengah BULLISH (close > EMA50)
    - Dip terjadi ke area oversold (RSI < 40 atau Lower Bollinger Band)
    - Konfirmasi pin bar / lower wick rejection (wick >= 1.2)
    - Target 3:1 R:R
    """
    price = row['close']
    low   = row['low']
    rsi   = row['rsi']
    bb_low = row['bb_low']
    wick  = row['lower_wick_ratio']
    rvol  = row['rvol']
    chg   = row['chg_24h']
    is_bull = row['trend_bullish']

    # Beli DIP HANYA di koin yang tren dasarnya BULLISH (menghindari falling knives)
    if is_bull and (rsi < 40 or low <= bb_low * 1.005) and wick >= 1.2 and rvol >= 1.1 and -8.0 < chg < 14.0:
        sl_pct = 0.018  # Stop Loss ketat -1.8%
        tp_pct = 0.055  # Target Profit +5.5% (3.1:1 R:R)
        return 'buy', price * (1 + tp_pct), price * (1 - sl_pct), 'trailing'
    return None, 0, 0, 'none'


def strat_trend_momentum_breakout(row):
    """
    STRATEGI 2: TREND-FOLLOW MOMENTUM BREAKOUT
    - Masuk saat tren EMA21 > EMA50 Bullish
    - Volume meledak (RVOL >= 1.6x)
    - RSI sehat (52 <= RSI <= 66, bukan pucuk)
    """
    price = row['close']
    rsi   = row['rsi']
    rvol  = row['rvol']
    is_bull = row['trend_bullish']
    chg   = row['chg_24h']

    if is_bull and rvol >= 1.6 and 52 <= rsi <= 66 and 1.5 <= chg <= 15.0:
        sl_pct = 0.018  # SL -1.8%
        tp_pct = 0.060  # TP +6.0% (3.3:1 R:R)
        return 'buy', price * (1 + tp_pct), price * (1 - sl_pct), 'trailing'
    return None, 0, 0, 'none'


def strat_vwap_mean_reversion(row):
    """
    STRATEGI 3: VWAP MEAN REVERSION PULLBACK
    - Harga berada di bawah VWAP (-1.5% s/d -4.0%)
    - RSI oversold mulai bangkit (32 <= RSI <= 45)
    - Volume mulai masuk (RVOL >= 1.2x)
    """
    price = row['close']
    rsi   = row['rsi']
    rvol  = row['rvol']
    vwap_dist = row['vwap_dist']

    if -4.0 <= vwap_dist <= -1.2 and 30 <= rsi <= 45 and rvol >= 1.2:
        sl_pct = 0.018  # SL -1.8%
        tp_pct = 0.045  # TP +4.5% (Kembali ke VWAP) (2.5:1 R:R)
        return 'buy', price * (1 + tp_pct), price * (1 - sl_pct), 'fixed'
    return None, 0, 0, 'none'


def strat_volatility_squeeze_explosion(row):
    """
    STRATEGI 4: VOLATILITY SQUEEZE EXPLOSION
    - Bollinger Band Squeeze sempit (< 4.0% width)
    - Breakout menembus Upper Band dengan Volume Spike (RVOL >= 2.2x)
    """
    price   = row['close']
    is_sqz  = row['is_squeeze']
    rvol    = row['rvol']
    bb_up   = row['bb_up']
    rsi     = row['rsi']

    if is_sqz and price >= bb_up * 0.998 and rvol >= 2.2 and rsi <= 72:
        sl_pct = 0.020  # SL -2.0%
        tp_pct = 0.080  # TP +8.0% Moonshot (4:1 R:R)
        return 'buy', price * (1 + tp_pct), price * (1 - sl_pct), 'trailing'
    return None, 0, 0, 'none'


def strat_multi_confluence_hybrid(row):
    """
    STRATEGI 5: MULTI-CONFLUENCE HYBRID (Institutional Engine)
    - Sistem skor multi-faktor: Butuh minimal 3 sinyal selaras
    """
    price = row['close']
    rsi   = row['rsi']
    rvol  = row['rvol']
    wick  = row['lower_wick_ratio']
    vwap_d = row['vwap_dist']
    is_bull = row['trend_bullish']
    chg   = row['chg_24h']

    confluence = 0
    if is_bull: confluence += 1
    if rvol >= 1.8: confluence += 1
    if 45 <= rsi <= 65: confluence += 1
    if wick >= 1.2: confluence += 1
    if -3.0 <= vwap_d <= 1.0: confluence += 1
    if 0.5 <= chg <= 15.0: confluence += 1

    if confluence >= 4 and rsi <= 68:
        sl_pct = 0.020  # SL -2.0%
        tp_pct = 0.065  # TP +6.5% Trailing
        return 'buy', price * (1 + tp_pct), price * (1 - sl_pct), 'trailing'
    return None, 0, 0, 'none'


# ==============================================================================
# 4. SIMULATION ENGINE (SPOT CASH ACCOUNTING)
# ==============================================================================
def backtest_single_strategy(all_data, strat_fn, name):
    """Simulasi eksekusi transaksi spot murni dengan komisi fee nyata."""
    total_trades = 0
    wins = 0
    losses = 0
    total_pnl_usd = 0.0
    equity = INITIAL_CASH
    peak_equity = INITIAL_CASH
    max_dd = 0.0
    consecutive_loss = 0
    max_consecutive_loss = 0
    trade_returns = []

    for df in all_data:
        in_trade = False
        entry_price = 0.0
        tp_price = 0.0
        sl_price = 0.0
        exit_type = 'none'
        peak_gain = 0.0
        hold_candles = 0

        # Iterasi candle per koin
        for i in range(len(df)):
            if i < 50: continue
            row = df.iloc[i]
            high = row['high']
            low  = row['low']
            close = row['close']

            if in_trade:
                hold_candles += 1
                curr_gain = (high - entry_price) / entry_price
                if curr_gain > peak_gain:
                    peak_gain = curr_gain

                # Institutional Dynamic Ratchet & Trailing Stop:
                # 1. Breakeven Lock: Begitu running profit mencapai +2.0%, SL dinaikkan ke Entry + 0.4% (Cover Spot Roundtrip Fee 0.2% + Untung Bersih 0.2%)
                if peak_gain >= 0.020:
                    sl_price = max(sl_price, entry_price * 1.004)
                
                # 2. Profit Lock Level 1: Begitu profit mencapai +4.0%, SL dikunci di Entry + 2.2%
                if peak_gain >= 0.040:
                    sl_price = max(sl_price, entry_price * 1.022)

                # 3. Profit Lock Level 2: Begitu profit mencapai +6.5%, SL dikunci di Entry + 4.5%
                if peak_gain >= 0.065:
                    sl_price = max(sl_price, entry_price * 1.045)

                # Cek Exit
                hit_tp = high >= tp_price
                hit_sl = low <= sl_price
                timeout = hold_candles >= 32  # Max hold 8 jam (32 candle 15m)

                if hit_tp or hit_sl or timeout:
                    if hit_tp:
                        exit_price = tp_price
                    elif hit_sl:
                        exit_price = sl_price
                    else: # Timeout exit at market close
                        exit_price = close

                    raw_pct = (exit_price - entry_price) / entry_price
                    # Potong fee spot round-trip (0.1% buy + 0.1% sell = 0.2%)
                    net_pct = raw_pct - (SPOT_FEE * 2)
                    pnl_usd = TRADE_SIZE * net_pct

                    total_pnl_usd += pnl_usd
                    equity += pnl_usd
                    total_trades += 1
                    trade_returns.append(net_pct * 100)

                    if pnl_usd > 0:
                        wins += 1
                        consecutive_loss = 0
                    else:
                        losses += 1
                        consecutive_loss += 1
                        max_consecutive_loss = max(max_consecutive_loss, consecutive_loss)

                    # Max Drawdown tracking
                    if equity > peak_equity:
                        peak_equity = equity
                    dd = (peak_equity - equity) / peak_equity * 100
                    if dd > max_dd:
                        max_dd = dd

                    in_trade = False

            if not in_trade:
                sig, tp, sl, ex_type = strat_fn(row)
                if sig == 'buy':
                    in_trade = True
                    entry_price = close
                    tp_price = tp
                    sl_price = sl
                    exit_type = ex_type
                    peak_gain = 0.0
                    hold_candles = 0

    if total_trades == 0:
        return None

    win_rate = (wins / total_trades) * 100
    gross_wins = sum(r for r in trade_returns if r > 0)
    gross_losses = abs(sum(r for r in trade_returns if r < 0))
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else 99.0
    expectancy = np.mean(trade_returns) if trade_returns else 0.0
    net_roi = (total_pnl_usd / INITIAL_CASH) * 100

    return {
        "name": name,
        "trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "net_pnl_usd": round(total_pnl_usd, 2),
        "net_roi_pct": round(net_roi, 2),
        "expectancy_pct": round(expectancy, 2),
        "max_dd_pct": round(max_dd, 1),
        "max_consec_sl": max_consecutive_loss,
    }


# ==============================================================================
# 5. MAIN EXECUTION & COMPARISON
# ==============================================================================
def main():
    print("=" * 85)
    print("  SUPER GILA QUANTITATIVE BACKTEST: BITGET & GATE.IO SPOT")
    print(f"  Analisis Data Riil 15M Koin Likuid | Modal ${INITIAL_CASH:.0f} | Size ${TRADE_SIZE:.0f}/trade")
    print("=" * 85)

    cache_file = "spot_backtest_cache.pkl"
    dataset = []
    if os.path.exists(cache_file):
        try:
            import pickle
            with open(cache_file, "rb") as f:
                dataset = pickle.load(f)
            print(f"[+] Memuat {len(dataset)} koin spot dari cache lokal ({cache_file}) secara instan!\n", flush=True)
        except Exception:
            dataset = []

    if not dataset:
        pairs = fetch_top_spot_pairs(MAX_COINS)
        if not pairs:
            print("[!] Gagal mengunduh daftar koin spot.")
            return

        print(f"\n[*] Mengunduh {LOOKBACK} candle 15m untuk {len(pairs)} koin spot teratas...")
        for idx, p in enumerate(pairs):
            df = fetch_spot_candles(p, INTERVAL, LOOKBACK)
            if df is not None and len(df) >= 100:
                df = compute_all_indicators(df)
                if len(df) >= 80:
                    dataset.append(df)
            if (idx + 1) % 15 == 0:
                print(f"    Selesai {idx+1}/{len(pairs)} koin ({len(dataset)} valid)...", flush=True)
            time.sleep(0.08)

        if dataset:
            try:
                import pickle
                with open(cache_file, "wb") as f:
                    pickle.dump(dataset, f)
                print(f"[+] Dataset disimpan ke {cache_file} untuk pengujian super cepat.", flush=True)
            except Exception:
                pass

        print(f"[+] Berhasil memproses {len(dataset)} koin spot dengan indikator lengkap.\n", flush=True)

    # 5 Strategi yang diuji
    strategies = [
        (strat_nfi_dip_sniping,            "1. NFI Dynamic Dip Sniping"),
        (strat_trend_momentum_breakout,    "2. Trend Momentum Breakout"),
        (strat_vwap_mean_reversion,        "3. VWAP Mean Reversion"),
        (strat_volatility_squeeze_explosion, "4. Volatility Squeeze"),
        (strat_multi_confluence_hybrid,    "5. Multi-Confluence Hybrid"),
    ]

    results = []
    print("[*] Menjalankan simulasi kuantitatif pada seluruh dataset...", flush=True)
    for fn, name in strategies:
        res = backtest_single_strategy(dataset, fn, name)
        if res:
            results.append(res)
            print(f"    [OK] Selesai: {name}")

    # Tampilkan Hasil Komparasi
    print("\n" + "=" * 90)
    print(f"{'Strategi':<30} {'Trades':>7} {'WinRate':>9} {'PF':>6} {'Net PnL ($)':>13} {'ROI (%)':>9} {'MaxDD':>7} {'SL Max':>7}")
    print("-" * 90)

    for r in results:
        print(f"{r['name']:<30} {r['trades']:>7} {r['win_rate']:>8.1f}% {r['profit_factor']:>6.2f} ${r['net_pnl_usd']:>11.2f} {r['net_roi_pct']:>8.1f}% {r['max_dd_pct']:>6.1f}% {r['max_consec_sl']:>7}")

    print("=" * 90)

    # Pilih Pemenang
    if results:
        # Pemenang berdasarkan Profit Factor tertinggi dan Net PnL positif
        best = max(results, key=lambda x: (x['profit_factor'], x['net_pnl_usd']))
        print(f"\n STRATEGI TERBAIK TERPILIH: {best['name']}")
        print(f"   Win Rate      : {best['win_rate']}%")
        print(f"   Profit Factor : {best['profit_factor']}x")
        print(f"   Net PnL       : ${best['net_pnl_usd']} ({best['net_roi_pct']}%)")
        print(f"   Max Drawdown  : -{best['max_dd_pct']}%")
        print(f"   Max Consec SL : {best['max_consec_sl']} trades")
        print(f"\n[KESIMPULAN ILMIAH] Strategi ini yang akan diterapkan 100% ke backend/crypto_engine.py!")

if __name__ == "__main__":
    main()
