import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- INSTITUTIONAL PORTFOLIO JOURNAL SIMULATION v31.7 ---
# Simulasi Satu Dompet ($10) Mengelola Seluruh Market Secara Kronologis

def get_hot_symbols():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    r = requests.get(url).json()
    df = pd.DataFrame(r)
    df['quoteVolume'] = df['quoteVolume'].astype(float)
    df = df[df['symbol'].str.endswith('USDT')]
    # Ambil Top 20 untuk simulasi agar tidak terlalu berat tapi tetap mewakili market
    return df.sort_values(by='quoteVolume', ascending=False).head(20)['symbol'].tolist()

def fetch_history(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1000"
    try:
        r = requests.get(url, timeout=10).json()
        df = pd.DataFrame(r, columns=['ts','o','h','l','c','v','cts','qv','t','tb','tv','i'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
        return symbol, df.set_index('ts')
    except: return symbol, None

def run_portfolio_simulation():
    symbols = get_hot_symbols()
    print(f"\n[1] Mengambil data historis untuk {len(symbols)} koin terpanas...")
    
    market_data = {}
    all_timestamps = set()
    for s in symbols:
        sym, df = fetch_history(s)
        if df is not None:
            market_data[sym] = df
            all_timestamps.update(df.index.tolist())
    
    sorted_ts = sorted(list(all_timestamps))
    
    # State Portfolio
    wallet = 10.0
    max_slots = 1 # SNIPER MODE v31.8
    active_positions = [] 
    journal = [] 
    
    lev = 10
    fee = 0.0006
    margin_per_trade = 5.0 # Pakai $5 biar berasa
    
    print(f"[2] Memulai simulasi kronologis (Total {len(sorted_ts)} candle)...")
    
    current_day = sorted_ts[0].date()
    daily_summary = []
    
    for ts in sorted_ts:
        # 1. Update Posisi Aktif (Cek SL/TP/TSL)
        for pos in active_positions[:]:
            df = market_data[pos['symbol']]
            if ts not in df.index: continue
            row = df.loc[ts]
            
            # Hitung PnL
            cpnl = ((row['c'] - pos['ent'])/pos['ent']) * lev * 100
            if cpnl > pos['peak']: pos['peak'] = cpnl
            
            # TSL Logic
            if pos['peak'] >= 10:
                locked = (int(pos['peak'] / 10) * 10) - 5
                new_sl = pos['ent'] * (1 + (locked/100)/lev)
                if new_sl > pos['sl']: pos['sl'] = new_sl
            
            # EXIT LOGIC v31.8: ATR or Strict 15% PnL
            max_sl_dist = pos['ent'] * 0.015 # 1.5% price
            if pos['side'] == 'buy':
                pos['sl'] = max(pos['sl'], pos['ent'] - max_sl_dist)
            else:
                pos['sl'] = min(pos['sl'], pos['ent'] + max_sl_dist)

            exit_price = 0
            if row['l'] <= pos['sl']: exit_price = pos['sl']
            elif row['h'] >= pos['tp']: exit_price = pos['tp']
            
            if exit_price > 0:
                final_pnl_pct = ((exit_price - pos['ent'])/pos['ent']) * lev * 100
                net_usd = (final_pnl_pct/100 * pos['margin']) - (pos['margin'] * lev * fee * 2)
                wallet += net_usd
                journal.append({
                    'date': ts, 'symbol': pos['symbol'], 
                    'pnl_usd': round(net_usd, 3), 'pnl_pct': round(final_pnl_pct, 2),
                    'balance': round(wallet, 2)
                })
                active_positions.remove(pos)

        # 2. Daily Reporting
        if ts.date() > current_day:
            day_trades = [j for j in journal if j['date'].date() == current_day]
            day_pnl = sum([t['pnl_usd'] for t in day_trades])
            daily_summary.append({'date': current_day, 'trades': len(day_trades), 'pnl': day_pnl, 'balance': wallet})
            current_day = ts.date()

        # 3. Scanning for New Trades (Jika ada slot kosong)
        if len(active_positions) < max_slots and wallet >= margin_per_trade:
            candidates = []
            for sym, df in market_data.items():
                if any(p['symbol'] == sym for p in active_positions): continue
                if ts not in df.index: continue
                
                row = df.loc[ts]
                # Filter Teknis Sederhana (Mock Engine)
                ema_9 = df['c'].shift(1).rolling(9).mean().loc[ts]
                ema_21 = df['c'].shift(1).rolling(21).mean().loc[ts]
                atr = (df['h'] - df['l']).shift(1).rolling(14).mean().loc[ts]
                rvol = (df['v'] / df['v'].rolling(20).mean()).loc[ts]
                
                if ema_9 > ema_21 and rvol > 1.8 and row['c'] > row['o']:
                    score = rvol * 20 # Simple score for ranking
                    candidates.append({'symbol': sym, 'score': score, 'row': row, 'atr': atr})
            
            # Ambil yang skor tertinggi
            candidates.sort(key=lambda x: x['score'], reverse=True)
            for cand in candidates:
                if len(active_positions) >= max_slots: break
                if wallet < margin_per_trade: break
                
                active_positions.append({
                    'symbol': cand['symbol'], 'side': 'buy', 'ent': cand['row']['c'],
                    'peak': 0, 'sl': cand['row']['c'] - (cand['atr'] * 1.5),
                    'tp': cand['row']['c'] + (cand['atr'] * 4.0),
                    'margin': margin_per_trade
                })
                wallet -= 0 # Margin is locked (simulated by not adding to balance until close)

    return daily_summary, journal

def main():
    print("\n" + "="*80)
    print("JOURNAL TRADING HARIAN: INSTITUTIONAL PREDATOR v31.7")
    print("Simulasi Dompet $10 | 3 Slot Posisi | Market Wide Scanner")
    print("="*80)
    
    summary, journal = run_portfolio_simulation()
    
    print(f"\n{'TANGGAL':<12} | {'TRADES':<7} | {'DAILY PNL':<10} | {'SALDO AKHIR'}")
    print("-" * 80)
    for s in summary:
        color = "+" if s['pnl'] >= 0 else ""
        print(f"{str(s['date']):<12} | {s['trades']:<7} | {color}${s['pnl']:<9.2f} | ${s['balance']:<9.2f}")
    
    print("\n" + "="*80)
    print("CONTOH 5 TRADE TERAKHIR DI BUKU HARIAN:")
    for j in journal[-5:]:
        print(f" >> {j['date']} | {j['symbol']:<10} | PnL: {j['pnl_pct']}% (${j['pnl_usd']}) | Bal: ${j['balance']}")
    
    print("="*80)
    final_bal = summary[-1]['balance'] if summary else 10.0
    profit_total = ((final_bal - 10) / 10) * 100
    print(f"KESIMPULAN: Setelah 15 hari, saldo Bos menjadi ${final_bal:.2f} ({profit_total:+.1f}%)")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
