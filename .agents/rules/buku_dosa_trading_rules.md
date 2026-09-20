# 📖 BUKU DOSA: ATURAN MUTLAK TRADING SPOT & ANTI-LOOPING

Dokumen ini adalah **Kontrak Tembok Baja** permanen untuk AI Assistant dan Engine Trading.
Dilarang keras melanggar aturan di bawah ini dalam kondisi apa pun.

---

## 🚫 5 DOSA BESAR (SINS REGISTRY) & SANKSI SISTEM

### 1. DOSA #1: MENANGKAP PISAU JATUH (DIP BUYING PADA DOWNTREND)
* **Penyebab:** Membeli koin hanya karena RSI < 35 / oversold saat tren sedang turun.
* **Fakta:** Di pasar altcoin, RSI rendah bukan diskon, tapi tanda koin sedang dibuang bandar.
* **Hukum Mutlak:** 
  - **HARAM BUY** jika `EMA 9 < EMA 21`.
  - **HARAM BUY** jika Trend 1-Jam adalah `BEARISH`.
  - **HARAM BUY** jika harga berada di bawah VWAP.
  - Sinyal `CORE2_NFI_DIP_ABSORPTION` dan segala bentuk dip-sniping telah **DIHAPUS SELAMANYA**.

### 2. DOSA #2: TRADING DI KOIN ZOMBIE / ILLIQUID
* **Penyebab:** Masuk koin dengan orderbook tipis (seperti BTW, KII, CNPY, FLOCK).
* **Fakta:** Slippage menghancurkan Stop Loss hingga rugi -15% s/d -20%.
* **Hukum Mutlak:**
  - Koin `BTWUSDT`, `KIIUSDT`, `CNPYUSDT`, `FLOCKUSDT` masuk **PERMANENT BLACKLIST**.
  - Wajib spread < 0.15% dan volume 24h >= $3,000,000 USDT.

### 3. DOSA #3: ALL-IN MARGIN ($95 DARI MODAL $100)
* **Penyebab:** Menghabiskan 95% saldo untuk satu koin tunggal.
* **Fakta:** Tidak ada ruang untuk nafas pasar. Dua kali kena stop loss langsung margin call.
* **Hukum Mutlak:**
  - Maksimal ukuran posisi adalah **20% dari modal akun** (`FIXED_MARGIN_USDT = 20.0`).
  - Maksimal risiko per trade = $1.00 - $1.50.

### 4. DOSA #4: MASUK DI VOLUME MATI (RVOL < 1.4)
* **Penyebab:** Masuk saat volume perdagangan sepi (RVOL rendah).
* **Hukum Mutlak:**
  - RVOL wajib **>= 1.4** untuk konfirmasi volume riil.

### 5. DOSA #5: REVENGE TRADING & AMNESIA KERUGIAN
* **Penyebab:** Membeli ulang koin yang baru saja bikin rugi.
* **Hukum Mutlak:**
  - Setiap koin yang terkena Stop Loss / rugi **DIKARANTINA 48 JAM PENUH** (`quarantine_registry`).
  - Bot dilarang menyentuh koin tersebut selama masa hukuman.

---

## 🛡️ HAKIM PRA-EKSEKUSI (PRE-TRADE REFLEXION AUDIT)
Setiap order yang hendak dieksekusi di `crypto_engine.py` **WAJIB** melalui audit `BukuDosaJudge.audit_candidate()`.
Jika ada indikasi salah satu dari 5 dosa di atas, order **WAJIB DI-REJECT SECARA FISIK**.

---

## 🤖 PANDUAN UNTUK AI AGENT (ANTI-LOOPING DIRECTIVE)
1. **JANGAN PERNAH** menawarkan strategi "Dip Buying", "Mean Reversion di Altcoin", atau "Beli Oversold" di pasar Spot.
2. **JANGAN PERNAH** melontarkan janji/jargon kuantitatif khayalan (seperti Funding Rate Arbitrage atau HFT) yang tidak sesuai dengan lingkungan VPS Spot Bitget.
3. **JANGAN PERNAH** mengubah alokasi trade menjadi all-in > 25% modal.
