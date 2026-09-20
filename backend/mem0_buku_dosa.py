"""
====================================================================
🧠 MEM0 BUKU DOSA ENGINE (Official Autonomous Agent Memory via Mem0)
====================================================================
Menggunakan library resmi Mem0 (github.com/mem0ai/mem0) & Gemini LLM.
Sistem ini belajar secara otonom dari setiap trade:
1. Ingesting trade results (PnL, koin, indikator, penyebab loss)
2. Mem0 mengekstrak "learned rules" & "failure patterns" ke Qdrant Vector DB
3. Sebelum trade baru dibuka, Mem0 melakukan semantic search untuk mengecek
   apakah setup trade tersebut mirip dengan bencana masa lalu.
====================================================================
"""

import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

import time
import json
from typing import Dict, Any, List, Tuple
from dotenv import load_dotenv

# Load env dari backend/.env
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_path)

from mem0 import Memory

_mem_instance = None
USER_ID = "cryptoscreener_ai_bot"

def get_mem0_client():
    """Singleton getter untuk instance Mem0 Memory."""
    global _mem_instance
    if _mem_instance is not None:
        return _mem_instance

    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        print("[MEM0 ERROR] GEMINI_API_KEY tidak ditemukan di .env!")
        return None

    # Path untuk local vector database Qdrant
    qdrant_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mem0_qdrant")
    os.makedirs(qdrant_path, exist_ok=True)

    config = {
        "llm": {
            "provider": "gemini",
            "config": {
                "model": "gemini-2.5-flash-lite",
                "api_key": gemini_key,
                "temperature": 0.1
            }
        },
        "embedder": {
            "provider": "gemini",
            "config": {
                "model": "gemini-embedding-001",
                "api_key": gemini_key
            }
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "path": qdrant_path,
                "embedding_model_dims": 768
            }
        }
    }

    try:
        _mem_instance = Memory.from_config(config)
        return _mem_instance
    except Exception as e:
        print(f"[MEM0 INIT FAILED] {e}")
        return None


def record_trade_memory(symbol: str, side: str, pnl_pct: float, pnl_usd: float, 
                        reason: str, tech_summary: str = ""):
    """
    Menyimpan hasil trade ke Mem0 agar AI belajar secara otonom dari outcome.
    """
    client = get_mem0_client()
    if not client:
        return

    status = "WIN" if pnl_pct > 0 else "LOSS"
    log_text = (
        f"Trade Execution Summary:\n"
        f"- Symbol: {symbol}\n"
        f"- Side: {side.upper()}\n"
        f"- Outcome: {status} with PnL {pnl_pct:+.2f}% (${pnl_usd:+.2f})\n"
        f"- Strategy/Reason: {reason}\n"
        f"- Market Context: {tech_summary}\n"
    )

    if status == "LOSS":
        log_text += (
            f"Crucial Post-Mortem Lesson: This trade resulted in a LOSS ({pnl_pct:.2f}%). "
            f"Analyze why {symbol} failed under condition '{reason}'. "
            f"Remember this failure to avoid entering similar bad setups in future spot trades."
        )
    else:
        log_text += (
            f"Crucial Success Pattern: This trade resulted in a PROFIT (+{pnl_pct:.2f}%). "
            f"Remember that {symbol} succeeded under condition '{reason}'."
        )

    try:
        res = client.add(log_text, user_id=USER_ID, metadata={"symbol": symbol, "status": status})
        print(f"[MEM0 LEARNED] 🧠 Hasil trade {symbol} ({status} {pnl_pct:+.2f}%) berhasil dipelajari & disimpan ke Vector DB.")
        return res
    except Exception as e:
        print(f"[MEM0 RECORD ERROR] Gagal menyimpan memori trade: {e}")
        return None


def search_trade_risk(symbol: str, side: str, reason: str, tech_dict: Dict[str, Any]) -> Tuple[bool, str, List[str]]:
    """
    Melakukan semantic memory search sebelum trade dieksekusi.
    Return: (is_safe: bool, warning_msg: str, relevant_memories: list)
    """
    client = get_mem0_client()
    if not client:
        return True, "Mem0 offline, audit dilewati", []

    trend_1h = tech_dict.get('trend_1h', 'UNKNOWN')
    rsi = tech_dict.get('rsi', 50)
    rvol = tech_dict.get('rvol', 1.0)
    ema_9 = tech_dict.get('ema_9', 0)
    ema_21 = tech_dict.get('ema_21', 0)
    downtrend_flag = "Downtrend EMA9<EMA21" if (ema_9 and ema_21 and ema_9 < ema_21) else "Uptrend"

    query = (
        f"Risk analysis for {symbol} {side.upper()} order. "
        f"Strategy: {reason}. "
        f"Indicators: RSI {rsi:.1f}, RVOL {rvol:.2f}, Trend 1h {trend_1h}, {downtrend_flag}. "
        f"Check past failures, toxic coins, dip buying traps, or slippage warnings."
    )

    try:
        results = client.search(query, filters={"user_id": USER_ID}, limit=5)
        memories = []
        is_high_risk = False
        warning_reasons = []

        if results and isinstance(results, dict) and "results" in results:
            raw_mems = results["results"]
        elif isinstance(results, list):
            raw_mems = results
        else:
            raw_mems = []

        for item in raw_mems:
            mem_text = item.get("memory", "") if isinstance(item, dict) else str(item)
            memories.append(mem_text)
            
            # Deteksi apakah memori memperingatkan bahaya
            lowered = mem_text.lower()
            if symbol.lower() in lowered and ("loss" in lowered or "fail" in lowered or "avoid" in lowered or "slippage" in lowered or "dump" in lowered):
                is_high_risk = True
                warning_reasons.append(f"Histori buruk {symbol}: {mem_text}")
            elif "dip buying" in lowered and "fail" in lowered and ("dip" in reason.lower() or ema_9 < ema_21):
                is_high_risk = True
                warning_reasons.append(f"Peringatan Dip Trap: {mem_text}")

        if is_high_risk:
            full_warning = " | ".join(warning_reasons)
            return False, full_warning, memories

        return True, "Aman menurut data memori Mem0.", memories
    except Exception as e:
        print(f"[MEM0 SEARCH ERROR] {e}")
        return True, f"Search error: {e}", []


def seed_historical_failures():
    """
    Melatih Mem0 dari 19 kali kegagalan aktual paper trading di VPS.
    """
    print("[MEM0 SEEDING] Memulai input memori dari 19 data kegagalan VPS...", flush=True)
    historical_losses = [
        {"symbol": "BTWUSDT", "pnl": -19.68, "usd": 0.0, "reason": "SPOT_HYBRID_HTF_BULL+OBI+ on illiquid token, suffered massive slippage on stop loss"},
        {"symbol": "KIIUSDT", "pnl": -12.22, "usd": 0.0, "reason": "CORE2_DIP_SNIPING_V2 buying falling knife, orderbook collapsed"},
        {"symbol": "BTWUSDT", "pnl": -11.67, "usd": 0.0, "reason": "CORE2_NFI_DIP_ABSORPTION re-entered falling coin, double loss"},
        {"symbol": "KIIUSDT", "pnl": -3.55, "usd": 0.0, "reason": "CORE2_NFI_DIP_ABSORPTION dip buying failed, continuous bleed"},
        {"symbol": "CNPYUSDT", "pnl": -2.42, "usd": -3.64, "reason": "Hit SL on dead volume fake breakout"},
        {"symbol": "CNPYUSDT", "pnl": -2.35, "usd": -3.53, "reason": "Hit SL repeatedly, lack of liquidity"},
        {"symbol": "CNPYUSDT", "pnl": -2.30, "usd": -3.45, "reason": "Hit SL again on downtrend"},
        {"symbol": "RAYUSDT", "pnl": -2.21, "usd": -3.32, "reason": "Hit SL during market chop"},
        {"symbol": "RAYUSDT", "pnl": -1.91, "usd": -2.86, "reason": "Hit SL on false momentum signal"},
        {"symbol": "KIIUSDT", "pnl": -1.88, "usd": -2.83, "reason": "Strict Stop Loss hit on dip entry"},
        {"symbol": "KIIUSDT", "pnl": -1.58, "usd": -2.36, "reason": "Hit SL on falling knife"},
        {"symbol": "UNIUSDT", "pnl": -1.43, "usd": 0.0, "reason": "CORE2_NFI_DIP_ABSORPTION buying dip when market was dumping"},
        {"symbol": "BTWUSDT", "pnl": -1.09, "usd": 0.0, "reason": "CORE2_NFI_DIP_ABSORPTION failed dip absorption"},
        {"symbol": "BTWUSDT", "pnl": -2.04, "usd": -3.06, "reason": "Hit SL on BTWUSDT pump and dump coin"},
        {"symbol": "BTWUSDT", "pnl": -1.87, "usd": -2.80, "reason": "Hit SL on BTWUSDT repeatedly"}
    ]

    for item in historical_losses:
        record_trade_memory(
            symbol=item["symbol"],
            side="BUY",
            pnl_pct=item["pnl"],
            pnl_usd=item["usd"],
            reason=item["reason"],
            tech_summary="Low liquidity, falling knife EMA9<EMA21, dead volume or high slippage."
        )
        time.sleep(1) # Delay untuk Gemini rate limit

    print("[MEM0 SEEDING COMPLETED] 🧠 Semua 19 kegagalan resmi tertanam di Vector Memory Mem0!", flush=True)


if __name__ == "__main__":
    if "--seed" in sys.argv:
        seed_historical_failures()
    elif "--search" in sys.argv:
        sym = sys.argv[2] if len(sys.argv) > 2 else "BTWUSDT"
        is_safe, warn, mems = search_trade_risk(sym, "BUY", "CORE2_NFI_DIP_ABSORPTION", {"rsi": 28, "rvol": 0.8, "trend_1h": "BEARISH"})
        print(f"\n[MEM0 AUDIT TEST FOR {sym}]")
        print(f"Safe: {is_safe}")
        print(f"Warning: {warn}")
        print("Relevant Memories:")
        for m in mems:
            print(f" - {m}")
    else:
        print("Gunakan: python mem0_buku_dosa.py --seed (untuk train memory) atau --search <SYMBOL>")
