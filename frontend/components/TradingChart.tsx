'use client';
import { useEffect, useRef } from 'react';
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts';

export default function TradingChart({ 
    symbol, 
    entryPrice, 
    tpPrice, 
    slPrice 
}: { 
    symbol: string, 
    entryPrice?: number, 
    tpPrice?: number, 
    slPrice?: number 
}) {
    const chartContainerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!chartContainerRef.current) return;

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: '#111827' },
                textColor: '#9CA3AF',
            },
            grid: {
                vertLines: { color: '#1F2937' },
                horzLines: { color: '#1F2937' },
            },
            width: chartContainerRef.current.clientWidth,
            height: 400,
        });

        const candlestickSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#10B981',
            downColor: '#EF4444',
            borderVisible: false,
            wickUpColor: '#10B981',
            wickDownColor: '#EF4444',
        });

        // Fetch data
        const fetchData = async () => {
            try {
                let data = [];
                if (symbol === 'XAUUSD' || symbol === 'GC=F') {
                    // Placeholder for forex chart data
                } else {
                    const url = `https://data-api.binance.vision/api/v3/klines?symbol=${symbol}&interval=15m&limit=100`;
                    const res = await fetch(url);
                    const json = await res.json();
                    data = json.map((d: any) => ({
                        time: d[0] / 1000,
                        open: parseFloat(d[1]),
                        high: parseFloat(d[2]),
                        low: parseFloat(d[3]),
                        close: parseFloat(d[4]),
                    }));
                    candlestickSeries.setData(data);
                }

                // Add Price Lines if they exist
                if (entryPrice > 0) {
                    candlestickSeries.createPriceLine({
                        price: entryPrice,
                        color: '#FCD34D',
                        lineWidth: 2,
                        lineStyle: 2, // Dashed
                        axisLabelVisible: true,
                        title: 'ENTRY',
                    });
                }
                if (tpPrice > 0) {
                    candlestickSeries.createPriceLine({
                        price: tpPrice,
                        color: '#10B981',
                        lineWidth: 2,
                        lineStyle: 1, 
                        axisLabelVisible: true,
                        title: 'TP',
                    });
                }
                if (slPrice > 0) {
                    candlestickSeries.createPriceLine({
                        price: slPrice,
                        color: '#EF4444',
                        lineWidth: 2,
                        lineStyle: 1,
                        axisLabelVisible: true,
                        title: 'SL',
                    });
                }
                
                chart.timeScale().fitContent();
            } catch (e) {
                console.error("Error fetching chart data", e);
            }
        };

        fetchData();

        const handleResize = () => {
            if (chartContainerRef.current) {
                chart.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };

        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, [symbol, entryPrice, tpPrice, slPrice]);

    return (
        <div className="w-full rounded-xl overflow-hidden border border-gray-800 bg-[#111827] p-2">
            <div ref={chartContainerRef} className="w-full h-[400px]" />
        </div>
    );
}
