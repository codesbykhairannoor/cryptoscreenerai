# -*- coding: utf-8 -*-
"""
STRATEGY BACKTEST v9.2 vs v8.x
Ambil data REAL dari Bitget, simulasi kedua strategi, bandingkan hasilnya.
"""
import sys, os, time, requests, hmac, hashlib, base64, json
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

API_KEY    = os.getenv("BITGET_API_KEY", "")
SECRET_KEY = os.getenv("BITGET_SECRET_KEY", "")
PASSPHRASE = os.getenv("BITGET_PASSPHRASE", "")

BASE_URL = "https://api.bitget.com"

# ═══════════════════════════════════════════════════════════
# COINS TO TEST -- liquid coins only (tidak ada blacklist)
# ═══════════════════════════════════════════════════════════
TEST_COINS = [
    "ETHUSDT", "BNBUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
    "LINKUSDT", "MATICUSDT", "DOTUSDT", "LTCUSDT", "ATOMUSDT",
    "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT",
    "SUIUSDT", "SEIUSDT", "TIAUSDT", "WIFUSDT", "FETUSDT",
]

# ═══════════════════════════════════════════════════════════
# BITGET API HELPER
# ═══════════════════════════════════════════════════════════
def sign_request(method, path, query="", body=""):
    ts = str(int(time.time() * 1000))
    msg = ts + method.upper() + path + (f"?{query}" if query else "") + body
    mac = hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256)
    sig = base64.b64encode(mac.digest()).decode()
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sig,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json",
        "locale": "en-US"
    }

def get_candles(symbol, granularity="15m", limit=200):
    """Ambil candle historis dari Bitget Futures."""
    try:
        path = "/api/v2/mix/market/history-candles"
        q = f"symbol={symbol}&granularity={granularity}&limit={limit}&productType=USDT-FUTURES"
        r = requests.get(BASE_URL + path, params={"symbol": symbol, "granularity": granularity,
                         "limit": limit, "productType": "USDT-FUTURES"}, timeout=8)
        data = r.json().get("data", [])
        # Format: [ts, open, high, low, close, vol, ...]
        return [[float(c[i]) for i in range(6)] for c in data if len(c) >= 6]
    except Exception as e:
        return []

def get_ticker(symbol):
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/ticker",
                        params={"symbol": symbol, "productType": "USDT-FUTURES"}, timeout=5)
        d = r.json().get("data", [{}])
        if isinstance(d, list): d = d[0]
        return float(d.get("lastPr", 0) or d.get("last", 0))
    except:
        return 0

def get_orderbook(symbol):
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/depth",
                        params={"symbol": symbol, "productType": "USDT-FUTURES", "limit": "20"}, timeout=5)
        d = r.json().get("data", {})
        bids = [[float(x) for x in b] for b in d.get("bids", [])[:5]]
        asks = [[float(x) for x in a] for a in d.get("asks", [])[:5]]
        if not bids or not asks:
            return 0.0
        bid_vol = sum(b[1] for b in bids)
        ask_vol = sum(a[1] for a in asks)
        total = bid_vol + ask_vol
        obi = (bid_vol - ask_vol) / total if total > 0 else 0
        return round(obi, 4)
    except:
        return 0.0

# ═══════════════════════════════════════════════════════════
# INDICATOR CALCULATORS (dari candle data)
# ═══════════════════════════════════════════════════════════
def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period-1) + gains[i]) / period
        al = (al * (period-1) + losses[i]) / period
    return round(100 - (100/(1+(ag/al if al else 0.001))), 2)

def calc_vwap(candles):
    """VWAP dari candle data."""
    total_vol = total_pv = 0
    for c in candles[-50:]:
        typ = (c[2] + c[3] + c[4]) / 3  # (high+low+close)/3
        vol = c[5]
        total_pv  += typ * vol
        total_vol += vol
    return total_pv / total_vol if total_vol > 0 else 0

def calc_volume_ratio(candles):
    """Current volume vs 20-period average."""
    if len(candles) < 21:
        return 1.0
    avg = sum(c[5] for c in candles[-21:-1]) / 20
    cur = candles[-1][5]
    return cur / avg if avg > 0 else 1.0

def calc_mss_bullish(closes):
    """MSS: Harga break di atas high 20 candle terakhir."""
    if len(closes) < 22:
        return False
    prev_high = max(closes[-22:-2])
    return closes[-1] > prev_high

def is_vol_spike(candles, mult=2.5):
    if len(candles) < 5:
        return False
    avg = sum(c[5] for c in candles[-5:-1]) / 4
    return candles[-1][5] > avg * mult

# ═══════════════════════════════════════════════════════════
# STRATEGY SCORERS
# ═══════════════════════════════════════════════════════════
def score_v8(rsi, vwap_dist, vol_spike, mss, obi, fvg_dummy=False):
    """Strategi LAMA: Mean Reversion."""
    score = 0
    # RSI: oversold = bagus untuk BUY (SALAH)
    if 30 <= rsi <= 50:   score += 25
    elif 50 < rsi <= 60:  score += 15
    elif 20 <= rsi < 30:  score += 10
    elif rsi > 70:        score -= 10
    # VWAP: di bawah = bagus (SALAH)
    if -3.0 <= vwap_dist <= -0.5:  score += 20
    elif -0.5 < vwap_dist <= 0.5:  score += 10
    elif vwap_dist > 3.0:          score -= 10
    # MSS
    if mss: score += 15
    # Vol spike
    if vol_spike: score += 12
    # OBI
    if obi > 0.15: score += 5
    elif obi > 0.10: score += 3
    # FVG dummy
    if fvg_dummy: score += 12
    return score

def score_v9(rsi, vwap_dist, vol_spike, mss, obi, vol_ratio=1.0):
    """Strategi BARU: Momentum Confirmation."""
    score = 0
    # RSI: momentum zone = 52-65 (bukan oversold)
    if 52 <= rsi <= 65:   score += 30
    elif 45 <= rsi < 52:  score += 15
    elif rsi > 75:        score -= 20
    elif rsi < 35:        score -= 15  # FALLING KNIFE
    # VWAP: DI ATAS = buyer control (dibalik)
    if 0.5 <= vwap_dist <= 3.0:   score += 20
    elif 0 < vwap_dist < 0.5:     score += 10
    elif vwap_dist < -2.0:        score -= 15
    # MSS
    if mss: score += 15
    # Volume
    if vol_spike:         score += 15
    elif vol_ratio > 1.5: score += 8
    # OBI (lebih berpengaruh)
    if obi > 0.20:   score += 10
    elif obi > 0.10: score += 5
    elif obi < -0.15: score -= 10
    return score

# ═══════════════════════════════════════════════════════════
# SIMULATE TRADE OUTCOME
# Beli di candle N, lihat apakah TP atau SL yang kena duluan
# ═══════════════════════════════════════════════════════════
def simulate_trade(candles, entry_idx, side, tp_pct, sl_pct):
    """
    Return: 'WIN', 'LOSS', atau 'TIMEOUT'
    """
    if entry_idx >= len(candles) - 1:
        return "TIMEOUT", 0
    
    entry_price = candles[entry_idx][4]  # close price
    
    if side == "buy":
        tp_price = entry_price * (1 + tp_pct)
        sl_price = entry_price * (1 - sl_pct)
    else:
        tp_price = entry_price * (1 - tp_pct)
        sl_price = entry_price * (1 + sl_pct)
    
    # Simulate forward max 24 candles (6 hours at 15m)
    for i in range(entry_idx + 1, min(entry_idx + 25, len(candles))):
        high  = candles[i][2]
        low   = candles[i][3]
        
        if side == "buy":
            if low  <= sl_price: return "LOSS", round((sl_price/entry_price - 1)*100, 2)
            if high >= tp_price: return "WIN",  round((tp_price/entry_price - 1)*100, 2)
        else:
            if high >= sl_price: return "LOSS", round((1 - sl_price/entry_price)*100, 2)
            if low  <= tp_price: return "WIN",  round((1 - tp_price/entry_price)*100, 2)
    
    # Timeout: lihat posisi terakhir
    final = candles[min(entry_idx+24, len(candles)-1)][4]
    if side == "buy":
        pnl = (final/entry_price - 1)*100
    else:
        pnl = (1 - final/entry_price)*100
    
    return ("WIN" if pnl > 0 else "LOSS"), round(pnl, 2)

# ═══════════════════════════════════════════════════════════
# MAIN BACKTEST ENGINE
# ═══════════════════════════════════════════════════════════
def run_backtest():
    print("=" * 70)
    print("STRATEGY BACKTEST: v8.x (Mean Reversion) vs v9.2 (Momentum)")
    print("Data: LIVE dari Bitget | Timeframe: 15m | 200 candles per coin")
    print("=" * 70)
    
    # Test koneksi dulu
    test_price = get_ticker("ETHUSDT")
    if test_price > 0:
        print(f"[OK] Bitget Connected | ETH price: ${test_price}\n")
    else:
        print("[FAIL] Cannot connect to Bitget!\n")
        return

    v8_results = {"WIN":0, "LOSS":0, "TIMEOUT":0, "pnls":[], "entries":0}
    v9_results = {"WIN":0, "LOSS":0, "TIMEOUT":0, "pnls":[], "entries":0}

    coin_report = []

    for symbol in TEST_COINS:
        sym_display = symbol.replace("USDT", "")
        
        # Fetch data
        candles = get_candles(symbol, "15m", 200)
        if len(candles) < 50:
            print(f"  {sym_display:<12} SKIP (not enough data: {len(candles)} candles)")
            continue
        
        # Get live OBI
        obi = get_orderbook(symbol)
        time.sleep(0.2)  # Rate limit
        
        v8_coin = {"WIN":0,"LOSS":0,"TIMEOUT":0}
        v9_coin = {"WIN":0,"LOSS":0,"TIMEOUT":0}
        v8_entries = v9_entries = 0
        v8_wins = v9_wins = 0

        # Scan each candle (skip last 25 to have room for outcome)
        for i in range(50, len(candles) - 25):
            window = candles[max(0,i-50):i+1]
            closes = [c[4] for c in window]
            
            rsi      = calc_rsi(closes, 14)
            vwap     = calc_vwap(window)
            curr_p   = closes[-1]
            vwap_d   = (curr_p - vwap) / vwap * 100 if vwap > 0 else 0
            vol_spk  = is_vol_spike(window)
            vol_rat  = calc_volume_ratio(window)
            mss      = calc_mss_bullish(closes)
            
            # ── V8 Decision ──
            s8 = score_v8(rsi, vwap_d, vol_spk, mss, obi)
            if s8 >= 40:  # Old threshold
                v8_entries += 1
                outcome, pnl = simulate_trade(candles, i, "buy", 0.09, 0.024)
                v8_coin[outcome] += 1
                v8_results[outcome] += 1
                v8_results["pnls"].append(pnl)
                v8_results["entries"] += 1

            # ── V9 Decision ──
            s9 = score_v9(rsi, vwap_d, vol_spk, mss, obi, vol_rat)
            if s9 >= 45:  # New threshold (stricter)
                v9_entries += 1
                outcome, pnl = simulate_trade(candles, i, "buy", 0.09, 0.04)
                v9_coin[outcome] += 1
                v9_results[outcome] += 1
                v9_results["pnls"].append(pnl)
                v9_results["entries"] += 1

        v8_t = v8_coin['WIN'] + v8_coin['LOSS'] + v8_coin['TIMEOUT']
        v9_t = v9_coin['WIN'] + v9_coin['LOSS'] + v9_coin['TIMEOUT']
        v8_wr = round(v8_coin['WIN']/v8_t*100,1) if v8_t else 0
        v9_wr = round(v9_coin['WIN']/v9_t*100,1) if v9_t else 0
        
        coin_report.append((sym_display, v8_t, v8_wr, v9_t, v9_wr, obi))
        print(f"  {sym_display:<12} | v8: {v8_t} trades WR:{v8_wr}% | v9: {v9_t} trades WR:{v9_wr}% | OBI:{obi:+.2f}")

    # ── FINAL COMPARISON ──
    print("\n" + "=" * 70)
    print("FINAL RESULTS")
    print("=" * 70)
    
    for label, res in [("V8 Mean Reversion", v8_results), ("V9.2 Momentum", v9_results)]:
        t = res['WIN'] + res['LOSS'] + res['TIMEOUT']
        wr = round(res['WIN']/t*100, 1) if t else 0
        avg_pnl = round(sum(res['pnls'])/len(res['pnls']), 2) if res['pnls'] else 0
        total_pnl = round(sum(res['pnls']), 1) if res['pnls'] else 0
        print(f"\n  {label}:")
        print(f"    Total Entries  : {t}")
        print(f"    Win Rate       : {wr}%")
        print(f"    Avg PnL/trade  : {avg_pnl}%")
        print(f"    Total PnL sim  : {total_pnl}%")
        print(f"    Wins/Losses    : {res['WIN']}/{res['LOSS']}")

    # Break-even analysis
    print("\n  [BREAK-EVEN ANALYSIS]")
    print("  V8:  Need 21.4% WR (RR 1:3.75) -- Was getting 0.7% in production")
    print("  V9:  Need 30.8% WR (RR 1:2.25) -- More achievable threshold")

    # Per-coin leaderboard
    print("\n" + "=" * 70)
    print("COIN LEADERBOARD (v9.2 Win Rate)")
    print("=" * 70)
    coin_report.sort(key=lambda x: x[4], reverse=True)
    print(f"  {'Coin':<12} {'v8 N':<6} {'v8 WR%':<8} {'v9 N':<6} {'v9 WR%':<8} {'OBI'}")
    print(f"  {'-'*55}")
    for row in coin_report:
        sym, v8n, v8wr, v9n, v9wr, ob = row
        flag = " <-- BEST" if v9wr >= 40 else (" <-- SKIP" if v9wr == 0 and v9n >= 5 else "")
        print(f"  {sym:<12} {v8n:<6} {v8wr}%{'':<5} {v9n:<6} {v9wr}%{flag}")
    
    # Best coins for v9.2
    best_coins = [r[0] for r in coin_report if r[4] >= 35 and r[3] >= 5]
    if best_coins:
        print(f"\n  RECOMMENDED COINS for v9.2: {best_coins}")
        print(f"  These show 35%+ WR with sufficient sample size")

    print("\n" + "=" * 70)
    print("BACKTEST COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    run_backtest()
