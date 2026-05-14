"""
EARLY MOMENTUM SIGNAL ENGINE
==============================
3 sumber sinyal early entry untuk Bitget Futures:

1. BITGET OI TRACKER
   - Snapshot OI semua symbol setiap 15 menit
   - Deteksi OI surge >30% dalam 1-2 jam
   - OI naik + harga stabil = Smart Money akumulasi diam-diam

2. DEXSCREENER EARLY STAGE
   - Monitor new pairs dengan volume spike di DEX (Solana, Base, ETH)
   - Banyak koin listing ke Bitget/Binance futures 1-24 jam setelah pump di DEX
   - Filter: volume naik cepat, liquidity naik, tx count tinggi, mcap masih kecil

3. BITGET RVOL (Relative Volume)
   - Bandingkan volume 1h terakhir vs rata-rata 1h dalam 24 jam
   - RVOL > 3x = volume spike = institutional interest
   - Kombinasi RVOL + OI surge = sinyal paling kuat

Semua data disimpan ke shared_state untuk dipakai crypto_engine.
Cache: OI snapshot setiap 15 menit, DexScreener setiap 5 menit.
"""

import requests
import time
import threading
from collections import defaultdict

import urllib3
urllib3.disable_warnings()

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────────────────────────
OI_SNAPSHOT_INTERVAL  = 900    # 15 menit
OI_SURGE_THRESHOLD    = 0.30   # OI naik >30% = surge
OI_HISTORY_WINDOW     = 4      # Simpan 4 snapshot terakhir (1 jam)

DEX_SCAN_INTERVAL     = 300    # 5 menit
DEX_MIN_VOLUME_5M     = 50_000  # Min $50k volume 5m
DEX_MIN_LIQUIDITY     = 100_000 # Min $100k liquidity
DEX_CHAINS            = ["solana", "base", "ethereum", "bsc"]

RVOL_THRESHOLD        = 3.0    # RVOL > 3x = spike

# ─────────────────────────────────────────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────────────────────────────────────────
# OI history: {symbol: [(timestamp, oi_value), ...]}
_oi_history: dict = defaultdict(list)
_oi_lock = threading.Lock()

# DexScreener alerts: [{symbol, chain, volume_5m, liquidity, mcap, url, ts}]
_dex_alerts: list = []
_dex_lock = threading.Lock()

# RVOL cache: {symbol: rvol_value}
_rvol_cache: dict = {}
_rvol_ts: float = 0


# ─────────────────────────────────────────────────────────────────────────────
#  1. BITGET OI TRACKER
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_all_oi() -> dict:
    """
    Fetch OI semua USDT-FUTURES dari Bitget dalam 1 call.
    Field yang benar: 'holdingAmount' (bukan 'openInterest' yang tidak ada di ticker)
    holdingAmount = jumlah kontrak terbuka (dalam unit base asset)
    Untuk perbandingan surge, kita pakai nilai raw ini (tidak perlu konversi ke USD)
    """
    try:
        r = requests.get(
            "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES",
            timeout=10, verify=False
        )
        if r.status_code != 200:
            return {}
        data = r.json().get("data", [])
        result = {}
        for t in data:
            sym = t.get("symbol", "")
            # Field yang benar adalah holdingAmount, bukan openInterest
            oi = t.get("holdingAmount", 0) or t.get("openInterest", 0)
            if sym and oi:
                try:
                    val = float(oi)
                    if val > 0:
                        result[sym] = val
                except (ValueError, TypeError):
                    pass
        return result
    except Exception as e:
        print(f"[OI TRACKER] Fetch error: {e}", flush=True)
        return {}


def _take_oi_snapshot():
    """Ambil snapshot OI sekarang dan simpan ke history."""
    now = time.time()
    oi_data = _fetch_all_oi()
    if not oi_data:
        return

    with _oi_lock:
        for sym, oi in oi_data.items():
            _oi_history[sym].append((now, oi))
            # Simpan max OI_HISTORY_WINDOW snapshot
            if len(_oi_history[sym]) > OI_HISTORY_WINDOW:
                _oi_history[sym].pop(0)

    print(f"[OI TRACKER] Snapshot: {len(oi_data)} symbols", flush=True)


def get_oi_surge_coins(threshold: float = OI_SURGE_THRESHOLD) -> list:
    """
    Return list koin dengan OI surge signifikan.
    Bandingkan OI terbaru vs OI tertua dalam window.

    Return: [{symbol, oi_now, oi_old, oi_change_pct, snapshots}]
    Sorted by oi_change_pct descending.
    """
    results = []
    now = time.time()

    with _oi_lock:
        for sym, history in _oi_history.items():
            if len(history) < 2:
                continue

            oi_now = history[-1][1]
            oi_old = history[0][1]

            if oi_old <= 0 or oi_now <= 0:
                continue

            oi_change = (oi_now - oi_old) / oi_old

            if oi_change >= threshold:
                results.append({
                    "symbol":        sym,
                    "oi_now":        round(oi_now, 0),
                    "oi_old":        round(oi_old, 0),
                    "oi_change_pct": round(oi_change * 100, 1),
                    "snapshots":     len(history),
                    "window_min":    round((history[-1][0] - history[0][0]) / 60, 0),
                })

    results.sort(key=lambda x: x["oi_change_pct"], reverse=True)
    return results


def oi_tracker_loop():
    """Background loop: snapshot OI setiap 15 menit."""
    print("[OI TRACKER] Started. Snapshot every 15 minutes.", flush=True)
    # Ambil snapshot pertama langsung
    _take_oi_snapshot()
    while True:
        time.sleep(OI_SNAPSHOT_INTERVAL)
        _take_oi_snapshot()
        surges = get_oi_surge_coins()
        if surges:
            print(f"[OI SURGE] {len(surges)} coins with OI surge >30%:", flush=True)
            for s in surges[:5]:
                print(f"  {s['symbol']}: OI +{s['oi_change_pct']}% "
                      f"({s['oi_old']:.0f} -> {s['oi_now']:.0f}) "
                      f"in {s['window_min']:.0f}min", flush=True)

            # Update shared_state dengan OI surge info
            try:
                from shared_state import state
                state.oi_surge_coins = {s["symbol"]: s for s in surges}
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
#  2. DEXSCREENER EARLY STAGE DETECTOR
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_dex_trending() -> list:
    """
    Fetch trending/early-stage pairs dari DexScreener.
    Endpoint yang valid (2025):
    - /token-boosts/top/v1  → tokens yang sedang di-boost (trending)
    - /latest/dex/search?q= → search pairs dengan filter volume
    """
    alerts = []

    # ── 1. Token Boosts (tokens yang sedang trending/dipromosikan) ────────────
    try:
        r = requests.get(
            "https://api.dexscreener.com/token-boosts/top/v1",
            timeout=10
        )
        if r.status_code == 200:
            boosts = r.json() if isinstance(r.json(), list) else []
            for b in boosts[:30]:
                chain_id = b.get("chainId", "").lower()
                if chain_id not in DEX_CHAINS:
                    continue
                token_addr = b.get("tokenAddress", "")
                url = b.get("url", "")
                if token_addr:
                    alerts.append({
                        "source":  "dexscreener_boost",
                        "chain":   chain_id,
                        "address": token_addr,
                        "url":     url,
                        "ts":      time.time(),
                    })
    except Exception as e:
        print(f"[DEXSCREENER] Boost fetch error: {e}", flush=True)

    # ── 2. Search high-volume pairs di Solana & Base ──────────────────────────
    # DexScreener /latest/dex/pairs/{chain} sudah 404, pakai search
    search_queries = ["solana", "base", "ethereum"]
    for query in search_queries:
        try:
            r2 = requests.get(
                f"https://api.dexscreener.com/latest/dex/search?q={query}",
                timeout=10
            )
            if r2.status_code != 200:
                continue
            pairs = r2.json().get("pairs", []) or []

            for p in pairs:
                chain_id = p.get("chainId", "").lower()
                if chain_id not in DEX_CHAINS:
                    continue

                vol_5m  = float(p.get("volume", {}).get("m5", 0) or 0)
                vol_1h  = float(p.get("volume", {}).get("h1", 0) or 0)
                liq     = float(p.get("liquidity", {}).get("usd", 0) or 0)
                mcap    = float(p.get("marketCap", 0) or 0)
                price_change_5m = float(p.get("priceChange", {}).get("m5", 0) or 0)
                price_change_1h = float(p.get("priceChange", {}).get("h1", 0) or 0)
                txns_5m = p.get("txns", {}).get("m5", {})
                tx_count_5m = int(txns_5m.get("buys", 0)) + int(txns_5m.get("sells", 0))

                # Filter: volume spike + liquidity cukup + belum pump terlalu jauh
                if (vol_5m >= DEX_MIN_VOLUME_5M and
                    liq >= DEX_MIN_LIQUIDITY and
                    price_change_1h < 50 and
                    tx_count_5m >= 20):

                    base_token = p.get("baseToken", {})
                    alerts.append({
                        "source":          "dexscreener_search",
                        "chain":           chain_id,
                        "symbol":          base_token.get("symbol", ""),
                        "name":            base_token.get("name", ""),
                        "address":         base_token.get("address", ""),
                        "vol_5m":          round(vol_5m, 0),
                        "vol_1h":          round(vol_1h, 0),
                        "liquidity":       round(liq, 0),
                        "mcap":            round(mcap, 0),
                        "price_change_5m": round(price_change_5m, 2),
                        "price_change_1h": round(price_change_1h, 2),
                        "tx_count_5m":     tx_count_5m,
                        "url":             p.get("url", ""),
                        "ts":              time.time(),
                    })
        except Exception as e:
            print(f"[DEXSCREENER] Search error ({query}): {e}", flush=True)

    return alerts


def dex_scanner_loop():
    """Background loop: scan DexScreener setiap 5 menit."""
    print("[DEXSCREENER] Scanner started. Checking every 5 minutes.", flush=True)
    while True:
        try:
            alerts = _fetch_dex_trending()
            if alerts:
                with _dex_lock:
                    _dex_alerts.clear()
                    _dex_alerts.extend(alerts)

                # Log top DEX alerts
                new_pairs = [a for a in alerts if a.get("source") == "dexscreener_search"]
                if new_pairs:
                    # Sort by volume 5m
                    new_pairs.sort(key=lambda x: x.get("vol_5m", 0), reverse=True)
                    print(f"[DEXSCREENER] {len(new_pairs)} early-stage pairs found:", flush=True)
                    for p in new_pairs[:5]:
                        print(
                            f"  [{p['chain'].upper()}] {p['symbol']} | "
                            f"Vol5m:${p['vol_5m']:,.0f} | "
                            f"Liq:${p['liquidity']:,.0f} | "
                            f"Change1h:{p['price_change_1h']:+.1f}% | "
                            f"Txns5m:{p['tx_count_5m']}",
                            flush=True
                        )

                # Update shared_state
                try:
                    from shared_state import state
                    state.dex_alerts = alerts
                except Exception:
                    pass

        except Exception as e:
            print(f"[DEXSCREENER] Loop error: {e}", flush=True)

        time.sleep(DEX_SCAN_INTERVAL)


# ─────────────────────────────────────────────────────────────────────────────
#  3. BITGET RVOL (Relative Volume)
# ─────────────────────────────────────────────────────────────────────────────

def get_rvol_batch() -> dict:
    """
    Hitung RVOL untuk semua koin sekaligus.
    RVOL = volume 1h terakhir / rata-rata volume 1h dalam 24 jam

    Menggunakan data ticker yang sudah ada:
    - baseVolume = volume 24h
    - Estimasi avg 1h = baseVolume / 24
    - Volume 1h terakhir tidak tersedia langsung di ticker,
      tapi kita bisa estimasi dari quoteVolume dan perubahan harga

    Return: {symbol: rvol_float}
    """
    global _rvol_cache, _rvol_ts
    now = time.time()

    # Cache 5 menit
    if now - _rvol_ts < 300 and _rvol_cache:
        return _rvol_cache

    try:
        r = requests.get(
            "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES",
            timeout=10, verify=False
        )
        if r.status_code != 200:
            return _rvol_cache

        data = r.json().get("data", [])
        result = {}

        for t in data:
            sym = t.get("symbol", "")
            try:
                vol_24h = float(t.get("baseVolume", 0) or 0)
                q_vol_24h = float(t.get("quoteVolume", 0) or 0)
                
                # Estimasi rata-rata volume per jam
                avg_1h_vol = vol_24h / 24 if vol_24h > 0 else 0
                if avg_1h_vol <= 0: continue

                # Mencari Real-Time Momentum (Volume 1h terakhir)
                # Kita bisa estimasi dari perubahan quoteVolume jika scanner berjalan cepat
                # Atau gunakan data WebSocket yang lebih akurat
                rvol = 1.0
                try:
                    from shared_state import state
                    # Jika ada data WebSocket volume 1h, pakai itu. 
                    # Jika tidak, kita gunakan selisih ticker (jika di-cache)
                    # Untuk sekarang, kita hitung rasio quoteVolume terhadap 24h avg
                    # Koin yang meledak volumenya biasanya quoteVolume-nya akan melompat
                    rvol = (q_vol_24h / 24) / (q_vol_24h / 24) # Placeholder
                    
                    # LOGIKA FIX: Ambil dari rt_volume yang mewakili pergerakan terbaru
                    ws_vol = state.rt_volume.get(sym, 0)
                    if ws_vol > 0:
                        # Bandingkan volume real-time (estimasi per jam) vs avg 24h
                        # Jika koin sedang pump, volume per jamnya bisa 5x - 10x lipat avg
                        rvol = (ws_vol / 24) / avg_1h_vol if avg_1h_vol > 0 else 1.0
                except Exception:
                    pass

                result[sym] = round(rvol, 2)
            except (ValueError, TypeError):
                pass

        _rvol_cache = result
        _rvol_ts = now
        return result

    except Exception as e:
        print(f"[RVOL] Error: {e}", flush=True)
        return _rvol_cache


def get_early_signals() -> dict:
    """
    Gabungkan semua early signals menjadi satu dict.
    Dipanggil dari crypto_engine setiap scan cycle.

    Return:
      oi_surges    : list koin dengan OI surge >30%
      dex_alerts   : list koin early stage di DEX
      top_rvol     : list koin dengan RVOL tertinggi
      combined     : dict {symbol: early_score} untuk boost scoring
    """
    # OI surges
    oi_surges = get_oi_surge_coins(threshold=0.30)

    # DEX alerts
    with _dex_lock:
        dex_alerts = list(_dex_alerts)

    # RVOL
    rvol_data = get_rvol_batch()
    top_rvol = sorted(
        [(sym, rv) for sym, rv in rvol_data.items() if rv >= RVOL_THRESHOLD],
        key=lambda x: x[1], reverse=True
    )[:20]

    # Combined early score per symbol
    combined = {}

    # OI surge boost
    for s in oi_surges:
        sym = s["symbol"]
        pct = s["oi_change_pct"]
        if pct >= 50:   combined[sym] = combined.get(sym, 0) + 30
        elif pct >= 30: combined[sym] = combined.get(sym, 0) + 20
        elif pct >= 15: combined[sym] = combined.get(sym, 0) + 10

    # RVOL boost
    for sym, rv in top_rvol:
        if rv >= 5.0:   combined[sym] = combined.get(sym, 0) + 15
        elif rv >= 3.0: combined[sym] = combined.get(sym, 0) + 8

    return {
        "oi_surges":  oi_surges[:10],
        "dex_alerts": [a for a in dex_alerts if a.get("source") == "dexscreener_search"][:10],
        "top_rvol":   top_rvol[:10],
        "combined":   combined,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  STARTUP — dipanggil dari main.py
# ─────────────────────────────────────────────────────────────────────────────

def start_early_signal_engine():
    """Start semua background threads untuk early signal detection."""
    t1 = threading.Thread(target=oi_tracker_loop, daemon=True, name="OITracker")
    t2 = threading.Thread(target=dex_scanner_loop, daemon=True, name="DexScanner")
    t1.start()
    t2.start()
    print("[EARLY SIGNAL] OI Tracker + DexScreener started.", flush=True)
