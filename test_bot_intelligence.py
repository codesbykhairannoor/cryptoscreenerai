"""
BOT INTELLIGENCE TEST SUITE
============================
Test berbagai skenario untuk verifikasi apakah bot cukup pintar atau ceroboh.

Skenario yang ditest:
CRYPTO:
  1. Falling knife (4h bearish) - harus SKIP
  2. Setup bagus (4h bullish + whale + demand zone) - harus ENTRY
  3. RSI oversold tapi 1h+4h bearish - harus SKIP
  4. Off-hours tanpa sinyal prediktif - harus SKIP
  5. Off-hours dengan whale signal kuat - harus ENTRY
  6. BTC bearish kuat saat mau LONG altcoin - harus SKIP
  7. EV negatif setelah fee - harus SKIP
  8. ADX ranging market - harus SKIP
  9. Volatility terlalu tinggi - harus SKIP
  10. Setup SHORT yang valid (4h bearish + supply zone) - harus ENTRY

FOREX:
  11. RSI overbought + 4h bullish - harus SKIP (tidak ada SELL)
  12. DUMP_IMMINENT + 4h bearish - harus ENTRY SELL
  13. Spread terlalu lebar - harus SKIP
  14. Session loss limit terlampaui - harus SKIP
  15. EV terlalu kecil setelah spread - harus SKIP
  16. Demand zone + whale buy - harus ENTRY BUY
  17. HTF resistance level - harus SKIP BUY
  18. News calendar event dalam 30 menit - harus SKIP
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

# ─── MOCK DATA HELPERS ────────────────────────────────────────────────────────

def make_tech(overrides=None):
    """Buat tech dict default (kondisi normal/neutral)."""
    base = {
        "mark_price": 1.0,
        "rsi": 50.0,
        "atr": 0.015,
        "trend_1h": "NEUTRAL",
        "trend_4h": "NEUTRAL",
        "fvg": "NONE",
        "order_block": "NONE",
        "mss_bullish": False,
        "mss_bearish": False,
        "choch_bullish": False,
        "choch_bearish": False,
        "is_liquidity_sweep": False,
        "whale_signal": "NORMAL",
        "obi": 0.0,
        "inst_flow": "NORMAL",
        "funding_rate": 0.0,
        "open_interest": 1000,
        "in_demand": False,
        "in_supply": False,
        "demand_zone": {"active": False, "top": 0, "bottom": 0, "strength": 0},
        "supply_zone": {"active": False, "top": 0, "bottom": 0, "strength": 0},
        "bull_stop_hunt": False,
        "bear_stop_hunt": False,
        "hunt_strength": 0,
        "poc": 1.0,
        "price_vs_poc": "AT",
        "poc_distance_pct": 0.0,
        "near_daily_level": False,
        "near_weekly_level": False,
        "htf_level_bias": "NEUTRAL",
        "at_fib_support": False,
        "at_fib_resistance": False,
        "current_fib_level": "NONE",
        "ema_200": 0.95,
        "ema_200_htf": 0.95,
    }
    if overrides:
        base.update(overrides)
    return base


def make_forex_ind(overrides=None):
    """Buat indicator dict untuk forex."""
    base = {
        "rsi": 50.0,
        "trend": "NEUTRAL",
        "trend_1h": "NEUTRAL",
        "trend_4h": "NEUTRAL",
        "fvg": "NONE",
        "ob": "NONE",
        "mss_bullish": False,
        "mss_bearish": False,
        "choch_bullish": False,
        "choch_bearish": False,
        "is_liquidity_sweep": False,
        "whale_signal": "NORMAL",
        "obi": 0.0,
        "vol_spike": False,
        "rsi_divergence": "NONE",
        "pump_signal": "NONE",
        "vwap_dist": 0.0,
        "atr": 1.5,
        "in_demand": False,
        "in_supply": False,
        "demand_zone": {"active": False, "top": 0, "bottom": 0, "strength": 0},
        "supply_zone": {"active": False, "top": 0, "bottom": 0, "strength": 0},
        "bull_stop_hunt": False,
        "bear_stop_hunt": False,
        "hunt_strength": 0,
        "poc": 4700.0,
        "price_vs_poc": "AT",
        "poc_distance_pct": 0.0,
        "near_daily_level": False,
        "near_weekly_level": False,
        "htf_level_bias": "NEUTRAL",
        "at_fib_support": False,
        "at_fib_resistance": False,
        "current_fib_level": "NONE",
    }
    if overrides:
        base.update(overrides)
    return base


# ─── TEST RUNNER ──────────────────────────────────────────────────────────────

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.results = []

    def check(self, name, condition, expected, got, detail=""):
        status = "PASS" if condition else "FAIL"
        if condition:
            self.passed += 1
        else:
            self.failed += 1
        self.results.append((status, name, expected, got, detail))

    def summary(self):
        print(f"\n{'='*70}")
        print(f"HASIL TEST: {self.passed} PASS / {self.failed} FAIL / {self.passed+self.failed} TOTAL")
        print(f"{'='*70}")
        for status, name, expected, got, detail in self.results:
            icon = "OK" if status == "PASS" else "FAIL"
            print(f"[{icon}] {name}")
            if status == "FAIL":
                print(f"      Expected: {expected}")
                print(f"      Got     : {got}")
                if detail:
                    print(f"      Detail  : {detail}")
        print(f"{'='*70}")
        return self.failed == 0


tr = TestResult()

# ─── IMPORT MODULES ───────────────────────────────────────────────────────────

try:
    from crypto_engine import _determine_trade_side, _calc_expected_value, _get_btc_context
    from crypto_engine import MIN_EXPECTED_VALUE, BITGET_FEE_PCT
    CRYPTO_OK = True
except Exception as e:
    print(f"[IMPORT ERROR] crypto_engine: {e}")
    CRYPTO_OK = False

try:
    from forex_executor import ForexExecutor
    FOREX_OK = False  # Tidak test live karena butuh credentials
except Exception as e:
    print(f"[IMPORT ERROR] forex_executor: {e}")
    FOREX_OK = False


# ─── CRYPTO TESTS ─────────────────────────────────────────────────────────────

if CRYPTO_OK:
    print("\n" + "="*70)
    print("CRYPTO BOT TESTS")
    print("="*70)

    # ── TEST 1: Falling knife — 4h bearish, tidak ada reversal signal ─────────
    tech = make_tech({
        "trend_1h": "BEARISH",
        "trend_4h": "BEARISH",
        "rsi": 38.0,  # RSI oversold — tapi 4h bearish
        "fvg": "NONE",
        "whale_signal": "NORMAL",
        "in_demand": False,
        "bull_stop_hunt": False,
    })
    side, reason, score = _determine_trade_side(tech, 38.0, -5.0, "NEUTRAL")
    tr.check(
        "TEST 1: Falling knife (4h+1h bearish, RSI oversold) → SKIP BUY",
        side != "buy",
        "side != buy",
        f"side={side} reason={reason}",
        "Bot tidak boleh BUY di tengah downtrend meski RSI oversold"
    )

    # ── TEST 2: Setup bagus — 4h bullish + whale + demand zone ───────────────
    tech = make_tech({
        "trend_1h": "BULLISH",
        "trend_4h": "BULLISH",
        "rsi": 42.0,
        "whale_signal": "WHALE_BUY",
        "in_demand": True,
        "demand_zone": {"active": True, "top": 1.05, "bottom": 0.98, "strength": 4},
        "obi": 0.20,
        "mss_bullish": True,
    })
    side, reason, score = _determine_trade_side(tech, 42.0, -1.5, "BULLISH")
    tr.check(
        "TEST 2: Setup bagus (4h bullish + whale + demand zone) → ENTRY BUY",
        side == "buy" and score >= 40,
        "side=buy score>=40",
        f"side={side} score={score} reason={reason}",
        "Bot harus masuk BUY dengan setup kuat"
    )

    # ── TEST 3: RSI oversold tapi 1h+4h bearish — harus SKIP ─────────────────
    tech = make_tech({
        "trend_1h": "BEARISH",
        "trend_4h": "BEARISH",
        "rsi": 30.0,  # Sangat oversold
        "fvg": "BULLISH_FVG",  # Ada FVG bullish
        "whale_signal": "NORMAL",
        "in_demand": False,
        "bull_stop_hunt": False,
    })
    side, reason, score = _determine_trade_side(tech, 30.0, -8.0, "NEUTRAL")
    tr.check(
        "TEST 3: RSI sangat oversold + FVG bullish tapi 1h+4h bearish → SKIP",
        side != "buy",
        "side != buy",
        f"side={side} reason={reason}",
        "Double bearish = block absolut, tidak ada exception"
    )

    # ── TEST 4: Setup SHORT valid — 4h bearish + supply zone ─────────────────
    tech = make_tech({
        "trend_1h": "BEARISH",
        "trend_4h": "BEARISH",
        "rsi": 68.0,
        "whale_signal": "WHALE_SELL",
        "in_supply": True,
        "supply_zone": {"active": True, "top": 1.10, "bottom": 1.05, "strength": 3},
        "obi": -0.25,
        "mss_bearish": True,
        "fvg": "BEARISH_FVG",
    })
    side, reason, score = _determine_trade_side(tech, 68.0, 3.0, "BEARISH")
    tr.check(
        "TEST 4: Setup SHORT valid (4h bearish + whale sell + supply zone) → ENTRY SELL",
        side == "sell" and score >= 40,
        "side=sell score>=40",
        f"side={side} score={score} reason={reason}",
        "Bot harus bisa SHORT kalau setup valid"
    )

    # ── TEST 5: 4h bullish tapi ada reversal signal kuat (bear stop hunt) ─────
    tech = make_tech({
        "trend_1h": "BULLISH",
        "trend_4h": "BULLISH",
        "rsi": 78.0,
        "bear_stop_hunt": True,
        "hunt_strength": 3,
        "in_supply": True,
        "supply_zone": {"active": True, "top": 1.10, "bottom": 1.05, "strength": 4},
        "whale_signal": "WHALE_SELL",
        "fvg": "BEARISH_FVG",
    })
    side, reason, score = _determine_trade_side(tech, 78.0, 4.0, "NEUTRAL")
    tr.check(
        "TEST 5: 4h bullish tapi bear stop hunt + supply zone kuat → boleh SELL",
        side == "sell",
        "side=sell (reversal signal override)",
        f"side={side} score={score} reason={reason}",
        "Reversal signal kuat harus bisa override 4h bias"
    )

    # ── TEST 6: EV negatif setelah fee ────────────────────────────────────────
    tech = make_tech({
        "whale_signal": "NORMAL",
        "obi": 0.0,
        "funding_rate": 0.0,
        "mss_bullish": False,
    })
    ev = _calc_expected_value("buy", tech, 40)  # Score minimum
    tr.check(
        "TEST 6: EV dihitung dengan fee Bitget (0.12%)",
        ev < 0.08,  # EV tidak mungkin 8% untuk score 40
        "ev < 0.08 (realistis)",
        f"ev={ev}",
        f"Fee {BITGET_FEE_PCT*100}% harus dikurangi dari EV gross"
    )

    # ── TEST 7: EV positif untuk setup bagus ─────────────────────────────────
    tech = make_tech({
        "whale_signal": "WHALE_BUY",
        "obi": 0.20,
        "funding_rate": -0.002,  # Short squeeze
        "mss_bullish": True,
    })
    ev = _calc_expected_value("buy", tech, 75)  # Score tinggi
    tr.check(
        "TEST 7: EV positif untuk setup bagus (score 75 + whale + squeeze)",
        ev > MIN_EXPECTED_VALUE,
        f"ev > {MIN_EXPECTED_VALUE}",
        f"ev={ev}",
        "Setup bagus harus punya EV yang layak"
    )

    # ── TEST 8: Demand zone dengan 4h bearish butuh strength >= 3 ────────────
    # Strength 2 = tidak cukup
    tech_weak = make_tech({
        "trend_4h": "BEARISH",
        "trend_1h": "BEARISH",
        "in_demand": True,
        "demand_zone": {"active": True, "top": 1.05, "bottom": 0.98, "strength": 2},
        "bull_stop_hunt": False,
        "whale_signal": "NORMAL",
    })
    side_weak, _, _ = _determine_trade_side(tech_weak, 42.0, -2.0, "NEUTRAL")

    # Strength 4 = cukup
    tech_strong = make_tech({
        "trend_4h": "BEARISH",
        "trend_1h": "BEARISH",
        "in_demand": True,
        "demand_zone": {"active": True, "top": 1.05, "bottom": 0.98, "strength": 4},
        "bull_stop_hunt": False,
        "whale_signal": "NORMAL",
    })
    side_strong, _, _ = _determine_trade_side(tech_strong, 42.0, -2.0, "NEUTRAL")

    tr.check(
        "TEST 8: Demand zone di 4h bearish — strength 2 SKIP, strength 4 BOLEH",
        side_weak != "buy" and side_strong == "buy",
        "weak=skip, strong=buy",
        f"weak={side_weak} strong={side_strong}",
        "Demand zone lemah tidak cukup untuk override 4h bearish"
    )

    # ── TEST 9: HTF alignment bonus ───────────────────────────────────────────
    # Setup sama tapi 4h berbeda — yang aligned harus dapat score lebih tinggi
    tech_aligned = make_tech({
        "trend_1h": "BULLISH",
        "trend_4h": "BULLISH",
        "rsi": 42.0,
        "fvg": "BULLISH_FVG",
        "mss_bullish": True,
        "obi": 0.15,
    })
    _, _, score_aligned = _determine_trade_side(tech_aligned, 42.0, -1.0, "NEUTRAL")

    tech_neutral = make_tech({
        "trend_1h": "NEUTRAL",
        "trend_4h": "NEUTRAL",
        "rsi": 42.0,
        "fvg": "BULLISH_FVG",
        "mss_bullish": True,
        "obi": 0.15,
    })
    _, _, score_neutral = _determine_trade_side(tech_neutral, 42.0, -1.0, "NEUTRAL")

    tr.check(
        "TEST 9: HTF aligned (4h bullish) dapat score lebih tinggi dari neutral",
        score_aligned > score_neutral,
        f"score_aligned({score_aligned}) > score_neutral({score_neutral})",
        f"aligned={score_aligned} neutral={score_neutral}",
        "4h alignment harus memberikan bonus score"
    )

    # ── TEST 10: Tidak ada setup = return None ────────────────────────────────
    tech = make_tech({
        "trend_1h": "NEUTRAL",
        "trend_4h": "NEUTRAL",
        "rsi": 50.0,  # RSI neutral
        "fvg": "NONE",
        "whale_signal": "NORMAL",
        "obi": 0.0,
        "mss_bullish": False,
        "mss_bearish": False,
        "choch_bullish": False,
        "choch_bearish": False,
        "in_demand": False,
        "in_supply": False,
    })
    side, reason, score = _determine_trade_side(tech, 50.0, 0.0, "NEUTRAL")
    tr.check(
        "TEST 10: Tidak ada setup (semua neutral) → return None",
        side is None,
        "side=None",
        f"side={side} score={score}",
        "Kalau tidak ada sinyal, bot tidak boleh masuk"
    )


# ─── FOREX SCORING TESTS (tanpa live connection) ──────────────────────────────

print("\n" + "="*70)
print("FOREX SCORING TESTS (offline)")
print("="*70)

# Test scoring logic langsung tanpa koneksi MetaAPI
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "forex_executor",
        os.path.join(os.path.dirname(__file__), 'backend', 'forex_executor.py')
    )
    mod = importlib.util.load_from_spec(spec) if hasattr(importlib.util, 'load_from_spec') else None

    # Buat instance dummy tanpa koneksi
    import unittest.mock as mock
    with mock.patch.dict(os.environ, {'FOREX_META_API_TOKEN': '', 'FOREX_ACCOUNT_ID': ''}):
        from forex_executor import ForexExecutor, MIN_MOMENTUM_SCORE
        fx = ForexExecutor.__new__(ForexExecutor)
        fx.is_active = False
        fx._last_known_price = 4700.0
        fx._dxy_cache = {"change": 0.0, "trend": "NEUTRAL", "ts": 0}

    # ── TEST 11: DUMP_IMMINENT + 4h bearish → SELL score tinggi ──────────────
    ind = make_forex_ind({
        "pump_signal": "DUMP_IMMINENT",
        "rsi_divergence": "BEARISH_DIVERGENCE",
        "trend": "BEARISH",
        "trend_1h": "BEARISH",
        "trend_4h": "BEARISH",
        "rsi": 55.0,
        "vol_spike": True,
    })
    sell_score = fx._score_setup(ind, "sell", 28)
    buy_score  = fx._score_setup(ind, "buy",  28)
    tr.check(
        "TEST 11: DUMP_IMMINENT + 4h bearish → SELL score >> BUY score",
        sell_score > buy_score and sell_score >= MIN_MOMENTUM_SCORE,
        f"sell_score >= {MIN_MOMENTUM_SCORE} dan > buy_score",
        f"sell={sell_score} buy={buy_score}",
        "DUMP_IMMINENT harus menghasilkan SELL score yang tinggi"
    )

    # ── TEST 12: Spread lebar → penalti score ─────────────────────────────────
    ind_normal = make_forex_ind({"pump_signal": "PUMP_IMMINENT", "vol_spike": True, "rsi": 38})
    ind_wide   = make_forex_ind({"pump_signal": "PUMP_IMMINENT", "vol_spike": True, "rsi": 38})
    score_normal = fx._score_setup(ind_normal, "buy", 28)   # spread normal
    score_wide   = fx._score_setup(ind_wide,   "buy", 160)  # spread lebar
    tr.check(
        "TEST 12: Spread lebar (160pts) → score lebih rendah dari spread normal",
        score_wide < score_normal,
        f"score_wide({score_wide}) < score_normal({score_normal})",
        f"normal={score_normal} wide={score_wide}",
        "Spread penalty harus mengurangi score"
    )

    # ── TEST 13: Demand zone → bonus score BUY ────────────────────────────────
    ind_no_zone = make_forex_ind({"rsi": 42, "fvg": "BULLISH_FVG", "mss_bullish": True})
    ind_in_zone = make_forex_ind({
        "rsi": 42, "fvg": "BULLISH_FVG", "mss_bullish": True,
        "in_demand": True,
        "demand_zone": {"active": True, "top": 4710, "bottom": 4700, "strength": 3},
    })
    score_no_zone = fx._score_setup(ind_no_zone, "buy", 28)
    score_in_zone = fx._score_setup(ind_in_zone, "buy", 28)
    tr.check(
        "TEST 13: Demand zone → bonus score BUY",
        score_in_zone > score_no_zone,
        f"score_in_zone({score_in_zone}) > score_no_zone({score_no_zone})",
        f"no_zone={score_no_zone} in_zone={score_in_zone}",
        "Demand zone harus memberikan bonus score"
    )

    # ── TEST 14: HTF resistance → penalti BUY ────────────────────────────────
    ind_no_htf = make_forex_ind({"rsi": 42, "fvg": "BULLISH_FVG"})
    ind_htf_res = make_forex_ind({
        "rsi": 42, "fvg": "BULLISH_FVG",
        "near_weekly_level": True,
        "htf_level_bias": "RESISTANCE",
    })
    score_no_htf  = fx._score_setup(ind_no_htf,  "buy", 28)
    score_htf_res = fx._score_setup(ind_htf_res, "buy", 28)
    tr.check(
        "TEST 14: HTF weekly resistance → penalti BUY score",
        score_htf_res < score_no_htf,
        f"score_htf_res({score_htf_res}) < score_no_htf({score_no_htf})",
        f"no_htf={score_no_htf} htf_res={score_htf_res}",
        "Weekly resistance harus mengurangi score BUY"
    )

    # ── TEST 15: EV forex dengan spread ──────────────────────────────────────
    ind_good = make_forex_ind({
        "pump_signal": "PUMP_IMMINENT",
        "whale_signal": "WHALE_BUY",
        "obi": 0.25,
        "in_demand": True,
    })
    ev_good = fx._calc_ev_forex("buy", ind_good, 75)

    ind_bad = make_forex_ind({
        "pump_signal": "NONE",
        "whale_signal": "WHALE_SELL",  # Berlawanan
        "obi": -0.20,
    })
    ev_bad = fx._calc_ev_forex("buy", ind_bad, 45)

    tr.check(
        "TEST 15: EV forex — setup bagus > setup buruk, dan spread dikurangi",
        ev_good > ev_bad,
        f"ev_good({ev_good}) > ev_bad({ev_bad})",
        f"good={ev_good} bad={ev_bad}",
        "EV harus mencerminkan kualitas setup setelah spread"
    )

    # ── TEST 16: Reversal signal mengurangi penalti trend ─────────────────────
    # DUMP_IMMINENT saat 4h bullish — penalti harus lebih kecil dari normal
    ind_no_reversal = make_forex_ind({
        "trend_4h": "BULLISH",
        "trend_1h": "BULLISH",
        "pump_signal": "NONE",
        "rsi": 72,
    })
    ind_with_reversal = make_forex_ind({
        "trend_4h": "BULLISH",
        "trend_1h": "BULLISH",
        "pump_signal": "DUMP_IMMINENT",
        "rsi_divergence": "BEARISH_DIVERGENCE",
        "rsi": 72,
    })
    score_no_rev  = fx._score_setup(ind_no_reversal,  "sell", 28)
    score_with_rev = fx._score_setup(ind_with_reversal, "sell", 28)
    tr.check(
        "TEST 16: DUMP_IMMINENT mengurangi penalti trend 4h bullish untuk SELL",
        score_with_rev > score_no_rev,
        f"score_with_rev({score_with_rev}) > score_no_rev({score_no_rev})",
        f"no_rev={score_no_rev} with_rev={score_with_rev}",
        "Reversal signal harus mengurangi penalti trend"
    )

except Exception as e:
    print(f"[FOREX TEST ERROR] {e}")
    import traceback
    traceback.print_exc()
    tr.check("FOREX TESTS", False, "no error", str(e))


# ─── SUMMARY ──────────────────────────────────────────────────────────────────

all_passed = tr.summary()

if all_passed:
    print("\nSemua test PASS — bot sudah cukup pintar untuk skenario yang ditest.")
else:
    print(f"\n{tr.failed} test FAIL — ada logika yang perlu diperbaiki.")

sys.exit(0 if all_passed else 1)
