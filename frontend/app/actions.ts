'use server'
import { GoogleGenerativeAI } from "@google/generative-ai";

export async function getGeminiAnalysis(top5Coins: string) {
    if (!process.env.GEMINI_API_KEY) {
        return "Gemini API Key tidak ditemukan di server.";
    }
    try {
        const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
        const model = genAI.getGenerativeModel({ model: "gemini-2.5-flash" });
        
        const prompt = `Lu adalah Chief Risk Officer (CRO) dan Institutional Pro Trader. Bot algoritma ML gw baru aja deteksi anomali volume pada koin-koin berikut beserta data teknikalnya (Trend EMA 200, RSI, Whale Ratio):
        
        [DATA KOIN]:
        ${top5Coins}
        
        TUGAS LU:
        1. JANGAN sekadar merekomendasikan koin hanya karena RSI rendah. Tolak mentah-mentah (Reject) koin yang berada di fase "Downtrend" (Harga di bawah EMA 200) atau dilabeli "High Risk / Danger". Menangkap pisau jatuh (catching a falling knife) adalah kebodohan.
        2. Pilih HANYA 1 atau 2 koin TERBAIK yang memiliki "Win Rate" tertinggi berdasarkan Konfirmasi Berlapis (Multi-Factor Confluence): Koin harus Uptrend (di atas EMA 200), RSI Oversold (diskon), dan punya dukungan Whale (Ratio > 1.2).
        3. Jelaskan keputusan lu secara singkat, tegas, pro, tapi tetap asik (gaya bahasa trader santai). Maksimal 1 paragraf padat. Kalau semua koin jelek/berbahaya, suruh gw "Wait and See" dan jangan maksa entry.
        `;
        
        const result = await model.generateContent(prompt);
        return result.response.text();
    } catch (error) {
        console.error("Gemini Error:", error);
        return "Gagal memuat analisis Gemini. Cek koneksi atau API Key.";
    }
}
