import time
import threading

class SharedState:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SharedState, cls).__new__(cls)
            cls._instance._rw_lock = threading.RLock()
            cls._instance.positions = []
            cls._instance.orders = []
            cls._instance.balances = {}
            cls._instance.last_update = 0
            cls._instance.last_order_update = 0
            cls._instance.last_algo_update = 0
            cls._instance.last_acc_update = 0
            cls._instance.sl_placement_cache = {}
            cls._instance.pos_start_time = {} # Symbol -> timestamp
            
            # REAL-TIME INTELLIGENCE (L2 & Whale)
            cls._instance.rt_obi = {}        # Symbol -> imbalance float (-1 to 1)
            cls._instance.rt_whale = {}      # Symbol -> signal str (WHALE_BUY/WHALE_SELL/NORMAL)
            cls._instance.rt_oi = {}         # Symbol -> open interest float
            cls._instance.rt_price = {}      # Symbol -> last price float
            cls._instance.rt_funding = {}    # Symbol -> funding rate float
            cls._instance.rt_volume = {}     # Symbol -> 24h volume float
            cls._instance.rt_change = {}     # Symbol -> 24h price change % float
            cls._instance.rt_high = {}       # Symbol -> 24h high float
            cls._instance.rt_low = {}        # Symbol -> 24h low float
            cls._instance.rt_bid = {}        # Symbol -> best bid float
            cls._instance.rt_ask = {}        # Symbol -> best ask float
            cls._instance.rt_spread = {}     # Symbol -> spread % float
            cls._instance.rt_whale_buy_vol = {}   # Symbol -> cumulative whale buy USD (rolling 5min)
            cls._instance.rt_whale_sell_vol = {}  # Symbol -> cumulative whale sell USD (rolling 5min)
            cls._instance.rt_whale_trades = {}    # Symbol -> list of recent whale trades
            cls._instance.rt_ticker_ts = {}  # Symbol -> last ticker update timestamp
            cls._instance.rt_depth_ts = {}   # Symbol -> last depth update timestamp
            cls._instance.rt_rvol = {}       # Symbol -> Relative Volume float
            cls._instance.rt_atr_pct = {}    # Symbol -> ATR% float
            cls._instance.market_ws_connected = False  # Market WS connection status
            cls._instance.market_ws_symbols = []       # List of symbols being tracked

            # NEWS SENTIMENT (Finnhub)
            cls._instance.news_sentiment = {} # Symbol -> score (-1 to 1)
            cls._instance.rt_news = [] # List of recent headlines
            
            # PERSISTENT TRADE STATE (survives bot restart)
            cls._instance.peak_pnl = {}       # Symbol -> peak PnL% (untuk trailing SL)
            cls._instance.recently_exited = {} # Symbol -> exit timestamp
            cls._instance.exit_pnl = {}        # Symbol -> exit PnL%

            # EARLY SIGNAL STATE
            cls._instance.oi_surge_coins = {}  # Symbol -> {oi_change_pct, oi_now, ...}
            cls._instance.dex_alerts     = []  # List of DEX early-stage pairs
        return cls._instance

    def update_positions(self, positions):
        with self._rw_lock:
            self.positions = positions
            self.last_update = time.time()

    def update_orders(self, orders):
        with self._rw_lock:
            self.orders = orders
            self.last_update = time.time()

    def update_balance(self, coin, data):
        with self._rw_lock:
            self.balances[coin] = data
            self.last_update = time.time()

state = SharedState()



