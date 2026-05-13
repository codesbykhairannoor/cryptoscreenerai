# -*- coding: utf-8 -*-
"""
FORENSIC FULL AUDIT v2 - CryptoScreenerAI
Fixed: bigint timestamp, transaction rollback handling
"""
import sys, psycopg2

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB_URL = "postgresql://postgres.ejqpkdwxkkcwiyfoqsfd:Kh%40iranaja09@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

def connect():
    return psycopg2.connect(DB_URL, sslmode='require')

def safe_q(cur, sql, label=""):
    """Execute safely with rollback on error"""
    try:
        cur.execute(sql)
        return cur.fetchall()
    except Exception as e:
        cur.execute("ROLLBACK")
        print(f"  [QUERY ERROR] {label}: {e}")
        return []

def run():
    print("=" * 70)
    print("FORENSIC AUDIT v2 - 345 TRADES ANALYSIS")
    print("=" * 70)
    conn = connect()
    conn.autocommit = True
    cur = conn.cursor()
    print("[OK] Connected to Production DB\n")

    T = "trades"  # confirmed table name

    # =========================================================
    # SECTION 1: STATUS BREAKDOWN
    # =========================================================
    print("--- [1] STATUS BREAKDOWN ---")
    rows = safe_q(cur, f"""
        SELECT status, COUNT(*), ROUND(AVG(pnl_pct)::numeric, 4)
        FROM {T} GROUP BY status ORDER BY COUNT(*) DESC
    """, "status")
    print(f"  {'Status':<15} {'Count':<8} {'Avg PnL%'}")
    for r in rows:
        print(f"  {str(r[0]):<15} {r[1]:<8} {r[2]}")
    print()

    # =========================================================
    # SECTION 2: CLOSED TRADES ONLY - REAL WIN/LOSS
    # =========================================================
    print("--- [2] CLOSED TRADES ONLY (WIN/LOSS = Actual Results) ---")
    rows = safe_q(cur, f"""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN pnl_pct < 0 THEN 1 ELSE 0 END) as losses,
            ROUND(AVG(pnl_pct)::numeric, 4) as avg_pnl,
            ROUND(SUM(pnl_pct)::numeric, 4) as total_pnl,
            ROUND(MAX(pnl_pct)::numeric, 4) as best,
            ROUND(MIN(pnl_pct)::numeric, 4) as worst
        FROM {T}
        WHERE status IN ('WIN', 'LOSS', 'CLOSED', 'win', 'loss', 'closed')
    """, "closed")
    if rows:
        r = rows[0]
        t, wins, losses, avg, tot_pnl, best, worst = r
        wr = round(wins/t*100, 1) if t and t > 0 else 0
        print(f"  Closed Trades: {t}")
        print(f"  Wins         : {wins} ({wr}%)")
        print(f"  Losses       : {losses}")
        print(f"  Avg PnL      : {avg}%")
        print(f"  Total PnL    : {tot_pnl}%")
        print(f"  Best Trade   : {best}%")
        print(f"  Worst Trade  : {worst}%")
    print()

    # =========================================================
    # SECTION 3: BUY vs SELL on CLOSED trades
    # =========================================================
    print("--- [3] BUY vs SELL BIAS (Closed Trades Only) ---")
    rows = safe_q(cur, f"""
        SELECT side, COUNT(*),
               SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END),
               ROUND(AVG(pnl_pct)::numeric, 4),
               ROUND(SUM(pnl_pct)::numeric, 4)
        FROM {T}
        WHERE status IN ('WIN', 'LOSS', 'CLOSED', 'win', 'loss', 'closed')
        GROUP BY side
    """, "buy_sell")
    wrs = {}
    for r in rows:
        side, tot, wins, avg, total_p = r
        wr = round(wins/tot*100, 1) if tot > 0 else 0
        wrs[str(side).lower()] = wr
        print(f"  {str(side).upper():<8}: {tot} trades | WR: {wr}% | Avg PnL: {avg}% | Total: {total_p}%")
    
    buy_wr  = wrs.get('buy', wrs.get('long', 0))
    sell_wr = wrs.get('sell', wrs.get('short', 0))
    diff = abs(buy_wr - sell_wr)
    print()
    if diff > 20:
        worse = "SELL" if buy_wr > sell_wr else "BUY"
        print(f"  *** CRITICAL BIAS: {worse} direction is {diff:.0f}% worse ***")
        print(f"  *** Bot is SYSTEMATICALLY WRONG on {worse} trades ***")
    elif sell_wr == 0 and wrs.get('sell', -1) != -1:
        print(f"  *** CRITICAL: SELL trades have 0% win rate! ***")
        print(f"  *** Bot should NEVER take SELL positions ***")
    print()

    # =========================================================
    # SECTION 4: HOUR-BY-HOUR (using timestamp as bigint ms)
    # =========================================================
    print("--- [4] WIN RATE BY HOUR (WIB, from bigint timestamp) ---")
    rows = safe_q(cur, f"""
        SELECT 
            ((timestamp / 1000 + 25200) / 3600 % 24)::int as hour_wib,
            COUNT(*) as total,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
            ROUND(AVG(pnl_pct)::numeric, 3) as avg_pnl
        FROM {T}
        WHERE status IN ('WIN', 'LOSS', 'CLOSED', 'win', 'loss', 'closed')
        GROUP BY hour_wib
        ORDER BY hour_wib
    """, "hour_bias")
    print(f"  {'Hour WIB':<12} {'Trades':<8} {'WR%':<10} {'Avg PnL%'}")
    print(f"  {'-'*45}")
    danger_hours = []
    for r in rows:
        hour, tot, wins, avg = r
        wr = round(wins/tot*100, 1) if tot > 0 else 0
        flag = " <-- DANGER" if wr < 40 and tot >= 3 else ""
        print(f"  {int(hour):02d}:00 WIB    {tot:<8} {wr}%{flag:<11} {avg}")
        if wr < 40 and tot >= 3:
            danger_hours.append(int(hour))
    if danger_hours:
        print(f"\n  Danger hours (WIB): {danger_hours}")
    print()

    # =========================================================
    # SECTION 5: SYMBOL PERFORMANCE
    # =========================================================
    print("--- [5] SYMBOL PERFORMANCE (Closed Trades, Top 30) ---")
    rows = safe_q(cur, f"""
        SELECT symbol, COUNT(*),
               SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END),
               ROUND(AVG(pnl_pct)::numeric, 3),
               ROUND(SUM(pnl_pct)::numeric, 3)
        FROM {T}
        WHERE status IN ('WIN', 'LOSS', 'CLOSED', 'win', 'loss', 'closed')
        GROUP BY symbol
        ORDER BY COUNT(*) DESC
        LIMIT 30
    """, "symbol")
    print(f"  {'Symbol':<25} {'N':<5} {'WR%':<8} {'Avg PnL%':<12} {'Total PnL%'}")
    print(f"  {'-'*65}")
    blacklist = []
    for r in rows:
        sym, tot, wins, avg, total_p = r
        wr = round(wins/tot*100, 1) if tot > 0 else 0
        flag = " <-- BLACKLIST?" if wr == 0 and tot >= 2 else ""
        print(f"  {str(sym):<25} {tot:<5} {wr}%{'':<5} {str(avg):<12} {total_p}{flag}")
        if wr == 0 and tot >= 2:
            blacklist.append(sym)
    if blacklist:
        print(f"\n  ZERO WIN RATE symbols (should be blacklisted): {blacklist}")
    print()

    # =========================================================
    # SECTION 6: SCORE vs WIN RATE (Is scoring calibrated?)
    # =========================================================
    print("--- [6] SCORE CALIBRATION (Does high score = higher win rate?) ---")
    rows = safe_q(cur, f"""
        SELECT 
            CASE 
                WHEN score >= 90 THEN 'A: 90-100'
                WHEN score >= 80 THEN 'B: 80-89'
                WHEN score >= 70 THEN 'C: 70-79'
                WHEN score >= 60 THEN 'D: 60-69'
                ELSE                  'E: <60'
            END as bucket,
            COUNT(*), 
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END),
            ROUND(AVG(pnl_pct)::numeric, 3) as avg_pnl
        FROM {T}
        WHERE status IN ('WIN', 'LOSS', 'CLOSED', 'win', 'loss', 'closed')
          AND score IS NOT NULL
        GROUP BY bucket ORDER BY bucket
    """, "score_cal")
    print(f"  {'Score Bucket':<15} {'N':<5} {'WR%':<8} {'Avg PnL%'}")
    print(f"  {'-'*40}")
    score_issue = False
    for r in rows:
        bucket, tot, wins, avg = r
        wr = round(wins/tot*100, 1) if tot > 0 else 0
        flag = " *** SCORE MISLEADING ***" if 'A:' in str(bucket) and wr < 55 else ""
        print(f"  {str(bucket):<15} {tot:<5} {wr}%{flag:<25} {avg}")
        if 'A:' in str(bucket) and wr < 55:
            score_issue = True
    if score_issue:
        print()
        print("  *** FINDING: Score 90+ tidak berarti profit lebih tinggi. ***")
        print("  *** Sistem scoring kita OVERFIT ke sinyal yang tidak akurat. ***")
    print()

    # =========================================================
    # SECTION 7: REASON/SIGNAL accuracy
    # =========================================================
    print("--- [7] ENTRY SIGNAL ACCURACY (What signals actually work?) ---")
    rows = safe_q(cur, f"""
        SELECT LEFT(reason, 50) as rsn,
               COUNT(*) as n,
               SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
               ROUND(AVG(pnl_pct)::numeric, 3) as avg_pnl
        FROM {T}
        WHERE status IN ('WIN', 'LOSS', 'CLOSED', 'win', 'loss', 'closed')
          AND reason IS NOT NULL AND reason != ''
        GROUP BY rsn
        ORDER BY n DESC
        LIMIT 20
    """, "reason")
    print(f"  {'Signal / Reason':<52} {'N':<4} {'WR%':<7} {'Avg PnL%'}")
    print(f"  {'-'*75}")
    bad_signals = []
    for r in rows:
        rsn, n, wins, avg = r
        wr = round(wins/n*100, 1) if n > 0 else 0
        flag = " *** BAD ***" if wr < 35 and n >= 3 else ""
        print(f"  {str(rsn):<52} {n:<4} {wr}%{flag:<12} {avg}")
        if wr < 35 and n >= 3:
            bad_signals.append(str(rsn))
    if bad_signals:
        print(f"\n  BAD SIGNALS (WR < 35%, remove these):")
        for s in bad_signals:
            print(f"    - {s}")
    print()

    # =========================================================
    # SECTION 8: SESSION PERFORMANCE
    # =========================================================
    print("--- [8] SESSION PERFORMANCE ---")
    rows = safe_q(cur, f"""
        SELECT session, COUNT(*),
               SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END),
               ROUND(AVG(pnl_pct)::numeric, 3),
               ROUND(SUM(pnl_pct)::numeric, 3)
        FROM {T}
        WHERE status IN ('WIN', 'LOSS', 'CLOSED', 'win', 'loss', 'closed')
          AND session IS NOT NULL
        GROUP BY session
        ORDER BY COUNT(*) DESC
    """, "session")
    print(f"  {'Session':<25} {'N':<5} {'WR%':<8} {'Avg PnL%':<12} {'Total PnL%'}")
    print(f"  {'-'*60}")
    for r in rows:
        sess, tot, wins, avg, total_p = r
        wr = round(wins/tot*100, 1) if tot > 0 else 0
        flag = " *** AVOID ***" if wr < 30 and tot >= 3 else ""
        print(f"  {str(sess):<25} {tot:<5} {wr}%{flag:<14} {str(avg):<12} {total_p}")
    print()

    # =========================================================
    # SECTION 9: MARKET (FOREX vs CRYPTO)
    # =========================================================
    print("--- [9] CRYPTO vs FOREX PERFORMANCE ---")
    rows = safe_q(cur, f"""
        SELECT market, COUNT(*),
               SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END),
               ROUND(AVG(pnl_pct)::numeric, 3),
               ROUND(SUM(pnl_pct)::numeric, 3)
        FROM {T}
        WHERE status IN ('WIN', 'LOSS', 'CLOSED', 'win', 'loss', 'closed')
        GROUP BY market
    """, "market")
    for r in rows:
        mkt, tot, wins, avg, total_p = r
        wr = round(wins/tot*100, 1) if tot > 0 else 0
        print(f"  {str(mkt).upper():<10}: {tot} trades | WR: {wr}% | Avg PnL: {avg}% | Total: {total_p}%")
    print()

    # =========================================================
    # SECTION 10: CONSECUTIVE LOSS STREAKS
    # =========================================================
    print("--- [10] CONSECUTIVE LOSS STREAKS ---")
    rows = safe_q(cur, f"""
        SELECT pnl_pct, timestamp FROM {T}
        WHERE status IN ('WIN', 'LOSS', 'CLOSED', 'win', 'loss', 'closed')
        ORDER BY timestamp ASC
    """, "streaks")
    max_streak = cur_streak = 0
    streaks_3plus = 0
    for r in rows:
        pnl = float(r[0]) if r[0] is not None else 0
        if pnl < 0:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            if cur_streak >= 3:
                streaks_3plus += 1
            cur_streak = 0
    if cur_streak >= 3:
        streaks_3plus += 1
    print(f"  Max Consecutive Losses  : {max_streak}")
    print(f"  Streaks of 3+ losses    : {streaks_3plus}")
    if max_streak >= 5:
        print(f"  *** {max_streak} consecutive losses = SYSTEMIC BUG in bot logic ***")
    print()

    # =========================================================
    # SECTION 11: RUNNING trades vs recent closed
    # =========================================================
    print("--- [11] RUNNING TRADES CURRENTLY ---")
    rows = safe_q(cur, f"""
        SELECT symbol, side, score, reason, pnl_pct,
               TO_TIMESTAMP(timestamp/1000)::date as entry_date
        FROM {T}
        WHERE status = 'RUNNING'
        ORDER BY timestamp DESC
        LIMIT 20
    """, "running")
    print(f"  {'Symbol':<20} {'Side':<6} {'Score':<7} {'Current PnL%':<14} {'Reason'}")
    print(f"  {'-'*70}")
    for r in rows:
        sym, side, score, reason, pnl, edate = r
        print(f"  {str(sym):<20} {str(side):<6} {str(score):<7} {str(round(float(pnl),2)):<14} {str(reason)[:30]}")
    print()

    print("=" * 70)
    print("AUDIT COMPLETE - Summary of Critical Findings Below")
    print("=" * 70)

    cur.close()
    conn.close()

if __name__ == "__main__":
    run()
