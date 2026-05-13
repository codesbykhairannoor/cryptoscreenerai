# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 2 v2 - Fixed OBI + Full Optimization
"""
import sys, os, time, requests, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012

COINS_UNIVERSE = [
    # Round 1 stars
    "INJUSDT","BNBUSDT","WIFUSDT","DOGEUSDT","NEARUSDT","ATOMUSDT","LTCUSDT",
    # Round 1 decent
    "ETHUSDT","LINKUSDT","OPUSDT","DOTUSDT","APTUSDT","TIAUSDT",
    # New candidates
    "AAVEUSDT","MKRUSDT","GMXUSDT","RNDRUSDT","GALAUSDT","SANDUSDT",
    "AXSUSDT","IMXUSDT","GRTUSDT","STXUSDT","ALGOUSDT","FLOWUSDT",
    "DYDXUSDT","ONEUSDT","CRVUSDT","SNXUSDT","COMPUSDT",
]

def get_candles(symbol, gran="15m", limit=300):
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles",
            params={"symbol":symbol,"granularity":gran,"limit":limit,"productType":"USDT-FUTURES"},
            timeout=8)
        data = r.json().get("data")
        if data is None:
            return []
        return [[float(c[i]) for i in range(6)] for c in data if len(c)>=6]
    except Exception as e:
        print(f"  Error fetching {symbol}: {e}")
        return []

def get_obi(symbol):
    """OBI dari merge-depth -- format [price, vol]."""
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/merge-depth",
            params={"symbol":symbol,"productType":"USDT-FUTURES","precision":"scale0","limit":"20"},
            timeout=5)
        d = r.json().get("data",{})
        bids = d.get("bids",[])  # [[price, vol], ...]
        asks = d.get("asks",[])
        if not bids or not asks: return 0.0
        bid_vol = sum(float(b[1]) for b in bids[:15])
        ask_vol = sum(float(a[1]) for a in asks[:15])
        total = bid_vol + ask_vol
        return round((bid_vol-ask_vol)/total,4) if total>0 else 0.0
    except: return 0.0

def get_funding(symbol):
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/current-fund-rate",
            params={"symbol":symbol,"productType":"USDT-FUTURES"},timeout=4)
        d = r.json().get("data",[{}])
        if isinstance(d,list): d=d[0] if d else {}
        return float(d.get("fundingRate",0))
    except: return 0.0

# ─── Indicators ───────────────────────────────────────────
def calc_rsi(closes,p=14):
    if len(closes)<p+1: return 50.0
    g,l=[],[]
    for i in range(1,len(closes)):
        d=closes[i]-closes[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g[:p])/p; al=sum(l[:p])/p
    for i in range(p,len(g)):
        ag=(ag*(p-1)+g[i])/p; al=(al*(p-1)+l[i])/p
    return round(100-(100/(1+(ag/(al or 1e-6)))),2)

def vwap_dist(candles,price):
    if len(candles)<10: return 0.0
    pv=vol=0
    for c in candles[-40:]:
        t=(c[2]+c[3]+c[4])/3; pv+=t*c[5]; vol+=c[5]
    v=pv/vol if vol else price
    return (price-v)/v*100

def vol_spike(candles,mult=2.5):
    if len(candles)<6: return False
    avg=sum(c[5] for c in candles[-6:-1])/5
    return candles[-1][5]>avg*mult

def vol_ratio(candles):
    if len(candles)<21: return 1.0
    avg=sum(c[5] for c in candles[-21:-1])/20
    return candles[-1][5]/avg if avg else 1.0

def mss_bull(closes):
    if len(closes)<22: return False
    return closes[-1]>max(closes[-22:-2])

# ─── Scorer v9.2 ──────────────────────────────────────────
def score_v9(rsi,vd,vs,mss,obi,vr,funding=0):
    s=0
    if 52<=rsi<=65:   s+=30
    elif 45<=rsi<52:  s+=15
    elif rsi>75:      s-=20
    elif rsi<35:      s-=15
    if 0.5<=vd<=3.0:  s+=20
    elif 0<vd<0.5:    s+=10
    elif vd<-2.0:     s-=15
    if obi>0.20:   s+=20
    elif obi>0.10: s+=10
    elif obi>0.05: s+=5
    elif obi<-0.15: s-=15
    if vs: s+=15
    elif vr>1.5: s+=8
    if mss: s+=15
    if funding>0.001: s-=10
    return s

# ─── Simulate ─────────────────────────────────────────────
def simulate(candles,idx,tp_pct,sl_pct):
    if idx>=len(candles)-1: return "TIMEOUT",0
    ep=candles[idx][4]
    tp,sl=ep*(1+tp_pct),ep*(1-sl_pct)
    for i in range(idx+1,min(idx+33,len(candles))):
        h,l=candles[i][2],candles[i][3]
        if l<=sl: return "LOSS",round((sl/ep-1)*100-FEE*100,2)
        if h>=tp: return "WIN", round((tp/ep-1)*100-FEE*100,2)
    final=candles[min(idx+32,len(candles)-1)][4]
    pnl=(final/ep-1)*100
    return ("WIN" if pnl>0 else "LOSS"),round(pnl-FEE*100,2)

def run_coin_test(symbol, thresh, tp, sl, candles=None, obi_val=None, funding=0):
    """Test satu coin dengan parameter tertentu."""
    if candles is None:
        candles = get_candles(symbol,"15m",250)
    if len(candles)<70: return 0,0,[]
    if obi_val is None:
        obi_val = get_obi(symbol)
    
    wins=losses=0; pnls=[]
    for i in range(50, len(candles)-33):
        w=candles[max(0,i-50):i+1]
        closes=[c[4] for c in w]
        rsi=calc_rsi(closes)
        vd=vwap_dist(w,closes[-1])
        vs=vol_spike(w)
        vr=vol_ratio(w)
        mss=mss_bull(closes)
        s=score_v9(rsi,vd,vs,mss,obi_val,vr,funding)
        if s>=thresh:
            out,pnl=simulate(candles,i,tp,sl)
            if out=="WIN": wins+=1
            elif out=="LOSS": losses+=1
            pnls.append(pnl)
    return wins,losses,pnls

# ─── MAIN ─────────────────────────────────────────────────
def main():
    print("="*70)
    print("BACKTEST ROUND 2 v2 - LIVE BITGET DATA + OBI FIXED")
    print("="*70)

    # Pre-fetch all candles and OBI
    print("\n[1/3] Fetching live data for all coins...")
    coin_data = {}
    for sym in COINS_UNIVERSE:
        c = get_candles(sym,"15m",100)
        if len(c)>=50:
            obi_val = get_obi(sym)
            funding = get_funding(sym)
            coin_data[sym] = (c, obi_val, funding)
            print(f"  {sym:<20} {len(c)} candles | OBI:{obi_val:+.3f} | FR:{funding:+.5f}", flush=True)
        else:
            print(f"  {sym:<20} SKIP (only {len(c)} candles)", flush=True)
        time.sleep(0.5)

    print(f"\n  Total coins loaded: {len(coin_data)}", flush=True)

    # ── THRESHOLD OPTIMIZATION ──────────────────────────────
    print("\n[2/3] THRESHOLD OPTIMIZATION (TP=9%, SL=4%)", flush=True)
    print(f"  {'Thresh':<8} {'Trades':<8} {'WR%':<8} {'Avg PnL%':<12} {'Total PnL%'}", flush=True)
    print(f"  {'-'*50}", flush=True)
    
    best_thresh = 45; best_thresh_pnl = -9999
    for thresh in [30, 35, 40, 45, 50, 55, 60]:
        all_wins=all_losses=0; all_pnls=[]
        for sym,(candles,obi_val,funding) in coin_data.items():
            w,l,pnls = run_coin_test(sym,thresh,0.09,0.04,candles,obi_val,funding)
            all_wins+=w; all_losses+=l; all_pnls.extend(pnls)
        t=all_wins+all_losses
        wr=round(all_wins/t*100,1) if t else 0
        avg=round(statistics.mean(all_pnls),2) if all_pnls else 0
        tot=round(sum(all_pnls),1) if all_pnls else 0
        status="<-- BEST" if tot>best_thresh_pnl else ""
        print(f"  {thresh:<8} {t:<8} {wr}%{'':<5} {avg:<12} {tot}%  {status}", flush=True)
        if tot>best_thresh_pnl:
            best_thresh_pnl=tot; best_thresh=thresh
    print(f"\n  OPTIMAL THRESHOLD: {best_thresh}", flush=True)

    # ── TP/SL OPTIMIZATION ─────────────────────────────────
    print(f"\n[2b] TP/SL OPTIMIZATION (Threshold={best_thresh})", flush=True)
    print(f"  {'Config':<28} {'Trades':<8} {'WR%':<8} {'Needed WR%':<12} {'Total PnL%'}", flush=True)
    print(f"  {'-'*65}", flush=True)
    
    rr_configs = [
        (0.05, 0.03, "TP5% SL3% (RR1:1.67)"),
        (0.06, 0.03, "TP6% SL3% (RR1:2)"),
        (0.08, 0.04, "TP8% SL4% (RR1:2)"),
        (0.09, 0.04, "TP9% SL4% (RR1:2.25) CURRENT"),
        (0.10, 0.04, "TP10% SL4% (RR1:2.5)"),
        (0.12, 0.04, "TP12% SL4% (RR1:3)"),
        (0.09, 0.05, "TP9% SL5% (RR1:1.8)"),
    ]
    
    best_rr = (0.09,0.04); best_rr_pnl = -9999
    for tp,sl,label in rr_configs:
        all_wins=all_losses=0; all_pnls=[]
        for sym,(candles,obi_val,funding) in coin_data.items():
            w,l,pnls=run_coin_test(sym,best_thresh,tp,sl,candles,obi_val,funding)
            all_wins+=w; all_losses+=l; all_pnls.extend(pnls)
        t=all_wins+all_losses
        wr=round(all_wins/t*100,1) if t else 0
        needed=round(100/(1+tp/sl),1)
        tot=round(sum(all_pnls),1) if all_pnls else 0
        ok="<-- BEST" if tot>best_rr_pnl else ("*** VIABLE" if wr>=needed else "")
        print(f"  {label:<28} {t:<8} {wr}%{'':<5} {needed}%{'':<8} {tot}%  {ok}", flush=True)
        if tot>best_rr_pnl:
            best_rr_pnl=tot; best_rr=(tp,sl)
    
    opt_tp,opt_sl = best_rr
    print(f"\n  OPTIMAL TP/SL: TP={opt_tp*100:.0f}% SL={opt_sl*100:.0f}%", flush=True)

    # ── PER-COIN FINAL RANKING ─────────────────────────────
    print(f"\n[3/3] PER-COIN RANKING (Threshold={best_thresh}, TP={opt_tp*100:.0f}%, SL={opt_sl*100:.0f}%)", flush=True)
    print(f"  {'Coin':<14} {'N':<5} {'WR%':<7} {'Total%':<10} {'Avg%':<8} {'OBI':<8} {'Verdict'}", flush=True)
    print(f"  {'-'*70}", flush=True)
    
    coin_ranking = []
    for sym,(candles,obi_val,funding) in coin_data.items():
        w,l,pnls=run_coin_test(sym,best_thresh,opt_tp,opt_sl,candles,obi_val,funding)
        t=w+l
        wr=round(w/t*100,1) if t else 0
        tot=round(sum(pnls),1) if pnls else 0
        avg=round(statistics.mean(pnls),2) if pnls else 0
        coin_ranking.append((sym.replace("USDT",""),t,wr,tot,avg,obi_val))
    
    coin_ranking.sort(key=lambda x:x[3],reverse=True)
    star_coins=[]
    needed_wr = round(100/(1+opt_tp/opt_sl),1)
    for sym,t,wr,tot,avg,obi_val in coin_ranking:
        if wr>=needed_wr+10 and t>=8:
            verdict="*** TRADE THIS"; star_coins.append(sym)
        elif wr>=needed_wr and t>=5:
            verdict="OK"
        elif t<5:
            verdict="(low sample)"
        else:
            verdict="SKIP"
        print(f"  {sym:<14} {t:<5} {wr}%{'':<4} {tot:<10} {avg:<8} {obi_val:+.3f}  {verdict}", flush=True)

    print(f"\n  FINAL RECOMMENDATION:", flush=True)
    print(f"  Trade only: {star_coins}", flush=True)
    print(f"  Settings  : Score >= {best_thresh} | TP {opt_tp*100:.0f}% | SL {opt_sl*100:.0f}%", flush=True)
    print(f"  Need WR   : {needed_wr}% to break even (after fee)", flush=True)
    
    all_wins2=all_losses2=0; all_pnls2=[]
    for sym,(candles,obi_val,funding) in coin_data.items():
        if sym.replace("USDT","") in star_coins:
            w,l,pnls=run_coin_test(sym,best_thresh,opt_tp,opt_sl,candles,obi_val,funding)
            all_wins2+=w; all_losses2+=l; all_pnls2.extend(pnls)
    if all_pnls2:
        t2=all_wins2+all_losses2
        print(f"\n  STAR COINS ONLY PERFORMANCE:", flush=True)
        print(f"    Trades    : {t2}", flush=True)
        print(f"    Win Rate  : {round(all_wins2/t2*100,1)}%", flush=True)
        print(f"    Total PnL : {round(sum(all_pnls2),1)}%", flush=True)
        print(f"    Avg/trade : {round(statistics.mean(all_pnls2),2)}%", flush=True)

    print("\n" + "="*70)
    print("BACKTEST ROUND 2 COMPLETE")
    print("="*70)

if __name__=="__main__":
    main()
