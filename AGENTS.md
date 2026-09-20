# AGENTS.md - Workspace Instructions & Buku Dosa Rules

## MANDATORY TRADING CONSTRAINTS (BUKU DOSA)
1. **NO DIP BUYING / FALLING KNIFE**: NEVER recommend or code dip buying/mean reversion on spot altcoins when EMA9 < EMA21 or 1h trend is bearish.
2. **NO SHITCOINS**: Blacklist `BTWUSDT`, `KIIUSDT`, `CNPYUSDT`, `FLOCKUSDT`. Spread must be < 0.15%, 24h volume >= $3M.
3. **NO ALL-IN**: Max position margin is 20% of balance (max $20 per trade on $100 capital).
4. **NO DEAD VOLUME**: RVOL must be >= 1.4.
5. **NO REVENGE TRADING**: 48h quarantine for any coin hitting stop loss.
6. **NO HALLUCINATIONS**: Do NOT promise futures/arbitrage/HFT features for a Spot-only Bitget bot.
