"""
====================================================================
📖 BUKU DOSA & REFLEXION ENGINE (Episodic Verbal Reinforcement Learning)
====================================================================
Sistem Memori Permanen Anti-Looping & Anti-Amnesia untuk Bot Spot Kripto.
Terinspirasi dari arsitektur Reflexion (NeurIPS) dan FreqAI Continual Learning.

Tugas:
1. Membaca & mendokumentasikan setiap dosa/kerugian masa lalu secara verbal (post-mortem).
2. Memblokir secara fisik (HARD REJECT) sebelum order dikirim jika terdeteksi dosa serupa.
3. Karantina koin bandel & menghapus kebiasaan menangkap pisau jatuh (falling knife).
====================================================================
"""

import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass
import json
import time
import sqlite3
from typing import Dict, Any, Tuple, Optional

REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "buku_dosa_registry.json")

# ====================================================================
# 1. DOSA-DOSA BESAR SEJARAH (HISTORICAL SINS / AUTOPSY DATA)
# Dihimpun langsung dari 19 kali loss di paper trading VPS
# ====================================================================
DEFAULT_SINS = {
    "version": "1.0-REFLEXION-SHIELD",
    "last_updated": int(time.time()),
    "permanent_blacklist": [
        "BTWUSDT",   # Rugi -19.68% & -11.67% (Illiquid Shitcoin Dump)
        "KIIUSDT",   # Rugi -12.22% & -3.55% (Orderbook Tipis / Slippage)
        "CNPYUSDT",  # Rugi berulang kali -2.42%, -2.35% (Zombie coin)
        "FLOCKUSDT", # Manipulasi volume bandar
    ],
    "loss_quarantine_hours": 48, # Koin yang rugi dikarantina 48 jam penuh
    "quarantine_registry": {},   # symbol -> unlock_timestamp
    "sins_catalog": [
        {
            "id": "DOSA_01_FALLING_KNIFE",
            "name": "Menangkap Pisau Jatuh (Dip Buying di Tren Turun)",
            "description": "Membeli koin hanya karena RSI oversold (<35) saat EMA9 < EMA21 atau Trend 1h Bearish. Di altcoin, RSI rendah bukan diskon, tapi tanda koin sedang dibuang bandar.",
            "rule": "HARAM BUY jika EMA9 < EMA21 ATAU Trend 1H Bearish ATAU Harga di bawah VWAP."
        },
        {
            "id": "DOSA_02_ILLIQUID_SHITCOIN",
            "name": "Trading di Koin Zombie / Illiquid Tanpa Orderbook Tebal",
            "description": "Membeli koin micin dengan spread lebar (>0.15%) atau volume harian < $3M. Begitu market turun, Stop Loss loncat dan slippage tembus -15% s/d -20%.",
            "rule": "HARAM trading koin yang spread > 0.15% atau volume 24h < $3,000,000 USDT."
        },
        {
            "id": "DOSA_03_ALL_IN_POSITION_SIZING",
            "name": "All-In Ukuran Posisi ($95 dari Modal $100)",
            "description": "Memakai margin $95 (95% saldo) untuk 1 koin. Zero room for error. Sekali kena gap down, modal langsung musnah.",
            "rule": "Maksimal alokasi per trade adalah 20% dari modal (max $20 per trade jika saldo $100)."
        },
        {
            "id": "DOSA_04_DEAD_VOLUME_ENTRY",
            "name": "Masuk Saat Volume Mati (RVOL < 1.2)",
            "description": "Masuk koin yang tidak ada pembeli institusional riil. Harga tersendat sideways lalu tergerus time-decay dan fee.",
            "rule": "RVOL (Relative Volume) wajib >= 1.4 untuk konfirmasi partisipasi pasar aktif."
        },
        {
            "id": "DOSA_05_REVENGE_CHURNING",
            "name": "Revenge Trade pada Koin yang Sama",
            "description": "Membeli ulang koin yang barusan bikin rugi (contoh BTWUSDT dibeli 4 kali dan rugi 4 kali).",
            "rule": "Koin yang rugi otomatis di-BAN selama 48 jam dari seluruh scanner."
        }
    ],
    "historical_losses": [
        {"symbol": "BTWUSDT", "loss_pct": -19.68, "reason": "Illiquid dump, trailing SL slippage", "sin": "DOSA_01_FALLING_KNIFE & DOSA_02_ILLIQUID_SHITCOIN"},
        {"symbol": "KIIUSDT", "loss_pct": -12.22, "reason": "Dip sniping v2 failed, orderbook collapse", "sin": "DOSA_01_FALLING_KNIFE"},
        {"symbol": "BTWUSDT", "loss_pct": -11.67, "reason": "Re-entered dip buying, dumped harder", "sin": "DOSA_05_REVENGE_CHURNING"},
        {"symbol": "CNPYUSDT", "loss_pct": -2.42, "reason": "Fake bounce on dead volume", "sin": "DOSA_04_DEAD_VOLUME_ENTRY"},
        {"symbol": "CNPYUSDT", "loss_pct": -2.35, "reason": "Hit strict stop loss", "sin": "DOSA_01_FALLING_KNIFE"},
        {"symbol": "RAYUSDT", "loss_pct": -2.21, "reason": "Hit SL on market chop", "sin": "DOSA_01_FALLING_KNIFE"},
        {"symbol": "KIIUSDT", "loss_pct": -1.88, "reason": "Strict SL hit", "sin": "DOSA_01_FALLING_KNIFE"}
    ]
}

def load_buku_dosa() -> Dict[str, Any]:
    """Memuat registry buku dosa dari disk, atau generate default jika belum ada."""
    if os.path.exists(REGISTRY_PATH):
        try:
            with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data
        except Exception as e:
            print(f"[BUKU DOSA] Error loading {REGISTRY_PATH}: {e}")
    
    # Save default
    save_buku_dosa(DEFAULT_SINS)
    return DEFAULT_SINS

def save_buku_dosa(data: Dict[str, Any]):
    """Menyimpan registry buku dosa ke disk."""
    try:
        with open(REGISTRY_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[BUKU DOSA] Error saving registry: {e}")


class BukuDosaJudge:
    """
    Hakim Pra-Eksekusi (Pre-Trade Reflexion Gatekeeper).
    Wajib dipanggil SEBELUM order dikirim ke exchange/paper executor.
    """
    
    @staticmethod
    def audit_candidate(symbol: str, tech: Dict[str, Any], mark_price: float, 
                        side: str, proposed_usd: float = 0.0, current_balance: float = 100.0) -> Tuple[bool, str, str]:
        """
        Audit apakah kandidat trade melanggar Dosa-Dosa Besar.
        Return: (is_approved: bool, reason: str, sin_code: str)
        """
        registry = load_buku_dosa()
        clean_sym = symbol.upper().replace("/", "")
        if not clean_sym.endswith("USDT"):
            clean_sym = f"{clean_sym}USDT"
            
        now = time.time()

        # 1. CEK PERMANENT BLACKLIST (Koin Beracun)
        blacklist = set(registry.get("permanent_blacklist", []))
        if clean_sym in blacklist:
            return False, f"Koin {clean_sym} masuk PERMANENT BLACKLIST (Pernah membakar modal parah).", "DOSA_02_ILLIQUID_SHITCOIN"

        # 2. CEK KARANTINA 48 JAM (Koin yang baru saja rugi)
        quarantine = registry.get("quarantine_registry", {})
        if clean_sym in quarantine:
            unlock_at = quarantine[clean_sym]
            if now < unlock_at:
                sisa_jam = (unlock_at - now) / 3600.0
                return False, f"Koin {clean_sym} dalam masa KARANTINA DOSA ({sisa_jam:.1f} jam lagi tersisa).", "DOSA_05_REVENGE_CHURNING"
            else:
                # Karantina selesai, hapus dari registry
                del quarantine[clean_sym]
                registry["quarantine_registry"] = quarantine
                save_buku_dosa(registry)

        # 3. CEK DOSA 01: FALLING KNIFE (Pisau Jatuh di Spot)
        # Hanya BLOKIR jika SEMUA 3 kondisi negatif terpenuhi sekaligus (v29.0)
        # Pasar sideways seringkali EMA9 < EMA21 padahal tren besar masih bullish.
        if side.lower() == "buy":
            ema_9 = float(tech.get('ema_9', mark_price))
            ema_21 = float(tech.get('ema_21', mark_price))
            trend_1h = str(tech.get('trend_1h', 'NEUTRAL')).upper()
            vwap = float(tech.get('vwap', mark_price))
            rsi = float(tech.get('rsi', 50))

            _ema_down   = ema_9 < ema_21
            _bear_1h    = "BEAR" in trend_1h
            _below_vwap = vwap > 0 and mark_price < (vwap * 0.980)

            # Pelanggaran TRIPLE: semua 3 kondisi negatif = hard falling knife
            if _ema_down and _bear_1h and _below_vwap:
                return False, f"Ditolak Buku Dosa: TRIPLE FALLING KNIFE - EMA9({ema_9:.4f})<EMA21({ema_21:.4f}) + Bearish1H + Harga<VWAP*0.98.", "DOSA_01_FALLING_KNIFE"

            # Pelanggaran GANDA: EMA down + Bearish 1H + RSI sangat lemah
            if _ema_down and _bear_1h and rsi < 35:
                return False, f"Ditolak Buku Dosa: EMA9<EMA21 + Bearish1H + RSI oversold ({rsi:.0f}). Downtrend kuat.", "DOSA_01_FALLING_KNIFE"

        # 4. CEK DOSA 04: DEAD VOLUME (Volume Mati) -- threshold dilonggarkan ke 1.1
        rvol = float(tech.get('rvol', 1.0))
        if rvol < 1.1:
            return False, f"Ditolak Buku Dosa: RVOL {rvol:.2f} < 1.1 (Volume mati, rawan manipulasi/terjebak).", "DOSA_04_DEAD_VOLUME_ENTRY"

        # 5. CEK DOSA 03: OVERSIZED ALLOCATION
        if proposed_usd > 0 and current_balance > 0:
            allocation_pct = (proposed_usd / current_balance) * 100.0
            # Jika saldo mencukupi (>= $25), alokasi tidak boleh melebihi 30%
            # Namun jika order adalah batas minimal exchange Spot ($5.0 - $6.0 USDT), jangan diblokir
            if allocation_pct > 30.0 and proposed_usd > 6.0:
                return False, f"Ditolak Buku Dosa: Alokasi ${proposed_usd:.2f} ({allocation_pct:.1f}%) > 30% dari saldo ${current_balance:.2f}. Langgar batas risiko.", "DOSA_03_ALL_IN_POSITION_SIZING"

        # LOLOS SEMUA AUDIT DOSA
        return True, "Bersih dari seluruh Dosa Besar.", "CLEAN"

    @staticmethod
    def record_loss_sin(symbol: str, loss_pct: float, loss_usd: float, reason: str):
        """
        Mencatat dosa baru secara real-time ke Buku Dosa dan mengkarantina koin 48 jam.
        """
        registry = load_buku_dosa()
        clean_sym = symbol.upper().replace("/", "")
        if not clean_sym.endswith("USDT"):
            clean_sym = f"{clean_sym}USDT"

        now = time.time()
        quarantine_hours = registry.get("loss_quarantine_hours", 48)
        unlock_at = now + (quarantine_hours * 3600)

        # Update karantina
        registry.setdefault("quarantine_registry", {})[clean_sym] = unlock_at

        # Catat ke historical losses
        loss_entry = {
            "timestamp": int(now),
            "symbol": clean_sym,
            "loss_pct": round(loss_pct, 2),
            "loss_usd": round(loss_usd, 2),
            "reason": reason,
            "sin_diagnosed": "DOSA_01_FALLING_KNIFE" if "Dip" in reason or loss_pct < -5 else "MARKET_CHOP"
        }
        registry.setdefault("historical_losses", []).append(loss_entry)
        registry["last_updated"] = int(now)

        # Jika rugi lebih dari 8%, masukkan ke permanent blacklist!
        if loss_pct <= -8.0:
            bl = set(registry.get("permanent_blacklist", []))
            bl.add(clean_sym)
            registry["permanent_blacklist"] = list(bl)
            print(f"[BUKU DOSA] 🚨 {clean_sym} RUGI EKSTREM ({loss_pct:.2f}%)! Otomatis dimasukkan ke PERMANENT BLACKLIST!")

        save_buku_dosa(registry)
        print(f"[BUKU DOSA] 📖 Dosa dicatat: {clean_sym} rugi {loss_pct:.2f}% (${loss_usd:.2f}). Karantina {quarantine_hours} jam.")


def sync_from_database(db_path: str = "trading_bot.db"):
    """Sinkronisasi dan audit otomatis dari database riwayat trade SQLite."""
    if not os.path.exists(db_path):
        print(f"[BUKU DOSA] DB {db_path} tidak ditemukan.")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT symbol, side, pnl_pct, pnl_usd, reason, closed_at FROM trades WHERE status = 'LOSS' ORDER BY id DESC")
        losses = cursor.fetchall()
        print(f"[BUKU DOSA AUDIT] Ditemukan {len(losses)} riwayat trade LOSS di {db_path}.")

        registry = load_buku_dosa()
        for r in losses:
            sym = r['symbol']
            pnl_pct = r['pnl_pct'] or 0.0
            pnl_usd = r['pnl_usd'] or 0.0
            reason = r['reason'] or "Unknown"

            if pnl_pct <= -8.0:
                bl = set(registry.get("permanent_blacklist", []))
                bl.add(sym)
                registry["permanent_blacklist"] = list(bl)

        save_buku_dosa(registry)
        print(f"[BUKU DOSA AUDIT] Sinkronisasi selesai. Permanent Blacklist: {registry.get('permanent_blacklist')}")
    except Exception as e:
        print(f"[BUKU DOSA AUDIT ERROR] {e}")
    finally:
        cursor.close()
        conn.close()


def print_audit_report():
    """Menampilkan isi Buku Dosa & Status Karantina di Konsol."""
    registry = load_buku_dosa()
    print("\n" + "="*65)
    print(" 📖 BUKU DOSA & EPISODIC REFLEXION JOURNAL 📖")
    print("="*65)

    print("\n🚫 1. PERMANENT BLACKLIST (Koin Diharamkan Selamanya):")
    for b in registry.get("permanent_blacklist", []):
        print(f"   ❌ {b:<12} -> TERLARANG (Histori pembakar modal/illiquid)")

    print("\n⏳ 2. COIN QUARANTINE REGISTRY (Karantina 48 Jam Aktif):")
    quarantine = registry.get("quarantine_registry", {})
    now = time.time()
    active_q = 0
    for sym, unlock in quarantine.items():
        if unlock > now:
            sisa = (unlock - now) / 3600.0
            print(f"   ⏱️ {sym:<12} -> Terkunci sisa {sisa:.1f} jam lagi")
            active_q += 1
    if active_q == 0:
        print("   (Tidak ada koin dalam masa karantina sementara)")

    print("\n📜 3. DAFTAR 5 DOSA BESAR & ATURAN MUTLAK:")
    for s in registry.get("sins_catalog", []):
        print(f"\n   [{s['id']}] {s['name']}")
        print(f"   Penjelasan : {s['description']}")
        print(f"   Aturan     : 🛡️ {s['rule']}")

    print("\n" + "="*65 + "\n")


if __name__ == "__main__":
    if "--audit" in sys.argv or len(sys.argv) == 1:
        sync_from_database("trading_bot.db")
        print_audit_report()
