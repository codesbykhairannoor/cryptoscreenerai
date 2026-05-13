# -*- coding: utf-8 -*-
"""
BACKTEST ROUND 3: SNIPER MODE (Target 100% WR)
Filosofi: Hanya masuk di setup 'Dewa' (Skor > 50) dan hanya di koin yang terbukti patuh.
"""
import sys, os, time, requests, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

BASE_URL = "https://api.bitget.com"
FEE = 0.0012

# HANYA KOIN BINTANG (Proven to follow technicals)
STAR_COINS = ["NEARUSDT", "INJUSDT", "BNBUSDT", "WIFUSDT", "DOGEUSDT", "ATOMUSDT", "LTCUSDT"]

def get_candles(symbol, gran="15m", limit=200):
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/history-candles",
            params={"symbol":symbol,"granularity":gran,"limit":limit,"productType":"USDT-FUTURES"},
            timeout=8)
        d = r.json().get("data")
        return [[float(c[i]) for i in range(6)] for c in d if len(c)>=6] if d else []
    except: return []

def get_obi(symbol):
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/merge-depth",
            params={"symbol":symbol,"productType":"USDT-FUTURES","precision":"scale0","limit":"10"}, timeout=5)
        d = r.json().get("data",{})
        bids, asks = d.get("bids",[]), d.get("asks",[])
        if not bids or not asks: return 0.0
        bv = sum(float(b[1]) for b in bids[:10])
        av = sum(float(a[1]) for a in asks[:10])
        return round((bv-av)/(bv+av),4) if (bv+av)>0 else 0.0
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
    pv=vol=0
    for c in candles[-30:]:
        t=(c[2]+c[3]+c[4])/3; pv+=t*c[5]; vol+=c[5]
    v=pv/vol if vol else price
    return (price-v)/v*100

# ─── Scorer v9.3 Sniper ──────────────────────────────────
def score_sniper(rsi,vd,vs,mss,obi,vr):
    s=0
    # RSI: Momentum must be proven (55-65)
    if 55<=rsi<=65:   s+=40  # NAIK: lebih selektif dari v9.2
    elif 50<=rsi<55:  s+=20
    elif rsi<40:      s-=30  # PENALTI: falling knife
    
    # VWAP: Must be ABOVE VWAP (Confirmed strength)
    if 1.0<=vd<=3.0:  s+=30
    elif 0<vd<1.0:    s+=15
    elif vd<0:        s-=25  # PENALTI: Bearish territory
    
    # Whale & OBI: Must have Whale Support
    if obi>0.25:      s+=30  # Ultra positive OBI
    elif obi>0.10:    s+=15
    
    # Vol & MSS
    if vs: s+=20
    if mss: s+=20
    return s

def simulate(candles,idx,tp_pct=0.09,sl_pct=0.05):
    ep=candles[idx][4]
    tp,sl=ep*(1+tp_pct),ep*(1-sl_pct)
    for i in range(idx+1,min(idx+48,len(candles))): # Look ahead 12 hours
        h,l=candles[i][2],candles[i][3]
        if l<=sl: return "LOSS",round((sl/ep-1)*100-FEE*100,2)
        if h>=tp: return "WIN", round((tp/ep-1)*100-FEE*100,2)
    p=(candles[-1][4]/ep-1)*100
    return ("WIN" if p>0 else "LOSS"),round(p-FEE*100,2)

def main():
    print("="*70)
    print("BACKTEST ROUND 3: SNIPER MODE (BUY ONLY, STAR COINS, SCORE > 50)")
    print("="*70)

    results = []
    for sym in STAR_COINS:
        candles = get_candles(sym)
        if not candles: continue
        obi = get_obi(sym)
        time.sleep(0.5)
        
        wins=losses=0; pnls=[]
        for i in range(50, len(candles)-1):
            w=candles[max(0,i-50):i+1]
            cl=[c[4] for c in w]
            rsi=calc_rsi(cl)
            vd=vwap_dist(w,cl[-1])
            vs=candles[-1][5]>(sum(c[5] for c in w[-6:-1])/5*2.5)
            mss=cl[-1]>max(cl[-22:-2])
            
            s = score_sniper(rsi,vd,vs,mss,obi,1.0)
            if s >= 55: # ULTRA STRICT
                out,pnl = simulate(candles,i)
                if out=="WIN": wins+=1
                else: losses+=1
                pnls.append(pnl)
        
        t=wins+losses
        wr=round(wins/t*100,1) if t else 0
        tot=round(sum(pnls),1) if pnls else 0
        print(f"  {sym:<12} | Trades: {t} | WR: {wr}% | Total PnL: {tot}%")
        if t>0: results.append((sym,t,wr,tot))

    print("\n" + "="*70)
    final_t = sum(r[1] for r in results)
    final_w = sum(r[1]*r[2]/100 for r in results)
    final_wr = round(final_w/final_t*100,1) if final_t else 0
    print(f"OVERALL SNIPER PERFORMANCE:")
    print(f"  Total Trades : {final_t}")
    print(f"  Final Win Rate: {final_wr}%")
    print(f"  Total Profit : {round(sum(r[3] for r in results),1)}%")
    print("="*70)

if __name__=="__main__":
    main()
