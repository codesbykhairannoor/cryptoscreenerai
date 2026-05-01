import time

class SharedState:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SharedState, cls).__new__(cls)
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
            cls._instance.rt_obi = {} # Symbol -> imbalance
            cls._instance.rt_whale = {} # Symbol -> signal (WHALE_BUY/SELL)
            cls._instance.rt_oi = {} # Symbol -> open interest
            cls._instance.rt_price = {} # Symbol -> last price
            
            # NEWS SENTIMENT (Finnhub)
            cls._instance.news_sentiment = {} # Symbol -> score (-1 to 1)
            cls._instance.rt_news = [] # List of recent headlines
        return cls._instance

    def update_positions(self, positions):
        self.positions = positions
        self.last_update = time.time()

    def update_orders(self, orders):
        self.orders = orders
        self.last_update = time.time()

    def update_balance(self, coin, data):
        self.balances[coin] = data
        self.last_update = time.time()

state = SharedState()
