'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { getGeminiAnalysis } from './actions';
import TradingChart from '../components/TradingChart';

export default function Home() {
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8000';
  
  const [cryptoData, setCryptoData] = useState<any[]>([]);
  const [forexData, setForexData] = useState<any[]>([]);
  const [idxData, setIdxData] = useState<any[]>([]);
  const [idxStatus, setIdxStatus] = useState<string>("UNKNOWN");
  const [tradeHistory, setTradeHistory] = useState<any[]>([]);
  const [performance, setPerformance] = useState<{wins: number, losses: number, pending: number, win_rate: number} | null>(null);
  const [aiAnalysis, setAiAnalysis] = useState<string>("Menunggu data untuk dianalisis...");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [timeframe, setTimeframe] = useState<string>('15m');
  const [activeTab, setActiveTab] = useState<string>('crypto');

  const [livePrices, setLivePrices] = useState<Record<string, number>>({});
  const [priceDirections, setPriceDirections] = useState<Record<string, 'up' | 'down'>>({});
  const wsRef = useRef<WebSocket | null>(null);

  const fetchData = useCallback(async () => {
    try {
      if (activeTab === 'crypto') {
        const res = await fetch(`${backendUrl}/api/top-coins?timeframe=${timeframe}`);
        if (res.ok) setCryptoData((await res.json()).data || []);
      } else if (activeTab === 'forex') {
        const res = await fetch(`${backendUrl}/api/forex?timeframe=${timeframe}`);
        if (res.ok) setForexData((await res.json()).data || []);
      } else if (activeTab === 'idx') {
        const res = await fetch(`${backendUrl}/api/idx-stocks?timeframe=${timeframe}`);
        if (res.ok) {
          const json = await res.json();
          setIdxData(json.data || []);
          setIdxStatus(json.market_status || "UNKNOWN");
        }
      }
      
      const [resPerf, resHistory] = await Promise.all([
        fetch(`${backendUrl}/api/performance`),
        fetch(`${backendUrl}/api/trade-history`)
      ]);

      if (resPerf.ok) setPerformance((await resPerf.json()).data);
      if (resHistory.ok) setTradeHistory((await resHistory.json()).data || []);
      
      setLastUpdated(new Date());
    } catch (error) {
      console.error("Network Error:", error);
    }
  }, [backendUrl, timeframe, activeTab]);

  useEffect(() => {
    fetchData(); 
    const interval = setInterval(fetchData, 15000); 
    return () => clearInterval(interval);
  }, [fetchData]);

  useEffect(() => {
    if (activeTab === 'idx') return; // IDX doesn't use Binance WS
    const symbols = activeTab === 'crypto' 
      ? cryptoData.map(c => `${c.symbol.toLowerCase()}@ticker`) 
      : forexData.filter(f => f.symbol !== 'XAUUSD').map(f => `${f.symbol.toLowerCase()}@ticker`);
    
    if (symbols.length === 0) return;
    const wsUrl = `wss://stream.binance.vision:9443/stream?streams=${symbols.join('/')}`;
    
    if (wsRef.current) wsRef.current.close();
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.data?.s && msg.data?.c) {
            const symbol = msg.data.s; 
            const price = parseFloat(msg.data.c);
            setLivePrices(prev => {
                if (prev[symbol] && prev[symbol] !== price) {
                    setPriceDirections(pd => ({...pd, [symbol]: price > prev[symbol] ? 'up' : 'down'}));
                }
                return { ...prev, [symbol]: price };
            });
        }
    };
    return () => ws.close();
  }, [cryptoData, forexData, activeTab]);

  const handlePickTrade = async (asset: any) => {
    try {
      const res = await fetch(`${backendUrl}/api/select-trade`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: asset.symbol,
          entry: asset.entry_price,
          tp: asset.tp_price,
          sl: asset.sl_price,
          market: activeTab
        })
      });
      if (res.ok) alert((await res.json()).message); fetchData();
    } catch (err) { console.error(err); }
  };

  const currentData = activeTab === 'crypto' ? cryptoData : activeTab === 'forex' ? forexData : idxData;
  const filteredHistory = tradeHistory.filter(t => t.market === activeTab);

  return (
    <main className="min-h-screen bg-[#0d1117] text-white p-4 md:p-8 font-sans">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* HEADER */}
        <header className="flex flex-col md:flex-row justify-between items-center gap-4 bg-gray-900/50 p-6 rounded-2xl border border-gray-800 shadow-2xl backdrop-blur-md">
          <div className="text-center md:text-left">
            <h1 className="text-3xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-emerald-400 tracking-tight">
              CHETILIZATION AI PRO
            </h1>
            <div className="flex items-center justify-center md:justify-start gap-2 mt-1 text-xs text-gray-500 uppercase tracking-widest font-bold">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
              LIVE DATA • POSTGRES REAL-TIME • GEMINI AI
            </div>
          </div>

          <div className="flex flex-wrap justify-center gap-3">
            {['15m', '1h', '4h', '1d'].map((tf) => (
              <button key={tf} onClick={() => setTimeframe(tf)}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${timeframe === tf ? 'bg-blue-600 text-white shadow-lg' : 'bg-gray-800 text-gray-400 hover:text-white'}`}>
                {tf.toUpperCase()}
              </button>
            ))}
          </div>

          {performance && (
            <div className="flex gap-4 bg-black/40 px-5 py-3 rounded-xl border border-gray-800 text-center">
              <div><p className="text-[10px] text-gray-500 uppercase">Win Rate</p><p className="text-emerald-400 font-black text-lg">{performance.win_rate}%</p></div>
              <div className="w-px bg-gray-800"></div>
              <div><p className="text-[10px] text-gray-500 uppercase">W / L</p><p className="text-white font-black text-lg">{performance.wins}/{performance.losses}</p></div>
            </div>
          )}
        </header>

        {/* TABS */}
        <nav className="flex bg-gray-900/80 p-1.5 rounded-2xl border border-gray-800 shadow-xl sticky top-4 z-50 backdrop-blur-xl">
          {[
            { id: 'crypto', label: 'Crypto', icon: '💎' },
            { id: 'forex', label: 'Gold & Forex', icon: '🌕' },
            { id: 'idx', label: 'IDX Stocks', icon: '🇮🇩' }
          ].map(tab => (
            <button key={tab.id} onClick={() => {setActiveTab(tab.id); setExpandedRow(null);}}
              className={`flex-1 flex items-center justify-center gap-2 py-3.5 rounded-xl font-black text-xs md:text-sm transition-all ${activeTab === tab.id ? 'bg-blue-600 text-white shadow-2xl scale-[1.02]' : 'text-gray-500 hover:text-gray-300'}`}>
              <div className="flex flex-col items-center">
                <div className="flex items-center gap-2">
                  <span>{tab.icon}</span> <span>{tab.label.toUpperCase()}</span>
                </div>
                {tab.id === 'idx' && (
                  <span className={`text-[8px] mt-0.5 px-1.5 py-0.5 rounded ${idxStatus.includes('OPEN') ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}>
                    {idxStatus}
                  </span>
                )}
              </div>
            </button>
          ))}
        </nav>

        {/* AI INSIGHT */}
        <section className="bg-gradient-to-br from-gray-900 to-blue-900/20 border border-blue-900/30 rounded-2xl p-6 shadow-2xl">
          <h3 className="flex items-center gap-2 text-blue-400 font-black text-sm uppercase tracking-widest mb-3">
            <span className="animate-bounce">🧠</span> AI Strategy Insight (Gemini 1.5)
          </h3>
          <p className="text-gray-300 text-sm leading-relaxed whitespace-pre-line italic">"{aiAnalysis}"</p>
        </section>

        {/* MAIN SCREENER */}
        <section className="bg-gray-900/40 rounded-2xl border border-gray-800 overflow-hidden shadow-2xl backdrop-blur-md">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm whitespace-nowrap">
              <thead className="bg-black/40 text-[10px] uppercase font-black text-gray-500 tracking-widest border-b border-gray-800">
                <tr>
                  <th className="px-6 py-5">Asset</th>
                  <th className="px-6 py-5">Live Price</th>
                  <th className="px-6 py-5 hidden md:table-cell text-emerald-400">Whale/Trend</th>
                  <th className="px-6 py-5 text-orange-400">Targets</th>
                  <th className="px-6 py-5">Signal</th>
                  <th className="px-6 py-5 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {currentData.map((asset) => {
                  const price = livePrices[asset.symbol] || parseFloat(asset.lastPrice);
                  const dir = priceDirections[asset.symbol];
                  const isExp = expandedRow === asset.symbol;
                  return (
                    <React.Fragment key={asset.symbol}>
                      <tr onClick={() => setExpandedRow(isExp ? null : asset.symbol)} className={`hover:bg-blue-600/5 cursor-pointer transition-all ${isExp ? 'bg-blue-600/10' : ''}`}>
                        <td className="px-6 py-5">
                          <p className="font-black text-white text-base">{asset.symbol}</p>
                          <p className={`text-[10px] font-bold ${asset.trend.includes('Bullish') ? 'text-emerald-500' : 'text-red-500'}`}>{asset.trend}</p>
                        </td>
                        <td className="px-6 py-5">
                          <p className={`font-mono text-lg font-black transition-all ${dir === 'up' ? 'text-emerald-400 scale-110' : dir === 'down' ? 'text-red-400 scale-110' : 'text-white'}`}>
                            {activeTab === 'idx' ? 'Rp' : '$'}{price.toLocaleString()}
                          </p>
                          <p className="text-[10px] text-emerald-400 font-bold">+{asset.change || asset.priceChangePercent}%</p>
                        </td>
                        <td className="px-6 py-5 hidden md:table-cell">
                          {activeTab === 'idx' ? (
                            <div className="flex flex-col gap-1.5">
                              <div className="flex justify-between items-center w-full">
                                <span className="text-[10px] font-black text-blue-400">WHALE DEMAND</span>
                                <span className="text-[10px] font-black text-white">{asset.demand_score}%</span>
                              </div>
                              <div className="h-1.5 w-32 bg-gray-800 rounded-full overflow-hidden border border-gray-700">
                                <div 
                                  className={`h-full transition-all duration-1000 bg-gradient-to-r from-blue-600 to-cyan-400`}
                                  style={{ width: `${asset.demand_score}%` }}
                                />
                              </div>
                              <div className="flex gap-2 mt-0.5">
                                <span className="text-[9px] px-1.5 py-0.5 bg-blue-500/10 text-blue-300 rounded font-bold border border-blue-500/10">Vol: {asset.relative_volume?.toFixed(1)}x</span>
                                <span className="text-[9px] px-1.5 py-0.5 bg-cyan-500/10 text-cyan-300 rounded font-bold border border-cyan-500/10">RSI: {asset.rsi?.toFixed(0)}</span>
                              </div>
                            </div>
                          ) : (
                            <>
                              <p className="text-emerald-300 font-bold">{asset.whale_ratio ? `${asset.whale_ratio}x Ratio` : 'Strong Trend'}</p>
                              <p className="text-[10px] text-gray-500">RSI: {asset.rsi_15m || asset.rsi?.toFixed(0)}</p>
                            </>
                          )}
                        </td>
                        <td className="px-6 py-5 font-mono text-[11px]">
                          <p className="text-emerald-400 font-bold">TP: {asset.tp_price}</p>
                          <p className="text-red-400 font-bold">SL: {asset.sl_price}</p>
                        </td>
                        <td className="px-6 py-5">
                          <span className={`px-2.5 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-tighter shadow-sm ${asset.trade_signal.includes('BUY') || (asset.demand_score > 70) ? 'bg-emerald-600 text-white' : asset.trade_signal.includes('DANGER') ? 'bg-red-600 text-white' : 'bg-gray-800 text-gray-400'}`}>
                            {asset.demand_score > 70 ? `🔥 WHALE BUY (${asset.demand_score}%)` : asset.trade_signal}
                          </span>
                        </td>
                        <td className="px-6 py-5 text-center">
                          <button onClick={(e) => {e.stopPropagation(); handlePickTrade(asset);}} className="bg-emerald-500/10 hover:bg-emerald-500 text-emerald-500 hover:text-white p-3 rounded-xl border border-emerald-500/20 transition-all">✅</button>
                        </td>
                      </tr>
                      {isExp && (
                        <tr className="bg-black/60">
                          <td colSpan={6} className="p-6 border-b border-gray-800">
                            <TradingChart 
                              symbol={asset.symbol} 
                              entryPrice={asset.entry_price || 0} 
                              tpPrice={asset.tp_price || 0} 
                              slPrice={asset.sl_price || 0} 
                            />
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>

        {/* MARKET JOURNAL */}
        <section className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden shadow-2xl">
          <div className="bg-gray-800/30 p-5 border-b border-gray-800 flex justify-between items-center">
            <h2 className="text-lg font-black text-blue-400 flex items-center gap-2"><span>📊</span> {activeTab.toUpperCase()} TRADING JOURNAL</h2>
            <p className="text-[10px] text-gray-500 font-bold italic uppercase tracking-widest">Real-time DB Sync</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm whitespace-nowrap">
              <thead className="text-[10px] text-gray-600 uppercase font-black tracking-widest bg-black/20">
                <tr><th className="px-6 py-4">Symbol</th><th className="px-6 py-4">Entry</th><th className="px-6 py-4">Target</th><th className="px-6 py-4 text-center">Status</th></tr>
              </thead>
              <tbody className="divide-y divide-gray-800/30">
                {filteredHistory.length === 0 ? (
                  <tr><td colSpan={4} className="text-center py-12 text-gray-700 font-bold uppercase tracking-widest text-xs">No active trades in {activeTab}</td></tr>
                ) : filteredHistory.map((trade: any, i: number) => (
                  <tr key={i} className="hover:bg-white/5 transition-colors">
                    <td className="px-6 py-4"><p className="font-black text-white">{trade.symbol}</p><p className="text-[9px] text-gray-600">{new Date(parseInt(trade.timestamp)).toLocaleTimeString()}</p></td>
                    <td className="px-6 py-4 font-mono text-gray-300">{trade.entry_price}</td>
                    <td className="px-6 py-4 font-mono"><p className="text-emerald-400 font-bold">TP: {trade.tp_price}</p><p className="text-red-400 font-bold">SL: {trade.sl_price}</p></td>
                    <td className="px-6 py-4 text-center">
                      <span className={`px-4 py-1.5 rounded-full text-[10px] font-black tracking-tighter ${trade.status === 'WIN' ? 'bg-emerald-500/20 text-emerald-400' : trade.status === 'LOSS' ? 'bg-red-500/20 text-red-400' : 'bg-blue-500/20 text-blue-400 animate-pulse'}`}>{trade.status}</span>
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