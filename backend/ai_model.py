import pandas as pd
from sklearn.ensemble import IsolationForest

def analyze_and_sort(df):
    features = ['priceChangePercent', 'quoteVolume']
    X = df[features]

    model = IsolationForest(contamination=0.25, random_state=42)
    df['anomaly'] = model.fit_predict(X)

    potential_coins = df[(df['anomaly'] == -1) & (df['priceChangePercent'] > 0)]
    sorted_coins = potential_coins.sort_values(by='quoteVolume', ascending=False)

    top_20 = sorted_coins.head(20)[['symbol', 'lastPrice', 'priceChangePercent', 'quoteVolume']]
    return top_20.to_dict(orient='records')