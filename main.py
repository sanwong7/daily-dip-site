import os
import matplotlib
# 1. 強制設定後台繪圖
matplotlib.use('Agg') 
import requests
import yfinance as yf
import mplfinance as mpf
import pandas as pd
import numpy as np
import base64
import json
import time
from io import BytesIO
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from datetime import datetime, timedelta

# --- 0. 設定 ---
API_KEY = os.environ.get("POLYGON_API_KEY")

# --- 1. 自動化選股核心 ---

def get_sp500_tickers():
    """從 Wikipedia 抓取 S&P 500 成分股"""
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        tables = pd.read_html(url)
        df = tables[0]
        tickers = df['Symbol'].tolist()
        tickers = [t.replace('.', '-') for t in tickers]
        print(f"📋 已抓取 S&P 500 名單，共 {len(tickers)} 隻。")
        return tickers
    except Exception as e:
        print(f"❌ 無法抓取 S&P 500 名單: {e}")
        return ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "NFLX", "INTC"]

def calculate_beta(stock_returns, market_returns):
    if len(stock_returns) != len(market_returns):
        min_len = min(len(stock_returns), len(market_returns))
        stock_returns = stock_returns[-min_len:]
        market_returns = market_returns[-min_len:]
    if len(market_returns) < 2: return 0 
    covariance = np.cov(stock_returns, market_returns)[0][1]
    variance = np.var(market_returns)
    if variance == 0: return 0
    return covariance / variance

SECTOR_MAP = {
    "Technology": "💻 科技與軟體",
    "Communication Services": "📡 通訊與媒體",
    "Consumer Cyclical": "🛍️ 非必需消費 (循環)",
    "Consumer Defensive": "🛒 必需消費 (防禦)",
    "Financial Services": "🏦 金融服務",
    "Healthcare": "💊 醫療保健",
    "Energy": "🛢️ 能源",
    "Industrials": "🏭 工業",
    "Basic Materials": "🧱 原物料",
    "Real Estate": "🏠 房地產",
    "Utilities": "💡 公用事業"
}

def get_stock_sector(ticker):
    try:
        info = yf.Ticker(ticker).info
        sector = info.get('sector', 'Unknown')
        industry = info.get('industry', 'Unknown')
        if "Semiconductor" in industry: return "⚡ 半導體"
        return SECTOR_MAP.get(sector, "🌐 其他產業")
    except: return "🌐 其他產業"

def auto_select_candidates():
    print("🚀 啟動超級篩選器 (Criteria: Cap>3B, Price>SMA200, Vol>500M, Beta>=1)...")
    raw_tickers = get_sp500_tickers()
    growth_adds = ["PLTR", "SOFI", "COIN", "MARA", "MSTR", "HOOD", "DKNG", "RBLX", "U", "CVNA", "OPEN", "SHOP", "ARM", "SMCI", "APP", "RDDT", "HIMS", "ASTS", "IONQ", "MU", "UBER", "ABNB"]
    full_list = list(set(raw_tickers + growth_adds))
    valid_tickers = [] 
    try:
        spy = yf.Ticker("SPY").history(period="1y")
        if spy.empty: return []
        spy_returns = spy['Close'].pct_change().dropna()
    except: return []
    
    print(f"🔍 開始掃描 {len(full_list)} 隻股票...")
    for ticker in full_list:
        try:
            try:
                info = yf.Ticker(ticker).fast_info
                if info.market_cap < 3_000_000_000: continue
            except: pass
            df = yf.Ticker(ticker).history(period="1y")
            if df is None or len(df) < 200: continue
            close = df['Close'].iloc[-1]
            sma200 = df['Close'].rolling(200).mean().iloc[-1]
            if close < sma200: continue 
            avg_vol = df['Volume'].tail(30).mean()
            avg_price = df['Close'].tail(30).mean()
            dollar_vol = avg_vol * avg_price
            if dollar_vol < 500_000_000: continue 
            stock_returns = df['Close'].pct_change().dropna()
            beta = calculate_beta(stock_returns, spy_returns)
            if beta < 1.0: continue
            sector_name = get_stock_sector(ticker)
            print(f"   ✅ {ticker} 入選! ({sector_name})")
            valid_tickers.append({'ticker': ticker, 'sector': sector_name})
        except: continue
    print(f"🏆 篩選完成! 共找到 {len(valid_tickers)} 隻。")
    return valid_tickers

# --- 2. 新聞 ---
def get_polygon_news():
    if not API_KEY: return "<div style='padding:20px'>API Key Missing</div>"
    news_html = ""
    try:
        url = f"https://api.polygon.io/v2/reference/news?limit=12&order=desc&sort=published_utc&apiKey={API_KEY}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get('results'):
            for item in data['results']:
                title = item.get('title')
                url = item.get('article_url')
                pub = item.get('publisher', {}).get('name', 'Unknown')
                dt = item.get('published_utc', '')[:10]
                news_html += f"<div class='news-item'><div class='news-meta'>{pub} • {dt}</div><a href='{url}' target='_blank' class='news-title'>{title}</a></div>"
        else: news_html = "<div style='padding:20px'>暫無新聞</div>"
    except: news_html = "News Error"
    return news_html

# --- 3. 市場大盤分析 ---
def get_market_condition():
    try:
        print("🔍 Checking Market...")
        spy = yf.Ticker("SPY").history(period="6mo")
        qqq = yf.Ticker("QQQ").history(period="6mo")
        if spy.empty or qqq.empty: return "NEUTRAL", "數據不足", 0
        spy_50 = spy['Close'].rolling(50).mean().iloc[-1]
        spy_curr = spy['Close'].iloc[-1]
        qqq_50 = qqq['Close'].rolling(50).mean().iloc[-1]
        qqq_curr = qqq['Close'].iloc[-1]
        is_bullish = (spy_curr > spy_50) and (qqq_curr > qqq_50)
        is_bearish = (spy_curr < spy_50) and (qqq_curr < qqq_50)
        if is_bullish: return "BULLISH", "🟢 市場順風 (大盤 > 50MA)", 5
        elif is_bearish: return "BEARISH", "🔴 市場逆風 (大盤 < 50MA)", -10
        else: return "NEUTRAL", "🟡 市場震盪", 0
    except: return "NEUTRAL", "Check Failed", 0

# --- 4. 數據獲取 ---
def fetch_data_safe(ticker, period, interval):
    try:
        dat = yf.Ticker(ticker).history(period=period, interval=interval)
        if dat is None or dat.empty: return None
        if not isinstance(dat.index, pd.DatetimeIndex): dat.index = pd.to_datetime(dat.index)
        dat = dat.rename(columns={"Open": "Open", "High": "High", "Low": "Low", "Close": "Close", "Volume": "Volume"})
        return dat
    except: return None

# --- 5. 技術指標 ---
def calculate_indicators(df):
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    vol_ma = df['Volume'].rolling(10).mean()
    rvol = df['Volume'] / vol_ma
    sma50 = df['Close'].rolling(50).mean()
    sma200 = df['Close'].rolling(200).mean()
    golden_cross = False
    if len(sma50) > 5:
        if sma50.iloc[-1] > sma200.iloc[-1] and sma50.iloc[-5] <= sma200.iloc[-5]:
            golden_cross = True
    trend_bullish = sma50.iloc[-1] > sma200.iloc[-1] if len(sma200) > 0 else False
    if len(df) > 30:
        perf_30d = (df['Close'].iloc[-1] - df['Close'].iloc[-30]) / df['Close'].iloc[-30] * 100
    else: perf_30d = 0
    return rsi, rvol, golden_cross, trend_bullish, perf_30d

# --- 6. 評分系統 ---
def calculate_quality_score(df, entry, sl, tp, is_bullish, market_bonus, sweep_type, indicators):
    try:
        score = 60 + market_bonus
        reasons = []
        rsi, rvol, golden_cross, trend, perf_30d = indicators
        strategies = 0
        if sweep_type == "MAJOR":
            strategies += 1; score += 25; reasons.append("🌊 強力獵殺 (Major Sweep >20d)")
        elif sweep_type == "MINOR":
            strategies += 1; score += 15; reasons.append("💧 短線獵殺 (Minor Sweep >10d)")
        if golden_cross: strategies += 1
        if 40 <= rsi.iloc[-1] <= 55: strategies += 1
        risk = entry - sl
        reward = tp - entry
        rr = reward / risk if risk > 0 else 0
        if rr >= 3.0: score += 15; reasons.append(f"💰 盈虧比極佳 ({rr:.1f}R)")
        elif rr >= 2.0: score += 10; reasons.append(f"💰 盈虧比優秀 ({rr:.1f}R)")
        curr_rsi = rsi.iloc[-1]
        if 40 <= curr_rsi <= 55: score += 10; reasons.append(f"📉 RSI 完美回調 ({int(curr_rsi)})")
        elif curr_rsi > 70: score -= 15
        curr_rvol = rvol.iloc[-1]
        if curr_rvol > 1.5: score += 10; reasons.append(f"🔥 爆量確認 (Vol {curr_rvol:.1f}x)")
        elif curr_rvol > 1.1: score += 5
        if sweep_type: score += 20; reasons.append("💧 觸發流動性獵殺 (Sweep)")
        if golden_cross: score += 10; reasons.append("✨ 出現黃金交叉")
        dist_pct = abs(df['Close'].iloc[-1] - entry) / entry
        if dist_pct < 0.01: score += 15; reasons.append("🎯 狙擊入場區")
        if trend: score += 5; reasons.append("📈 長期趨勢向上")
        if market_bonus > 0: reasons.append("🌍 大盤順風車 (+5)")
        if market_bonus < 0: reasons.append("🌪️ 逆大盤風險 (-10)")
        return min(max(int(score), 0), 99), reasons, rr, rvol.iloc[-1], perf_30d, strategies
    except: return 50, [], 0, 0, 0, 0

# --- 7. SMC 運算 ---
def calculate_smc(df):
    try:
        window = 50
        recent = df.tail(window)
        bsl = float(recent['High'].max())
        ssl_long = float(recent['Low'].min())
        eq = (bsl + ssl_long) / 2
