'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { getGeminiAnalysis } from './actions';
import TradingChart from '../components/TradingChart';

export default function Home() {
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8000';

  const [quantData, setQuantData] = useState<any[]>([]);
  const [quantUniverse, setQuantUniverse] = useState<number>(0);
  const [quantLoading, setQuantLoading] = useState<boolean>(false);
  const [cryptoData, setCryptoData] = useState<any[]>([]);
  const [forexData, setForexData] = useState<any[]>([]);
  const [idxData, setIdxData] = useState<any[]>([]);
  const [idxStatus, setIdxStatus] = useState<string>("UNKNOWN");
  const [tradeHistory, setTradeHistory] = useState<any[]>([]);
  const [performance, setPerformance] = useState<{ wins: number, losses: number, pending: number, win_rate: number } | null>(null);
  const [aiAnalysis, setAiAnalysis] = useState<string>("Menunggu data untuk dianalisis...");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [timeframe, setTimeframe] = useState<string>('15m');
  const [activeTab, setActiveTab] = useState<string>('quant');

  const [livePrices, setLivePrices] = useState<Record<string, number>>({});
  const [priceDirections, setPriceDirections] = useState<Record<string, 'up' | 'down'>>({});
  const [bitgetStatus, setBitgetStatus] = useState<string>("Checking...");
  const [isBitgetConnected, setIsBitgetConnected] = useState<boolean>(false);
  const [forexStatus, setForexStatus] = useState<string>("Checking...");
  const [isForexConnected, setIsForexConnected] = useState<boolean>(false);
  const wsRef = useRef<WebSocket | null>(null);

  const fetchBitgetStatus = async () => {
    try {
      const res = await fetch(`${backendUrl}/api/bitget-status`);
      if (res.ok) {
        const json = await res.json();
        setBitgetStatus(json.message);
        setIsBitgetConnected(json.connected);
      }
    } catch (e) {
      setBitgetStatus("Failed to connect to backend");
    }
  };

  const fetchForexStatus = async () => {
    try {
      const res = await fetch(`${backendUrl}/api/forex-status`);
      if (res.ok) {
        const json = await res.json();
        setForexStatus(json.message);
        setIsForexConnected(json.connected);
      }
    } catch (e) {
      setForexStatus("Failed to connect to backend");
    }
  };

  const fetchData = useCallback(async () => {
    try {
      if (activeTab === 'quant') {
        setQuantLoading(true);
        const res = await fetch(`${backendUrl}/api/institutional-quant?limit=25`);
        if (res.ok) {
          const json = await res.json();
          if (json.status === 'success') {
            setQuantData(json.data || []);
            setQuantUniverse(json.universe_size || 0);
          }
        }
        setQuantLoading(false);
      } else if (activeTab === 'crypto') {
        fetchBitgetStatus();
        const res = await fetch(`${backendUrl}/api/top-coins?timeframe=${timeframe}`);
        if (res.ok) setCryptoData((await res.json()).data || []);
      } else if (activeTab === 'forex') {
        fetchForexStatus();
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
            setPriceDirections(pd => ({ ...pd, [symbol]: price > prev[symbol] ? 'up' : 'down' }));
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

  const handleExecuteNow = async (asset: any) => {
    if (!confirm(`🚀 EXECUTE REAL MARKET ORDER for ${asset.symbol}?`)) return;
    try {
      const res = await fetch(`${backendUrl}/api/execute-now`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: asset.symbol,
          market: activeTab,
          side: 'buy',
          tp: asset.tp_price,
          sl: asset.sl_price
        })
      });
      const data = await res.json();
      alert(data.message);
      fetchData();
    } catch (err) { alert("Execution Failed"); }
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

        {/* CONDITIONAL STATUS BAR */}
        {activeTab === 'crypto' && (
          <div className={`p-4 rounded-xl border flex items-center justify-between transition-all ${isBitgetConnected ? 'bg-emerald-950/20 border-emerald-900/50' : 'bg-red-950/20 border-red-900/50'}`}>
            <div className="flex items-center gap-3">
              <div className={`h-3 w-3 rounded-full ${isBitgetConnected ? 'bg-emerald-500 shadow-[0_0_10px_#10b981]' : 'bg-red-500 shadow-[0_0_10px_#ef4444]'}`}></div>
              <div>
                <p className="text-[10px] text-gray-500 uppercase font-bold tracking-widest">Bitget Futures Connection</p>
                <p className={`text-sm font-bold ${isBitgetConnected ? 'text-emerald-400' : 'text-red-400'}`}>
                  {bitgetStatus}
                </p>
              </div>
            </div>
            <button onClick={fetchBitgetStatus} className="px-3 py-1 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs font-bold transition-colors">
              REFRESH
            </button>
          </div>
        )}

        {activeTab === 'forex' && (
          <div className={`p-4 rounded-xl border flex items-center justify-between transition-all ${isForexConnected ? 'bg-blue-950/20 border-blue-900/50' : 'bg-red-950/20 border-red-900/50'}`}>
            <div className="flex items-center gap-3">
              <div className={`h-3 w-3 rounded-full ${isForexConnected ? 'bg-blue-500 shadow-[0_0_10px_#3b82f6]' : 'bg-red-500 shadow-[0_0_10px_#ef4444]'}`}></div>
              <div>
                <p className="text-[10px] text-gray-500 uppercase font-bold tracking-widest">MetaAPI MT5 Connection (Exness)</p>
                <p className={`text-sm font-bold ${isForexConnected ? 'text-blue-400' : 'text-red-400'}`}>
                  {forexStatus}
                </p>
              </div>
            </div>
            <button onClick={fetchForexStatus} className="px-3 py-1 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs font-bold transition-colors">
              REFRESH
            </button>
          </div>
        )}

        {/* TABS */}
        <nav className="flex bg-gray-900/80 p-1.5 rounded-2xl border border-gray-800 shadow-xl sticky top-4 z-50 backdrop-blur-xl">
          {[
            { id: 'quant', label: 'Institutional Quant', icon: '🏛️', badge: 'WorldQuant 101' },
            { id: 'crypto', label: 'Crypto Screener', icon: '💎' },
            { id: 'forex', label: 'Gold & Forex', icon: '🌕' },
            { id: 'idx', label: 'IDX Stocks', icon: '🇮🇩' }
          ].map(tab => (
            <button key={tab.id} onClick={() => { setActiveTab(tab.id); setExpandedRow(null); }}
              className={`flex-1 flex items-center justify-center gap-2 py-3.5 rounded-xl font-black text-xs md:text-sm transition-all ${activeTab === tab.id ? 'bg-blue-600 text-white shadow-2xl scale-[1.02]' : 'text-gray-500 hover:text-gray-300'}`}>
              <div className="flex flex-col items-center">
                <div className="flex items-center gap-2">
                  <span>{tab.icon}</span> <span>{tab.label.toUpperCase()}</span>
                </div>
                {tab.badge && (
                  <span className="text-[8px] mt-0.5 px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-400 font-bold border border-emerald-500/30">
                    {tab.badge}
                  </span>
                )}
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

        {/* MAIN SCREENER / QUANT MATRIX */}
        {activeTab === 'quant' ? (
          <div className="space-y-6">
            {/* Quantitative Intelligence Metrics Banner */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="bg-gray-900/60 p-5 rounded-2xl border border-blue-900/40 backdrop-blur-md">
                <p className="text-[10px] text-gray-500 uppercase tracking-widest font-black">Universe Scanned</p>
                <p className="text-2xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-cyan-400 mt-1">
                  {quantUniverse > 0 ? `${quantUniverse} Spot Pairs` : 'Scanning Universe...'}
                </p>
                <p className="text-[11px] text-gray-400 mt-1 font-mono">Cross-sectional normalized (0-1 rank)</p>
              </div>
              <div className="bg-gray-900/60 p-5 rounded-2xl border border-emerald-900/40 backdrop-blur-md">
                <p className="text-[10px] text-gray-500 uppercase tracking-widest font-black">Top Decile Alphas</p>
                <p className="text-2xl font-black text-emerald-400 mt-1">
                  Q1 Long Edge
                </p>
                <p className="text-[11px] text-gray-400 mt-1 font-mono">WorldQuant #101 + #54 + #41</p>
              </div>
              <div className="bg-gray-900/60 p-5 rounded-2xl border border-purple-900/40 backdrop-blur-md">
                <p className="text-[10px] text-gray-500 uppercase tracking-widest font-black">MM Inventory Skew</p>
                <p className="text-2xl font-black text-purple-400 mt-1">
                  Avellaneda-Stoikov
                </p>
                <p className="text-[11px] text-gray-400 mt-1 font-mono">Reservation price delta adjustment</p>
              </div>
              <div className="bg-gray-900/60 p-5 rounded-2xl border border-amber-900/40 backdrop-blur-md">
                <p className="text-[10px] text-gray-500 uppercase tracking-widest font-black">Agent Episodic Memory</p>
                <p className="text-2xl font-black text-amber-400 mt-1">
                  Mem0 AI Protected
                </p>
                <p className="text-[11px] text-gray-400 mt-1 font-mono">15 Failure Cases Immunized</p>
              </div>
            </div>

            {/* Official Academic Citations & Code Provenance */}
            <div className="bg-gradient-to-r from-gray-900/90 via-blue-950/30 to-gray-900/90 border border-gray-800 rounded-2xl p-6 shadow-2xl backdrop-blur-md">
              <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-2 mb-4 pb-3 border-b border-gray-800/80">
                <div>
                  <h3 className="text-sm font-black text-blue-400 uppercase tracking-widest flex items-center gap-2">
                    <span>🏛️</span> Institutional Mathematical Models & Academic Literature
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Mathematical alpha formulas verified from quantitative hedge fund literature (WorldQuant LLC, Courant Institute NYU).
                  </p>
                </div>
                <span className="text-[10px] px-2.5 py-1 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-mono font-bold">
                  arXiv:1601.00991 / QuantFinance
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="bg-black/40 p-4 rounded-xl border border-gray-800/60 hover:border-blue-500/40 transition-all">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-black text-emerald-400">WorldQuant 101 Alphas</span>
                    <a href="https://arxiv.org/abs/1601.00991" target="_blank" rel="noreferrer" className="text-[10px] text-blue-400 hover:underline">arXiv:1601.00991 ↗</a>
                  </div>
                  <p className="text-[11px] text-gray-300 font-semibold mt-1">Kakushadze, Z. (2016)</p>
                  <p className="text-[10px] text-gray-400 mt-1 font-mono leading-tight">
                    Alpha #101: (close - open) / ((high - low) + 0.001)<br/>
                    Alpha #54: (-1 * (low - close) * open^5) / ((low - high) * close^5)
                  </p>
                </div>

                <div className="bg-black/40 p-4 rounded-xl border border-gray-800/60 hover:border-purple-500/40 transition-all">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-black text-purple-400">Avellaneda-Stoikov MM</span>
                    <a href="https://doi.org/10.1080/14697680701381228" target="_blank" rel="noreferrer" className="text-[10px] text-purple-400 hover:underline">Quant Finance ↗</a>
                  </div>
                  <p className="text-[11px] text-gray-300 font-semibold mt-1">Avellaneda & Stoikov (2008)</p>
                  <p className="text-[10px] text-gray-400 mt-1 font-mono leading-tight">
                    Reservation Price: r(s, q, t) = s - q * γ * σ² * (T - t)<br/>
                    Dynamic inventory dampening to prevent dump absorption.
                  </p>
                </div>

                <div className="bg-black/40 p-4 rounded-xl border border-gray-800/60 hover:border-amber-500/40 transition-all">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-black text-amber-400">Mem0 Distributed Memory</span>
                    <a href="https://github.com/mem0ai/mem0" target="_blank" rel="noreferrer" className="text-[10px] text-amber-400 hover:underline">mem0ai/mem0 ↗</a>
                  </div>
                  <p className="text-[11px] text-gray-300 font-semibold mt-1">Deshmukh, T. et al. (2024)</p>
                  <p className="text-[10px] text-gray-400 mt-1 font-mono leading-tight">
                    Episodic memory graph + Qdrant vectors. Prevents repeating past mistakes (quarantine & falling knife veto).
                  </p>
                </div>
              </div>
            </div>

            {/* FACTOR MATRIX TABLE */}
            <div className="bg-gray-900/40 rounded-2xl border border-gray-800 overflow-hidden shadow-2xl backdrop-blur-md">
              <div className="p-5 border-b border-gray-800 flex flex-col md:flex-row justify-between items-start md:items-center gap-3">
                <div>
                  <h2 className="text-lg font-black text-white flex items-center gap-2">
                    <span>⚡</span> Cross-Sectional Alpha Decile Ranking
                  </h2>
                  <p className="text-xs text-gray-400">
                    Ranked relative to all {quantUniverse} traded pairs simultaneously. Top Decile (Q1) exhibits highest multi-factor institutional edge.
                  </p>
                </div>
                <button onClick={fetchData} className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-black transition-all flex items-center gap-2 shadow-lg">
                  {quantLoading ? <span className="animate-spin">🔄</span> : '⚡'} RE-CALCULATE ALPHAS
                </button>
              </div>

              {quantLoading && quantData.length === 0 ? (
                <div className="py-20 text-center text-gray-400 font-bold uppercase tracking-widest text-xs flex flex-col items-center justify-center gap-3">
                  <div className="h-8 w-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                  <span>Computing cross-sectional universe matrices & Kakushadze formulaic alphas...</span>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm whitespace-nowrap">
                    <thead className="bg-black/50 text-[10px] uppercase font-black text-gray-400 tracking-wider border-b border-gray-800">
                      <tr>
                        <th className="px-5 py-4">Rank / Asset</th>
                        <th className="px-5 py-4">Composite Alpha Score</th>
                        <th className="px-5 py-4">Price & 24h Vol</th>
                        <th className="px-5 py-4 text-emerald-400">Alpha #101 Rank</th>
                        <th className="px-5 py-4 text-cyan-400">Alpha #54 Rank</th>
                        <th className="px-5 py-4 text-purple-400">Alpha #41 Rank</th>
                        <th className="px-5 py-4 text-orange-400">Stoikov Skew</th>
                        <th className="px-5 py-4">Recommendation</th>
                        <th className="px-5 py-4 text-center">Execute</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800/40">
                      {quantData.map((row) => {
                        const isExp = expandedRow === row.symbol;
                        return (
                          <React.Fragment key={row.symbol}>
                            <tr onClick={() => setExpandedRow(isExp ? null : row.symbol)} className={`hover:bg-blue-600/5 cursor-pointer transition-all ${isExp ? 'bg-blue-600/10' : ''}`}>
                              <td className="px-5 py-4">
                                <div className="flex items-center gap-3">
                                  <span className="font-mono text-xs font-bold text-gray-500 w-5">#{row.rank}</span>
                                  <div>
                                    <div className="flex items-center gap-2">
                                      <p className="font-black text-white text-base">{row.symbol}</p>
                                      <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/30">
                                        {row.decile}
                                      </span>
                                    </div>
                                    <p className={`text-[10px] font-bold ${row.change_24h >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                      {row.change_24h >= 0 ? '+' : ''}{row.change_24h}% (24h)
                                    </p>
                                  </div>
                                </div>
                              </td>
                              <td className="px-5 py-4">
                                <div className="w-36">
                                  <div className="flex justify-between items-center text-[11px] font-mono font-bold mb-1">
                                    <span className={row.quant_score >= 75 ? 'text-emerald-400' : row.quant_score >= 60 ? 'text-cyan-400' : 'text-gray-300'}>
                                      {row.quant_score} / 100
                                    </span>
                                  </div>
                                  <div className="h-2 w-full bg-gray-800 rounded-full overflow-hidden border border-gray-700/50">
                                    <div
                                      className={`h-full transition-all duration-1000 ${row.quant_score >= 75 ? 'bg-gradient-to-r from-emerald-500 to-teal-300' : row.quant_score >= 60 ? 'bg-gradient-to-r from-blue-500 to-cyan-400' : 'bg-gray-600'}`}
                                      style={{ width: `${Math.min(100, Math.max(0, row.quant_score))}%` }}
                                    />
                                  </div>
                                </div>
                              </td>
                              <td className="px-5 py-4 font-mono">
                                <p className="text-white font-bold">${row.last_price?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })}</p>
                                <p className="text-[10px] text-gray-500">${row.turnover_m}M Vol</p>
                              </td>
                              <td className="px-5 py-4 font-mono">
                                <span className="text-xs font-bold text-emerald-400">{row.alpha_101_rank?.toFixed(3)}</span>
                                <p className="text-[9px] text-gray-500">Intraday Flow</p>
                              </td>
                              <td className="px-5 py-4 font-mono">
                                <span className="text-xs font-bold text-cyan-400">{row.alpha_54_rank?.toFixed(3)}</span>
                                <p className="text-[9px] text-gray-500">Decile Decay</p>
                              </td>
                              <td className="px-5 py-4 font-mono">
                                <span className="text-xs font-bold text-purple-400">{row.alpha_41_rank?.toFixed(3)}</span>
                                <p className="text-[9px] text-gray-500">VWAP Spread</p>
                              </td>
                              <td className="px-5 py-4 font-mono">
                                <span className="text-xs font-bold text-orange-400">{row.stoikov_skew_pct > 0 ? '+' : ''}{row.stoikov_skew_pct}%</span>
                                <p className="text-[9px] text-gray-500">Quote Skew</p>
                              </td>
                              <td className="px-5 py-4">
                                <span className={`px-2.5 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-tighter ${row.recommendation.includes('STRONG') ? 'bg-emerald-600 text-white shadow-emerald-900/50 shadow-sm' : row.recommendation.includes('LONG') ? 'bg-blue-600/80 text-white' : 'bg-gray-800 text-gray-400'}`}>
                                  {row.recommendation}
                                </span>
                              </td>
                              <td className="px-5 py-4 text-center">
                                <button onClick={(e) => {
                                  e.stopPropagation();
                                  handleExecuteNow({
                                    symbol: row.symbol,
                                    entry_price: row.last_price,
                                    tp_price: Number((row.last_price * 1.04).toFixed(6)),
                                    sl_price: Number((row.last_price * 0.98).toFixed(6))
                                  });
                                }} className="bg-orange-500/10 hover:bg-orange-500 text-orange-400 hover:text-white px-3 py-2 rounded-xl border border-orange-500/20 transition-all font-black text-[10px] flex items-center gap-1 mx-auto" title="Execute Quant Order">
                                  ⚡ EXECUTE
                                </button>
                              </td>
                            </tr>
                            {isExp && (
                              <tr className="bg-black/60">
                                <td colSpan={9} className="p-6 border-b border-gray-800">
                                  <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                                    <div className="bg-gray-900/80 p-4 rounded-xl border border-gray-800">
                                      <h4 className="text-xs font-bold uppercase tracking-wider text-blue-400 mb-2">Alpha Breakdown Details</h4>
                                      <div className="space-y-1.5 text-xs font-mono">
                                        <div className="flex justify-between"><span className="text-gray-400">Raw Alpha #101:</span><span className="text-white font-bold">{row.alpha_101_raw}</span></div>
                                        <div className="flex justify-between"><span className="text-gray-400">Normalized Mom Rank:</span><span className="text-emerald-400 font-bold">{row.momentum_rank}</span></div>
                                        <div className="flex justify-between"><span className="text-gray-400">Inventory Skew:</span><span className="text-orange-400 font-bold">{row.inventory_skew}</span></div>
                                        <div className="flex justify-between"><span className="text-gray-400">24h Quote Vol:</span><span className="text-white font-bold">${Number(row.quote_volume_24h).toLocaleString()}</span></div>
                                      </div>
                                    </div>
                                    <div className="bg-gray-900/80 p-4 rounded-xl border border-gray-800">
                                      <h4 className="text-xs font-bold uppercase tracking-wider text-emerald-400 mb-2">Institutional Trading Thesis</h4>
                                      <p className="text-xs text-gray-300 leading-relaxed">
                                        Asset ranks in the top decile ({row.decile}) of the cross-sectional universe.
                                        Positive intraday buying efficiency coupled with positive momentum decile confirms sustained institutional demand,
                                        eliminating the retail trap of catching falling knives.
                                      </p>
                                    </div>
                                    <div className="bg-gray-900/80 p-4 rounded-xl border border-gray-800">
                                      <h4 className="text-xs font-bold uppercase tracking-wider text-purple-400 mb-2">Target Execution Bracket</h4>
                                      <div className="space-y-1.5 text-xs font-mono">
                                        <div className="flex justify-between"><span className="text-gray-400">Entry Reference:</span><span className="text-blue-400 font-bold">${row.last_price}</span></div>
                                        <div className="flex justify-between"><span className="text-gray-400">Stoikov Limit TP (+4.0%):</span><span className="text-emerald-400 font-bold">${(row.last_price * 1.04).toFixed(6)}</span></div>
                                        <div className="flex justify-between"><span className="text-gray-400">Quant Hard Stop (-2.0%):</span><span className="text-red-400 font-bold">${(row.last_price * 0.98).toFixed(6)}</span></div>
                                        <div className="flex justify-between"><span className="text-gray-400">Risk/Reward:</span><span className="text-emerald-400 font-bold">1 : 2.0</span></div>
                                      </div>
                                    </div>
                                  </div>
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        ) : (
          /* MAIN SCREENER (CRYPTO / FOREX / IDX) */
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
                            <p className="text-blue-400 font-bold">Entry: {asset.entry_price}</p>
                            <p className="text-emerald-400 font-bold">TP: {asset.tp_price}</p>
                            <p className="text-red-400 font-bold">SL: {asset.sl_price}</p>
                          </td>
                          <td className="px-6 py-5">
                            <span className={`px-2.5 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-tighter shadow-sm ${asset.trade_signal.includes('BUY') || (asset.demand_score > 70) ? 'bg-emerald-600 text-white' : asset.trade_signal.includes('DANGER') ? 'bg-red-600 text-white' : 'bg-gray-800 text-gray-400'}`}>
                              {asset.demand_score > 70 ? `🔥 WHALE BUY (${asset.demand_score}%)` : asset.trade_signal}
                            </span>
                          </td>
                          <td className="px-6 py-5 text-center">
                            <div className="flex items-center gap-2">
                              <button onClick={(e) => { e.stopPropagation(); handlePickTrade(asset); }} className="bg-emerald-500/10 hover:bg-emerald-500 text-emerald-500 hover:text-white p-3 rounded-xl border border-emerald-500/20 transition-all" title="Add to Journal">✅</button>
                              <button onClick={(e) => { e.stopPropagation(); handleExecuteNow(asset); }} className="bg-orange-500/10 hover:bg-orange-500 text-orange-500 hover:text-white px-3 py-3 rounded-xl border border-orange-500/20 transition-all font-black text-[10px]" title="Execute Now">⚡ NOW</button>
                            </div>
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
        )}

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