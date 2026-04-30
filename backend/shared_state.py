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
