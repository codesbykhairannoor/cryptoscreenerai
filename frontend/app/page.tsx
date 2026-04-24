'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { getGeminiAnalysis } from './actions';
import TradingChart from '../components/TradingChart';

export default function Home() {
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8000';
  
  const [cryptoData, setCryptoData] = useState<any[]>([]);
  const [forexData, setForexData] = useState<any[]>([]);
  const [idxData, setIdxData] = useState<any[]>([]);
  const [tradeHistory, setTradeHistory] = useState<any[]>([]);
  const [performance, setPerformance] = useState<{wins: number, losses: number, pending: number, win_rate: number} | null>(null);
  const [aiAnalysis, setAiAnalysis] = useState<string>("Menunggu data untuk dianalisis...");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [timeframe, setTimeframe] = useState<string>('15m');

  // WEBSOCKET STATES
  const [livePrices, setLivePrices] = useState<Record<string, number>>({});
  const [priceDirections, setPriceDirections] = useState<Record<string, 'up' | 'down'>>({});
  const wsRef = useRef<WebSocket | null>(null);

  const fetchData = useCallback(async () => {
    try {
      // Fetch Crypto Data
      const resCrypto = await fetch(`${backendUrl}/api/top-coins?timeframe=${timeframe}`, { cache: 'no-store' });
      if (resCrypto.ok) {
        const json = await resCrypto.json();
        setCryptoData(json.data || []);
      }

      // Fetch Forex Data
      const resForex = await fetch(`${backendUrl}/api/forex?timeframe=${timeframe}`, { cache: 'no-store' });
      if (resForex.ok) {
        const json = await resForex.json();
        setForexData(json.data || []);
      }

      // Fetch IDX Data
      const resIdx = await fetch(`${backendUrl}/api/idx-stocks?timeframe=${timeframe}`, { cache: 'no-store' });
      if (resIdx.ok) {
        const json = await resIdx.json();
        setIdxData(json.data || []);
      }
      
      // Fetch Performance Data
      const resPerf = await fetch(`${backendUrl}/api/performance`, { cache: 'no-store' });
      if (resPerf.ok) {
        const json = await resPerf.json();
        setPerformance(json.data);
      }

      // Fetch Trade History
      const resHistory = await fetch(`${backendUrl}/api/trade-history`, { cache: 'no-store' });
      if (resHistory.ok) {
        const json = await resHistory.json();
        setTradeHistory(json.data || []);
      }
      
      setLastUpdated(new Date());
    } catch (error) {
      console.error("Gagal konek ke Python Backend:", error);
    }
  }, [backendUrl, timeframe]);

  // Initial Fetch & Heavy Polling Setup
  useEffect(() => {
    fetchData(); 
    const interval = setInterval(fetchData, 15000); 
    return () => clearInterval(interval);
  }, [fetchData]);

  // Direct Binance WebSocket Setup for BOTH Crypto and Forex (PAXGUSDT)
  useEffect(() => {
    if (cryptoData.length === 0 && forexData.length === 0) return;

    const cryptoSymbols = cryptoData.map(c => `${c.symbol.toLowerCase()}@ticker`);
    // We keep forex symbols in the map in case some are on Binance, but XAUUSD will poll
    const forexSymbols = forexData.filter(f => f.symbol !== 'XAUUSD').map(f => `${f.symbol.toLowerCase()}@ticker`);
    const allSymbols = [...cryptoSymbols, ...forexSymbols].join('/');
    
    if (!allSymbols) return;

    const wsUrl = `wss://stream.binance.vision:9443/stream?streams=${allSymbols}`;

    if (wsRef.current) {
        wsRef.current.close();
    }

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.data && message.data.s && message.data.c) {
            const symbol = message.data.s; 
            const currentPrice = parseFloat(message.data.c);
            
            setLivePrices(prev => {
                const prevPrice = prev[symbol];
                if (prevPrice && prevPrice !== currentPrice) {
                    setPriceDirections(pd => ({
                        ...pd,
                        [symbol]: currentPrice > prevPrice ? 'up' : 'down'
                    }));
                }
                return { ...prev, [symbol]: currentPrice };
            });
        }
    };

    return () => {
        if (wsRef.current) {
            wsRef.current.close();
        }
    };
  }, [cryptoData, forexData]);

  const handlePickTrade = async (asset: any) => {
    if (asset.entry_price <= 0) {
      alert("Belum ada target harga untuk aset ini.");
      return;
    }

    try {
      const res = await fetch(`${backendUrl}/api/select-trade`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: asset.symbol,
          entry: asset.entry_price,
          tp: asset.tp_price,
          sl: asset.sl_price
        })
      });

      if (res.ok) {
        const result = await res.json();
        alert(result.message);
        fetchData(); // Refresh history
      }
    } catch (err) {
      console.error("Gagal memilih trade", err);
    }
  };

  // Remove flash animation after 500ms
  useEffect(() => {
      const timers = Object.keys(priceDirections).map(symbol => {
          return setTimeout(() => {
              setPriceDirections(pd => {
                  const newPd = { ...pd };
                  delete newPd[symbol];
                  return newPd;
              });
          }, 500);
      });
      return () => timers.forEach(clearTimeout);
  }, [priceDirections]);

  // Gemini Analysis Effect
  useEffect(() => {
    if (cryptoData.length > 0) {
      const fetchAI = async () => {
        try {
          const top5Coins = cryptoData.slice(0, 5).map((c: any) => 
            `${c.symbol} (Trend: ${c.trend}, Whale Ratio: ${c.whale_ratio}x, RSI: ${c.rsi_15m}, Sinyal: ${c.trade_signal})`
          ).join(" | ");
          
          const result = await getGeminiAnalysis(top5Coins);
          setAiAnalysis(result);
        } catch (error) {
          console.error("Failed to fetch AI analysis", error);
        }
      };
      
      if (aiAnalysis.includes("Menunggu data")) {
        fetchAI();
      }
    }
  }, [cryptoData, aiAnalysis]);

  return (
    <main className="min-h-screen bg-[#0d1117] text-white p-8 font-sans">
      <div className="max-w-7xl mx-auto space-y-8">
        
        <header className="border-b border-gray-800 pb-4 flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
          <div>
            <h1 className="text-3xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-emerald-400">
              Chetilization AI Pro
            </h1>
            <p className="text-gray-400 mt-2 flex items-center gap-2">
              <span>Live WebSockets</span> 
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
              <span>• Institutional AI • Proof of Win-Rate</span>
            </p>
          </div>
          
          <div className="flex flex-col sm:flex-row items-center gap-4 sm:gap-6 w-full md:w-auto">
              <div className="flex bg-gray-900/80 p-1 rounded-lg border border-gray-700 shadow-inner w-full sm:w-auto overflow-x-auto">
                {['15m', '1h', '4h', '1d'].map((tf) => (
                  <button
                    key={tf}
                    onClick={() => setTimeframe(tf)}
                    className={`px-4 py-1.5 rounded-md text-xs font-bold transition-all whitespace-nowrap flex-1 sm:flex-none ${
                      timeframe === tf 
                        ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/30 scale-105' 
                        : 'text-gray-500 hover:text-gray-300'
                    }`}
                  >
                    {tf.toUpperCase()}
                  </button>
                ))}
              </div>

              {performance && (
                <div className="bg-gray-900 border border-gray-700 px-4 py-2 rounded-lg flex gap-4 text-sm shadow-xl w-full sm:w-auto justify-center">
                    <div className="flex flex-col items-center">
                        <span className="text-gray-400 text-[10px] uppercase tracking-wider">Win Rate</span>
                        <span className={`font-bold text-base ${performance.win_rate > 50 ? 'text-emerald-400' : 'text-yellow-400'}`}>
                            {performance.win_rate}%
                        </span>
                    </div>
                    <div className="w-px bg-gray-700"></div>
                    <div className="flex flex-col items-center">
                        <span className="text-gray-400 text-[10px] uppercase tracking-wider">W / L</span>
                        <span className="font-bold text-base text-white">
                            <span className="text-emerald-400">{performance.wins}</span> - <span className="text-red-400">{performance.losses}</span>
                        </span>
                    </div>
                    <div className="w-px bg-gray-700"></div>
                    <div className="flex flex-col items-center">
                        <span className="text-gray-400 text-[10px] uppercase tracking-wider">Pending</span>
                        <span className="font-bold text-base text-blue-400">{performance.pending}</span>
                    </div>
                </div>
              )}
          </div>
        </header>

        <section className="bg-gray-900 border border-gray-700 rounded-xl p-6 shadow-lg">
          <div className="flex items-center space-x-2 mb-4">
            <span className="text-xl">✨</span>
            <h2 className="text-xl font-semibold text-blue-300">Rekomendasi Entry AI (Gemini CRO)</h2>
          </div>
          <p className="text-gray-300 leading-relaxed text-sm">
            {aiAnalysis}
          </p>
        </section>

        {/* CRYPTO SECTION */}
        <section>
          <h2 className="text-xl font-semibold mb-4 text-emerald-300">Live Crypto Screener (Click row for Chart)</h2>
          <div className="overflow-x-auto rounded-lg border border-gray-800 shadow-xl">
            <table className="w-full text-left text-sm text-gray-400 whitespace-nowrap">
              <thead className="text-xs text-gray-400 uppercase bg-gray-900 border-b border-gray-800">
                <tr>
                  <th className="px-4 py-4 font-medium">Asset</th>
                  <th className="px-4 py-4 font-medium">Price</th>
                  <th className="px-4 py-4 font-medium hidden sm:table-cell text-emerald-400">Whale</th>
                  <th className="px-4 py-4 font-medium hidden md:table-cell">RSI</th>
                  <th className="px-4 py-4 font-medium text-orange-300">Targets</th>
                  <th className="px-4 py-4 font-medium text-blue-300">Signal</th>
                  <th className="px-4 py-4 font-medium text-center">Trade</th>
                </tr>
              </thead>
              <tbody>
                {cryptoData.length === 0 ? (
                   <tr><td colSpan={7} className="text-center py-8 text-gray-500">Loading Crypto Data...</td></tr>
                ) : cryptoData.map((coin: any, index: number) => {
                  const displayPrice = livePrices[coin.symbol] || parseFloat(coin.lastPrice);
                  const direction = priceDirections[coin.symbol];
                  const isExpanded = expandedRow === coin.symbol;
                  
                  return (
                  <React.Fragment key={index}>
                      <tr 
                          className="bg-[#0d1117] border-b border-gray-800 hover:bg-gray-800/50 transition-colors cursor-pointer"
                      >
                        <td onClick={() => setExpandedRow(isExpanded ? null : coin.symbol)} className="px-4 py-4 font-bold text-white">
                          <div className="flex items-center gap-2">
                              {coin.symbol}
                              <span className="text-xs text-gray-600">{isExpanded ? '▼' : '▶'}</span>
                          </div>
                          <div className={`text-[10px] mt-1 uppercase tracking-wider font-semibold ${coin.trend?.includes('Bullish') ? 'text-emerald-500' : 'text-red-500'}`}>
                            {coin.trend || 'Unknown'}
                          </div>
                        </td>
                        
                        <td onClick={() => setExpandedRow(isExpanded ? null : coin.symbol)} className="px-4 py-4">
                          <div className={`font-mono text-lg transition-colors duration-200 ${
                              direction === 'up' ? 'text-emerald-400 drop-shadow-[0_0_8px_rgba(52,211,153,0.8)]' : 
                              direction === 'down' ? 'text-red-400 drop-shadow-[0_0_8px_rgba(248,113,113,0.8)]' : 
                              'text-white'
                          }`}>
                            ${displayPrice.toFixed(4)}
                          </div>
                          <span className="text-emerald-400 text-xs">+{parseFloat(coin.priceChangePercent).toFixed(2)}%</span>
                        </td>
                        
                        <td onClick={() => setExpandedRow(isExpanded ? null : coin.symbol)} className="px-4 py-4 bg-emerald-900/5 border-l border-emerald-900/20 hidden sm:table-cell">
                          <span className="font-semibold text-emerald-300">${Math.round(coin.bid_wall_usdt / 1000)}k</span><br/>
                          <span className="text-[10px] text-gray-500">at ${parseFloat(coin.bid_wall_price).toFixed(2)}</span>
                        </td>
                        
                        <td onClick={() => setExpandedRow(isExpanded ? null : coin.symbol)} className="px-4 py-4 hidden md:table-cell">
                          <span className={`font-bold ${coin.rsi_15m < 45 ? 'text-emerald-400' : coin.rsi_15m > 70 ? 'text-red-400' : 'text-yellow-400'}`}>
                            {coin.rsi_15m}
                          </span>
                        </td>

                        <td onClick={() => setExpandedRow(isExpanded ? null : coin.symbol)} className="px-4 py-4 text-[10px]">
                          {coin.entry_price > 0 ? (
                            <div className="flex flex-col gap-0.5">
                               <span className="text-emerald-400">TP: ${coin.tp_price}</span>
                               <span className="text-red-400">SL: ${coin.sl_price}</span>
                            </div>
                          ) : (
                            <span className="text-gray-600">-</span>
                          )}
                        </td>

                        <td onClick={() => setExpandedRow(isExpanded ? null : coin.symbol)} className="px-4 py-4">
                          <span className={`px-2 py-1 rounded text-[9px] font-bold uppercase tracking-wider block text-center ${
                            coin.trade_signal.includes('STRONG BUY') ? 'bg-emerald-600 text-white' : 
                            coin.trade_signal.includes('FAST SCALP') ? 'bg-orange-500/20 text-orange-400' : 
                            coin.trade_signal.includes('DANGER') ? 'bg-red-500/20 text-red-400' : 
                            'bg-gray-800 text-gray-500'
                          }`}>
                            {coin.trade_signal}
                          </span>
                        </td>

                        <td className="px-4 py-4 text-center">
                            <button 
                                onClick={(e) => { e.stopPropagation(); handlePickTrade(coin); }}
                                className="bg-emerald-500/20 hover:bg-emerald-500/40 text-emerald-400 p-2 rounded-full border border-emerald-500/30 transition-all text-xs"
                                title="Ambil Trade Ini"
                            >
                                ✅
                            </button>
                        </td>
                      </tr>
                      {isExpanded && (
                          <tr className="bg-[#111827]">
                              <td colSpan={7} className="p-4 border-b border-gray-800">
                                  <TradingChart 
                                      symbol={coin.symbol} 
                                      entryPrice={coin.entry_price} 
                                      tpPrice={coin.tp_price} 
                                      slPrice={coin.sl_price} 
                                  />
                              </td>
                          </tr>
                      )}
                  </React.Fragment>
                )})}
              </tbody>
            </table>
          </div>
        </section>

        {/* FOREX SECTION */}
        <section>
          <h2 className="text-xl font-semibold mb-4 text-amber-400">Forex & Commodities (Spot OANDA)</h2>
          <div className="overflow-x-auto rounded-lg border border-gray-800 shadow-xl">
            <table className="w-full text-left text-sm text-gray-400 whitespace-nowrap">
              <thead className="text-xs text-gray-400 uppercase bg-gray-900 border-b border-gray-800">
                <tr>
                  <th className="px-4 py-4 font-medium">Symbol</th>
                  <th className="px-4 py-4 font-medium">Price</th>
                  <th className="px-4 py-4 font-medium">RSI (15m)</th>
                  <th className="px-4 py-4 font-medium text-orange-300">Target (TP) & Risk (SL)</th>
                  <th className="px-4 py-4 font-medium text-blue-300">Trade Signal</th>
                  <th className="px-4 py-4 font-medium text-center">Action</th>
                </tr>
              </thead>
              <tbody>
                {forexData.length === 0 ? (
                   <tr><td colSpan={6} className="text-center py-8 text-gray-500">Loading Forex Data...</td></tr>
                ) : forexData.map((asset: any, index: number) => {
                  const displayPrice = livePrices[asset.symbol] || parseFloat(asset.lastPrice);
                  const direction = priceDirections[asset.symbol];
                  const isExpanded = expandedRow === asset.symbol;
                  
                  return (
                  <React.Fragment key={index}>
                      <tr 
                          className="bg-[#0d1117] border-b border-gray-800 hover:bg-gray-800/50 transition-colors cursor-pointer"
                      >
                        <td onClick={() => setExpandedRow(isExpanded ? null : asset.symbol)} className="px-4 py-4 font-bold text-white">
                            <div className="flex items-center gap-2">
                                <span className="text-xl">🪙</span> {asset.symbol}
                                <span className="text-xs text-gray-600">{isExpanded ? '▼' : '▶'}</span>
                            </div>
                            <div className={`text-[10px] mt-1 uppercase tracking-wider font-semibold ${asset.trend?.includes('Bullish') ? 'text-emerald-500' : 'text-red-500'}`}>
                                {asset.trend || 'Unknown'}
                            </div>
                        </td>
                        
                        <td onClick={() => setExpandedRow(isExpanded ? null : asset.symbol)} className="px-4 py-4">
                          <div className={`font-mono text-lg transition-colors duration-200 ${
                              direction === 'up' ? 'text-emerald-400 drop-shadow-[0_0_8px_rgba(52,211,153,0.8)]' : 
                              direction === 'down' ? 'text-red-400 drop-shadow-[0_0_8px_rgba(248,113,113,0.8)]' : 
                              'text-white'
                          }`}>
                            ${displayPrice.toFixed(2)}
                          </div>
                        </td>
                        
                        <td onClick={() => setExpandedRow(isExpanded ? null : asset.symbol)} className="px-4 py-4">
                          <span className={`font-bold ${asset.rsi_15m < 35 ? 'text-emerald-400' : asset.rsi_15m > 70 ? 'text-red-400' : 'text-yellow-400'}`}>
                            {asset.rsi_15m}
                          </span>
                        </td>

                        <td onClick={() => setExpandedRow(isExpanded ? null : asset.symbol)} className="px-4 py-4 text-xs">
                          {asset.entry_price > 0 ? (
                            <div className="flex flex-col gap-1">
                               <span className="text-gray-300">Entry: <span className="font-semibold text-white">${asset.entry_price}</span></span>
                               <span className="text-emerald-400">TP: <span className="font-semibold">${asset.tp_price}</span></span>
                               <span className="text-red-400">SL: <span className="font-semibold">${asset.sl_price}</span></span>
                            </div>
                          ) : (
                            <span className="text-gray-600">-</span>
                          )}
                        </td>

                        <td onClick={() => setExpandedRow(isExpanded ? null : asset.symbol)} className="px-4 py-4">
                          <span className={`px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider ${
                            asset.trade_signal.includes('OVERSOLD') ? 'bg-gradient-to-r from-emerald-600 to-emerald-400 text-white shadow-lg shadow-emerald-500/20' : 
                            asset.trade_signal.includes('OVERBOUGHT') ? 'bg-red-500/20 text-red-400 border border-red-500/30' : 
                            'bg-gray-800 text-gray-500'
                          }`}>
                            {asset.trade_signal}
                          </span>
                        </td>

                        <td className="px-4 py-4 text-center">
                            <button 
                                onClick={(e) => { e.stopPropagation(); handlePickTrade(asset); }}
                                className="bg-emerald-500/20 hover:bg-emerald-500/40 text-emerald-400 p-2 rounded-full border border-emerald-500/30 transition-all"
                                title="Ambil Trade Ini"
                            >
                                ✅
                            </button>
                        </td>
                      </tr>
                      {isExpanded && (
                          <tr className="bg-[#111827]">
                              <td colSpan={6} className="p-4 border-b border-gray-800">
                                  <TradingChart 
                                      symbol={asset.symbol} 
                                      entryPrice={asset.entry_price} 
                                      tpPrice={asset.tp_price} 
                                      slPrice={asset.sl_price} 
                                  />
                              </td>
                          </tr>
                      )}
                  </React.Fragment>
                )})}
              </tbody>
            </table>
          </div>
        </section>

        {/* INDONESIA STOCKS (IDX) SCREENER */}
        <section className="bg-gray-900/50 rounded-2xl border border-gray-800 overflow-hidden shadow-2xl backdrop-blur-sm mb-10">
          <div className="px-6 py-5 bg-gradient-to-r from-gray-900 to-gray-800 border-b border-gray-800 flex justify-between items-center">
            <div>
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <span className="text-red-500">🇮🇩</span> Indonesia Stocks (IDX)
              </h2>
              <p className="text-gray-500 text-[10px] mt-0.5">Top Blue Chips • 15m Delay</p>
            </div>
          </div>
          <div className="overflow-x-auto">
              <table className="w-full text-left text-sm text-gray-400">
                  <thead className="text-xs text-gray-400 uppercase bg-gray-900 border-b border-gray-800">
                      <tr>
                          <th className="px-4 py-4 font-medium">Stock</th>
                          <th className="px-4 py-4 font-medium">Price</th>
                          <th className="px-4 py-4 font-medium text-blue-300">Signal</th>
                          <th className="px-4 py-4 text-center">Trade</th>
                      </tr>
                  </thead>
                  <tbody>
                      {idxData.map((stock) => (
                          <tr key={stock.symbol} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                              <td className="px-4 py-4">
                                  <div className="font-bold text-white">{stock.symbol}</div>
                                  <div className="text-[9px] text-gray-500 truncate max-w-[100px]">{stock.name}</div>
                              </td>
                              <td className="px-4 py-4">
                                  <div className="font-mono font-bold text-white text-base">
                                      Rp {parseFloat(stock.lastPrice).toLocaleString()}
                                  </div>
                                  <span className={`text-[10px] ${parseFloat(stock.change) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                      {parseFloat(stock.change) >= 0 ? '▲' : '▼'} {Math.abs(parseFloat(stock.change)).toFixed(2)}%
                                  </span>
                              </td>
                              <td className="px-4 py-4">
                                  <span className={`px-2 py-1 rounded text-[9px] font-bold uppercase tracking-wider block text-center ${
                                      stock.trade_signal.includes('BUY') ? 'bg-emerald-600 text-white' : 
                                      stock.trade_signal.includes('OVERBOUGHT') ? 'bg-red-600 text-white' : 
                                      'bg-gray-800 text-gray-500'
                                  }`}>
                                      {stock.trade_signal}
                                  </span>
                              </td>
                              <td className="px-4 py-4 text-center">
                                  <button 
                                      onClick={() => handlePickTrade(stock)}
                                      className="bg-emerald-500/20 hover:bg-emerald-500/40 text-emerald-400 p-2 rounded-full border border-emerald-500/30 transition-all text-xs"
                                  >
                                      ✅
                                  </button>
                              </td>
                          </tr>
                      ))}
                  </tbody>
              </table>
          </div>
        </section>

        {/* TRADING JOURNAL HISTORY */}
        <section className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden shadow-2xl">
          <div className="bg-gray-800/50 p-4 border-b border-gray-700 flex justify-between items-center">
            <h2 className="text-xl font-bold text-blue-400">📊 My Trading Journal (Manual Picks)</h2>
            <span className="text-xs text-gray-500 italic">Auto-tracking TP/SL targets every 60s</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm whitespace-nowrap">
              <thead className="text-xs text-gray-500 uppercase bg-gray-900/50">
                <tr>
                  <th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3">Symbol</th>
                  <th className="px-4 py-3">Entry</th>
                  <th className="px-4 py-3">TP</th>
                  <th className="px-4 py-3">SL</th>
                  <th className="px-4 py-3 text-center">Result</th>
                </tr>
              </thead>
              <tbody>
                {tradeHistory.length === 0 ? (
                  <tr><td colSpan={6} className="text-center py-10 text-gray-600">Belum ada trade yang dipilih. Klik tombol ✅ di tabel atas untuk mulai tracking.</td></tr>
                ) : tradeHistory.map((trade: any, idx: number) => (
                  <tr key={idx} className="border-b border-gray-800 hover:bg-gray-800/30 transition-colors">
                    <td className="px-4 py-3 text-gray-500 text-[10px]">
                      {new Date(trade.timestamp).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 font-bold text-white">{trade.symbol}</td>
                    <td className="px-4 py-3 font-mono text-gray-300">${trade.entry_price}</td>
                    <td className="px-4 py-3 font-mono text-emerald-400">${trade.tp_price}</td>
                    <td className="px-4 py-3 font-mono text-red-400">${trade.sl_price}</td>
                    <td className="px-4 py-3 text-center">
                      <span className={`px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-tighter ${
                        trade.status === 'WIN' ? 'bg-emerald-500 text-white shadow-lg shadow-emerald-500/20' :
                        trade.status === 'LOSS' ? 'bg-red-500 text-white' :
                        trade.status === 'RUNNING' ? 'bg-amber-500 text-white shadow-lg shadow-amber-500/20 animate-pulse' :
                        'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                      }`}>
                        {trade.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

      </div>
    </main>
  );
}