"""
SUPER DUPER BACKTEST ENGINE - BITGET & GATE.IO SPOT TOP GAINER MOMENTUM
Simulasi 100% berdasarkan logika riil di crypto_engine.py & paper_executor.py
Menggunakan data historis riil (klines 15m hingga 1000 candle / ~10 hari perdagangan riil).
Dilengkapi fallback otomatis ke Gate.io Spot API jika DNS Bitget terblokir ISP lokal.
"""
import requests
import time
import os
import sys
import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

# --- CONFIG NFI SPOT REAL ---
INITIAL_BALANCE = 1000.0
FIXED_MARGIN_USDT = 45.0  # NFI: 30% dari $150 = $45 per trade
LEVERAGE = 1              # 1x Spot murni
TP_PCT = 0.20             # +20.0% Take Profit (Dynamic Trailing akan kunci profit)
SL_PCT = -0.07            # -7.0% Stop Loss (Lebar untuk hindari noise)
TRAIL_ACTIVATE_PCT = 0.02 # +2.0% aktifkan trailing (Spot mode)
TRAIL_LOCK_PCT = 0.01     # +1.0% lock profit
TIMEOUT_CANDLES = 12      # 12 candle 15m = 3 jam sideways timeout (NFI Dynamic ROI)

USE_GATEIO = False

def fetch_top_spot_symbols(limit=25):
    global USE_GATEIO
    print(f"[*] Mengambil Top {limit} koin volume terbesar untuk Backtest...", flush=True)
    # Coba Bitget dulu
    try:
        url = "https://api.bitget.com/api/v2/spot/market/tickers"
        r = requests.get(url, timeout=2)
        if r.status_code == 200:
            data = r.json().get("data", [])
            valid = []
            for t in data:
                sym = t.get("symbol", "")
                vol = float(t.get("quoteVolume", 0) or 0)
                if sym.endswith("USDT") and not any(x in sym for x in ("USDC", "DAI", "BUSD", "EUR", "GBP")):
                    if vol > 500000:
                        valid.append((sym, sym, vol))
            valid.sort(key=lambda x: x[2], reverse=True)
            symbols = valid[:limit]
            print(f"[+] Berhasil memilih {len(symbols)} simbol dari Bitget: {', '.join([x[0] for x in symbols[:10]])}...", flush=True)
            return symbols
    except Exception:
        pass
        
    # Fallback Gate.io (Sangat cepat dan bebas blokir DNS di Indonesia)
    USE_GATEIO = True
    print("[*] Menggunakan Gate.io Spot Data Feed (Fallback tercepat & bebas blokir DNS)...", flush=True)
    try:
        url = "https://api.gateio.ws/api/v4/spot/tickers"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            valid = []
            for t in data:
                pair = t.get("currency_pair", "")
                vol = float(t.get("quote_volume", 0) or 0)
                if pair.endswith("_USDT") and not any(x in pair for x in ("USDC", "DAI", "BUSD", "EUR", "GBP", "BEAR", "BULL")):
                    if vol > 500000:
                        sym = pair.replace("_", "")
                        valid.append((sym, pair, vol))
            valid.sort(key=lambda x: x[2], reverse=True)
            symbols_info = valid[:limit]
            print(f"[+] Berhasil memilih {len(symbols_info)} simbol Top Gainer / Volume: {', '.join([x[0] for x in symbols_info[:10]])}...", flush=True)
            return symbols_info
    except Exception as e:
        print(f"[!] Gagal fetch Gate.io tickers: {e}", flush=True)
        
    default_syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "PEPEUSDT", "DOGEUSDT", "WLDUSDT", "SUIUSDT", "RENDERUSDT", "NEARUSDT", "AVAXUSDT"]
    return [(s, s.replace("USDT", "_USDT"), 1000000) for s in default_syms]

def fetch_historical_candles(sym_info, granularity="15m", limit=800):
    sym_clean, gate_pair, _ = sym_info
    if not USE_GATEIO:
        try:
            url = f"https://api.bitget.com/api/v2/spot/market/candles?symbol={sym_clean}&granularity={granularity}in&limit={limit}"
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                data = r.json().get("data", [])
                data.reverse()
                return data
        except Exception:
            pass
        
    # Fallback Gate.io
    try:
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={gate_pair}&interval={granularity}&limit={limit}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            std_data = []
            for c in data:
                std_data.append([c[0], c[5], c[3], c[4], c[2], c[6], c[1]])
            return std_data
    except Exception:
        pass
    return []

def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calc_ema(closes, period=21):
    if len(closes) < period: return closes[-1]
    ema = np.mean(closes[:period])
    multiplier = 2 / (period + 1)
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def run_backtest():
    print("\n" + "="*65)
    print(" 🚀 SUPER DUPER BACKTEST NFI ENGINE - SPOT TOP 300 GAINERS 🚀")
    print("="*65)
    print(f"💰 Modal Awal : ${INITIAL_BALANCE:.2f} | Size / Trade: ${FIXED_MARGIN_USDT:.2f} (Spot NFI DCA)")
    print(f"🎯 Strategi   : NFI Tri-Core (TP: +20.0% | SL: -7.0% | Trail: +1.0% at +2.0%)")
    print(f"⏳ Dynamic ROI: Amankan profit >0.5% jika ditahan >3 jam")
    print("="*65 + "\n")

    symbols_info = fetch_top_spot_symbols(limit=30)
    
    total_trades = 0
    wins = 0
    losses = 0
    timeouts = 0
    trail_wins = 0
    total_pnl_usd = 0.0
    
    trade_logs = []
    symbol_stats = {}

    for sym_info in symbols_info:
        sym = sym_info[0]
        candles = fetch_historical_candles(sym_info, granularity="15m", limit=800)
        if len(candles) < 100:
            print(f"  [-] {sym:<10}: Data candle tidak cukup ({len(candles)})")
            continue
            
        print(f"  [+] {sym:<10}: Memproses {len(candles)} candle 15m (~{len(candles)/96:.1f} hari)...")
            
        # Parse data
        closes = [float(c[4]) for c in candles]
        highs  = [float(c[2]) for c in candles]
        lows   = [float(c[3]) for c in candles]
        vols   = [float(c[5]) for c in candles]
        timestamps = [int(c[0]) for c in candles]
        
        in_trade = False
        entry_price = 0.0
        entry_idx = 0
        sl_price = 0.0
        tp_price = 0.0
        trailing_active = False
        
        sym_wins = 0
        sym_losses = 0
        sym_pnl = 0.0

        for i in range(50, len(candles) - 1):
            curr_close = closes[i]
            curr_high  = highs[i]
            curr_low   = lows[i]
            curr_vol   = vols[i]
            
            # --- EVALUASI MANAJEMEN POSISI AKTIF ---
            if in_trade:
                bars_held = i - entry_idx
                pnl_pct = (curr_close - entry_price) / entry_price
                max_high_pct = (curr_high - entry_price) / entry_price
                min_low_pct  = (curr_low - entry_price) / entry_price
                
                exit_reason = None
                exit_price = 0.0
                
                # 1. Cek Stop Loss
                if curr_low <= sl_price:
                    exit_price = sl_price
                    exit_reason = "Hit SL (-7.0%)" if not trailing_active else "Hit Trailing SL (Locked)"
                # 2. Cek Take Profit
                elif curr_high >= tp_price:
                    exit_price = tp_price
                    exit_reason = "Hit Take Profit (+20.0%)"
                # 3. Cek aktivasi Trailing Stop (Dynamic Trailing berbasis Highest High)
                elif max_high_pct >= TRAIL_ACTIVATE_PCT:
                    trailing_active = True
                    dynamic_sl = curr_high * 0.985
                    min_lock_sl = entry_price * (1.0 + TRAIL_LOCK_PCT)
                    new_sl = max(dynamic_sl, min_lock_sl)
                    if sl_price == 0 or new_sl > sl_price:
                        sl_price = new_sl
                # 4. Cek NFI Dynamic Sideways Timeout (3 Jam & Profit > 0.5%)
                elif bars_held >= TIMEOUT_CANDLES:
                    if pnl_pct >= 0.005:
                        exit_price = curr_close
                        exit_reason = f"NFI Dynamic ROI (+{pnl_pct*100:.2f}%)"
                    elif pnl_pct < -0.05: # Kalau sideways tapi rugi gede, mending keluar
                        exit_price = curr_close
                        exit_reason = f"Sideways Cutloss ({pnl_pct*100:.2f}%)"
                    # 5. Force Exit Timeout (24h)
                    elif bars_held >= 96:
                        exit_price = curr_close
                        exit_reason = "24h Sideways Timeout"
                    
                if exit_reason:
                    trade_pnl_pct = (exit_price - entry_price) / entry_price
                    trade_pnl_usd = FIXED_MARGIN_USDT * trade_pnl_pct
                    
                    total_trades += 1
                    total_pnl_usd += trade_pnl_usd
                    sym_pnl += trade_pnl_usd
                    
                    is_win = trade_pnl_pct > 0
                    if is_win:
                        wins += 1
                        sym_wins += 1
                        if "Trailing" in exit_reason: trail_wins += 1
                    elif trade_pnl_pct < 0:
                        losses += 1
                        sym_losses += 1
                    else:
                        timeouts += 1
                        if "Timeout" in exit_reason: timeouts += 1
                        
                    status_icon = "✅" if is_win else ("❌" if trade_pnl_pct < 0 else "⚖️")
                    trade_logs.append({
                        "symbol": sym,
                        "entry": entry_price,
                        "exit": exit_price,
                        "pnl_pct": trade_pnl_pct * 100,
                        "pnl_usd": trade_pnl_usd,
                        "reason": exit_reason,
                        "icon": status_icon,
                        "bars": bars_held
                    })
                    
                    in_trade = False
                continue

            # --- EVALUASI SINYAL ENTRY (100% LONG-ONLY) ---
            # RSI 14
            rsi = calc_rsi(closes[:i+1], period=14)
            # EMA 21
            ema21 = calc_ema(closes[:i+1], period=21)
            # EMA 84 (sebagai proksi Trend 1H di candle 15m)
            ema84 = calc_ema(closes[:i+1], period=84)
            
            # RVOL (Volume saat ini dibanding rata-rata 20 candle)
            avg_vol_20 = np.mean(vols[i-20:i]) if i >= 20 else vols[i]
            rvol = curr_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0
            
            # Bollinger Bands (20, 2.0)
            bb_mean = np.mean(closes[max(0, i-19):i+1])
            bb_std = np.std(closes[max(0, i-19):i+1])
            bb_up = bb_mean + 2.0 * bb_std
            bb_low = bb_mean - 2.0 * bb_std
            bb_width_pct = (bb_up - bb_low) / bb_mean * 100 if bb_mean > 0 else 10.0
            is_squeeze = bb_width_pct < 5.0
            
            # Wick ratio (SMC Demand Rejection proxy)
            body_size = abs(curr_close - closes[i-1]) if i >= 1 else abs(curr_close - curr_low)
            lower_wick = min(curr_close, closes[i-1]) - curr_low if i >= 1 else 0
            wick_ratio = lower_wick / body_size if body_size > 0 else 1.0
            
            # 1. Filter Dasar Spot (Jangan tangkap pisau jatuh berlebihan)
            if rsi < 25 or rsi > 82: continue
            
            # CORE 1: Volatility Breakout (RVOL >= 2.0x, Squeeze, Harga Breakout BB Up/EMA 84)
            is_core1 = (rvol >= 2.0 and 55 <= rsi <= 78 and (curr_close >= bb_up * 0.995 or curr_close > ema84 or is_squeeze))
            
            # CORE 2: NFI Dip Sniping (Dilarang serok bawah jika tren 1H hancur - Proksi: EMA84 harus naik)
            ema84_prev = calc_ema(closes[:i], period=84)
            trend_1h_bullish = (ema84 > ema84_prev)
            is_core2 = ((rsi <= 44 or curr_close <= bb_low * 1.01) and (trend_1h_bullish or rsi <= 35) and wick_ratio >= 1.2)
            
            # CORE 3: SMC Demand Rejection (Wick ratio >= 1.3 dengan volume masuk RVOL >= 1.5)
            is_core3 = (wick_ratio >= 1.3 and rvol >= 1.5 and rsi <= 65)
            
            if is_core1 or is_core2 or is_core3:
                in_trade = True
                entry_price = curr_close
                entry_idx = i
                sl_price = entry_price * (1.0 + SL_PCT)  # -3.5%
                tp_price = entry_price * (1.0 + TP_PCT)  # +7.5%
                trailing_active = False

        if sym_wins + sym_losses > 0:
            symbol_stats[sym] = {"wins": sym_wins, "losses": sym_losses, "pnl": sym_pnl}

    # --- PRINT REPORT ---
    win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
    final_balance = INITIAL_BALANCE + total_pnl_usd
    return_pct = (total_pnl_usd / INITIAL_BALANCE) * 100

    print("\n" + "="*65)
    print(" 📊 HASIL BACKTEST TOP GAINER MOMENTUM (SPOT REAL DATA) 📊")
    print("="*65)
    print(f"📈 Total Trade Evaluasi : {total_trades}")
    print(f"✅ Total Menang (WIN)   : {wins} (termasuk {trail_wins} Trailing Stop Lock)")
    print(f"❌ Total Kalah (LOSS)   : {losses}")
    print(f"⚖️ Sideways / Timeout   : {timeouts}")
    print(f"🏆 Win Rate             : {win_rate:.1f}%")
    print("-" * 65)
    print(f"💰 Modal Awal           : ${INITIAL_BALANCE:.2f}")
    print(f"💵 Keuntungan (PnL)     : ${total_pnl_usd:+.2f} ({return_pct:+.2f}%)")
    print(f"🏛️ Saldo Akhir          : ${final_balance:.2f}")
    print("="*65)

    print("\n📜 Top 10 Transaksi Terakhir:")
    print("-" * 65)
    for log in trade_logs[-10:]:
        print(f"{log['icon']} {log['symbol']:<10} | Entry: {log['entry']:<8.4f} | Exit: {log['exit']:<8.4f} | PnL: {log['pnl_pct']:+5.2f}% (${log['pnl_usd']:+5.2f}) | {log['reason']}")
    print("-" * 65)
    
    print("\n👑 Top 5 Koin Paling Cuan di Backtest:")
    sorted_syms = sorted(symbol_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)
    for sym, st in sorted_syms[:5]:
        wr = (st['wins'] / (st['wins'] + st['losses'])) * 100 if (st['wins'] + st['losses']) > 0 else 0
        print(f"   🔥 {sym:<10} | WinRate: {wr:5.1f}% ({st['wins']}W/{st['losses']}L) | Total PnL: ${st['pnl']:+6.2f}")
    print("="*65 + "\n")

if __name__ == "__main__":
    run_backtest()
