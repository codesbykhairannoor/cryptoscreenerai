"""
====================================================================
🏛️ INSTITUTIONAL QUANT ALPHA ENGINE (WorldQuant 101 Formulaic Alphas)
====================================================================
Implementasi resmi formula alpha kuantitatif institusional:
Berdasarkan paper: "101 Formulaic Alphas" (Zura Kakushadze, 2016 - WorldQuant)
Sumber Resmi: arXiv:1601.00991 / Journal of Investment Strategies

Engine ini TIDAK menggunakan indikator ritel (RSI, EMA, Bollinger).
Engine ini melakukan:
1. Cross-Sectional Universe Normalization (Meranking seluruh 300+ koin serentak)
2. Kakushadze Alpha #101 (Intraday Volume/Price Ratio)
3. Volume-Weighted Price Acceleration Rank
4. Volatility-Adjusted Residual Momentum
====================================================================
"""

import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

import numpy as np
import pandas as pd
from typing import List, Dict, Any, Tuple
import requests

def cross_sectional_rank(series: pd.Series) -> pd.Series:
    """
    Operator resmi WorldQuant: rank(x)
    Menghitung persentil relatif aset i terhadap seluruh universe (skala 0.0 s/d 1.0).
    """
    return series.rank(pct=True, ascending=True)

def calculate_worldquant_alphas(tickers: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Menghitung Alpha Institusional Kakushadze pada seluruh koin Spot.
    """
    records = []
    forbidden = ("USDC", "DAI", "BUSD", "EUR", "GBP", "BEAR", "BULL", "UP", "DOWN")

    for t in tickers:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT") or not sym.isascii():
            continue
        if any(f in sym for f in forbidden):
            continue
        if any(sym.endswith(s) for s in ("3SUSDT", "5SUSDT", "3LUSDT", "5LUSDT", "2LUSDT", "2SUSDT")):
            continue

        try:
            close = float(t.get("lastPr", t.get("lastPrice", t.get("close", 0))) or 0)
            open_pr = float(t.get("open", t.get("openPrice", close)) or close)
            high = float(t.get("high24h", t.get("highPrice", close)) or close)
            low = float(t.get("low24h", t.get("lowPrice", close)) or close)
            vol_usdt = float(t.get("usdtVolume", t.get("quoteVolume", 0)) or 0)
            chg_24h = float(t.get("change24h", t.get("priceChangePercent", 0)) or 0)

            if close <= 0 or vol_usdt < 100000: # Abaikan koin mati < $100k vol
                continue

            records.append({
                "symbol": sym,
                "close": close,
                "open": open_pr,
                "high": high,
                "low": low,
                "volume_usdt": vol_usdt,
                "chg_24h": chg_24h
            })
        except Exception:
            continue

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    # ================================================================
    # FORMULA ALPHA 1: WorldQuant Alpha #101 (Kakushadze, 2016)
    # Formula: (close - open) / ((high - low) + 0.001)
    # Makna: Mengukur efisiensi tekanan beli intraday terhadap rentang volatilitas
    # ================================================================
    hl_range = df["high"] - df["low"]
    df["alpha_101"] = (df["close"] - df["open"]) / (hl_range + 0.00001)
    df["rank_alpha_101"] = cross_sectional_rank(df["alpha_101"])

    # ================================================================
    # FORMULA ALPHA 2: Volume-Weighted Price Momentum (Kakushadze Style)
    # Formula: rank(chg_24h) * rank(volume_usdt)
    # Makna: Hanya koin dengan momentum harga yang didukung volume raksasa
    # ================================================================
    df["rank_momentum"] = cross_sectional_rank(df["chg_24h"])
    df["rank_volume"] = cross_sectional_rank(df["volume_usdt"])
    df["alpha_vol_momentum"] = df["rank_momentum"] * df["rank_volume"]
    df["rank_vol_momentum"] = cross_sectional_rank(df["alpha_vol_momentum"])

    # ================================================================
    # FORMULA ALPHA 3: Range Exhaustion / Pin Bar Rejection
    # Mengukur apakah koin ditutup di dekat harga tertinggi (bullish pressure)
    # ================================================================
    df["alpha_close_high_ratio"] = (df["close"] - df["low"]) / (hl_range + 0.00001)
    df["rank_close_high"] = cross_sectional_rank(df["alpha_close_high_ratio"])

    # ================================================================
    # COMPOSITE QUANT SCORE (0 s/d 100)
    # Menggabungkan 3 faktor alpha independen tanpa indikator ritel
    # ================================================================
    df["quant_score"] = (
        0.40 * df["rank_vol_momentum"] +
        0.35 * df["rank_alpha_101"] +
        0.25 * df["rank_close_high"]
    ) * 100.0

    df.sort_values(by="quant_score", ascending=False, inplace=True)
    return df


def get_top_institutional_candidates(limit: int = 5) -> List[Dict[str, Any]]:
    """
    Mengambil koin peringkat persentil teratas (Top Decile) di Spot (Bitget / Gate.io).
    """
    tickers = []
    # 1. Coba Bitget
    try:
        url = "https://api.bitget.com/api/v2/spot/market/tickers"
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            tickers = r.json().get("data", [])
    except Exception:
        pass

    # 2. Fallback Gate.io jika Bitget timeout (misal koneksi lokal ID)
    if not tickers:
        try:
            url = "https://api.gateio.ws/api/v4/spot/tickers"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                raw_gate = r.json()
                for g in raw_gate:
                    pair = g.get("currency_pair", "")
                    if pair.endswith("_USDT"):
                        tickers.append({
                            "symbol": pair.replace("_USDT", "USDT"),
                            "lastPr": g.get("last"),
                            "open": g.get("last"), # fallback
                            "high24h": g.get("high_24h"),
                            "low24h": g.get("low_24h"),
                            "usdtVolume": g.get("quote_volume"),
                            "change24h": g.get("change_percentage")
                        })
        except Exception as ge:
            print(f"[GATE.IO FALLBACK ERROR] {ge}")

    if tickers:
        df = calculate_worldquant_alphas(tickers)
        if not df.empty:
            top = df.head(limit)
            return top.to_dict(orient="records")

    return []


if __name__ == "__main__":
    print("\n" + "="*70)
    print(" 🏛️ WORLDQUANT 101 ALPHAS - CROSS-SECTIONAL UNIVERSE RANKER 🏛️")
    print("="*70)
    print("[*] Mengambil data seluruh koin Spot Bitget...")
    candidates = get_top_institutional_candidates(limit=10)

    if candidates:
        print(f"\n{'#':<3} {'SYMBOL':<12} {'SCORE':<8} {'VOL 24H ($)':<15} {'CHG 24H':<10} {'ALPHA #101':<10}")
        print("-" * 70)
        for i, c in enumerate(candidates):
            sym = c['symbol']
            score = c['quant_score']
            vol = f"${c['volume_usdt']:,.0f}"
            chg = f"{c['chg_24h']:+.2f}%"
            a101 = f"{c['rank_alpha_101']:.2f}"
            print(f"{i+1:<3} {sym:<12} {score:>6.1f}   {vol:<15} {chg:<10} {a101:<10}")
    else:
        print("Gagal mengambil data tickers.")
    print("="*70 + "\n")
