import os
import matplotlib
# 1. 強制設定後台繪圖 (最優先)
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

# --- 1. 觀察清單 ---

# 🔥🔥🔥【每日更新區】從 Colab 複製出來的文字直接貼在下面引號內 🔥🔥🔥
TEMP_WATCHLIST_RAW = "IRWD, SKYT, SLS, PEPG, TROO, CTRN, BCAR, ARDX, RCAT, MLAC, SNDK, ONDS, VELO, APLD, TIGR, FLNC, SERV, ACMR, FTAI, ZURA"

# 系統會自動把上面的文字轉換成 Python 列表
TEMP_WATCHLIST = [x.strip() for x in TEMP_WATCHLIST_RAW.split(',') if x.strip()]

SECTORS = {
    "🔥 熱門交易": ["NVDA", "TSLA", "AAPL", "AMD", "PLTR", "SOFI", "MARA", "MSTR", "SMCI", "COIN"],
    "💎 科技巨頭": ["MSFT", "AMZN", "GOOGL", "META", "NFLX", "CRM", "ADBE"],
    "⚡ 半導體": ["TSM", "AVGO", "MU", "INTC", "ARM", "QCOM", "TXN", "AMAT"],
    "🚀 成長股": ["HOOD", "DKNG", "RBLX", "U", "CVNA", "OPEN", "SHOP", "NET"],
    "🏦 金融與消費": ["JPM", "V", "COST", "MCD", "NKE", "LLY", "WMT", "DIS", "SBUX"],
    "📉 指數 ETF": ["SPY", "QQQ", "IWM", "TQQQ", "SQQQ"]
}

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

# --- 5. 技術指標 (RSI, RVOL) ---
def calculate_indicators(df):
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    # RVOL (相對成交量)
    vol_ma = df['Volume'].rolling(10).mean()
    rvol = df['Volume'] / vol_ma
    
    # Golden Cross
    sma50 = df['Close'].rolling(50).mean()
    sma200 = df['Close'].rolling(200).mean()
    golden_cross = False
    if len(sma50) > 5:
        if sma50.iloc[-1] > sma200.iloc[-1] and sma50.iloc[-5] <= sma200.iloc[-5]:
            golden_cross = True
            
    # Trend
    trend_bullish = sma50.iloc[-1] > sma200.iloc[-1] if len(sma200) > 0 else False
    
    # Perf
    if len(df) > 30:
        perf_30d = (df['Close'].iloc[-1] - df['Close'].iloc[-30]) / df['Close'].iloc[-30] * 100
    else:
        perf_30d = 0
    
    return rsi, rvol, golden_cross, trend_bullish, perf_30d

# --- 6. 評分系統 ---
def calculate_quality_score(df, entry, sl, tp, is_bullish, market_bonus, found_sweep, indicators):
    try:
        score = 60 + market_bonus
        reasons = []
        rsi, rvol, golden_cross, trend, perf_30d = indicators
        
        # Strategies
        strategies = 0
        if found_sweep: strategies += 1
        if golden_cross: strategies += 1
        if 40 <= rsi.iloc[-1] <= 55: strategies += 1
        
        # RR
        risk = entry - sl
        reward = tp - entry
        rr = reward / risk if risk > 0 else 0
        if rr >= 3.0: 
            score += 15
            reasons.append(f"💰 盈虧比極佳 ({rr:.1f}R)")
        elif rr >= 2.0: 
            score += 10
            reasons.append(f"💰 盈虧比優秀 ({rr:.1f}R)")

        # RSI
        curr_rsi = rsi.iloc[-1]
        if 40 <= curr_rsi <= 55: 
            score += 10
            reasons.append(f"📉 RSI 完美回調 ({int(curr_rsi)})")
        elif curr_rsi > 70: score -= 15

        # RVOL
        curr_rvol = rvol.iloc[-1]
        if curr_rvol > 1.5:
            score += 10
            reasons.append(f"🔥 爆量確認 (Vol {curr_rvol:.1f}x)")
        elif curr_rvol > 1.1: score += 5

        # Sweep (重點加分)
        if found_sweep:
            score += 20
            reasons.append("💧 觸發流動性獵殺 (Sweep)")
            
        # Golden Cross
        if golden_cross:
            score += 10
            reasons.append("✨ 出現黃金交叉")

        # Distance
        close = df['Close'].iloc[-1]
        dist_pct = abs(close - entry) / entry
        if dist_pct < 0.01: 
            score += 15
            reasons.append("🎯 狙擊入場區")
            
        if trend: 
            score += 5
            reasons.append("📈 長期趨勢向上")

        if market_bonus > 0: reasons.append("🌍 大盤順風車 (+5)")
        if market_bonus < 0: reasons.append("🌪️ 逆大盤風險 (-10)")

        return min(max(int(score), 0), 99), reasons, rr, rvol.iloc[-1], perf_30d, strategies
    except: return 50, [], 0, 0, 0, 0

# --- 7. SMC 運算 (增強版 Sweep) ---
def calculate_smc(df):
    try:
        window = 50
        recent = df.tail(window)
        bsl = float(recent['High'].max())
        ssl_long = float(recent['Low'].min())
        ssl_short = float(recent['Low'].tail(5).min())
        
        eq = (bsl + ssl_long) / 2
        
        best_entry = eq
        found_fvg = False
        found_sweep = False
        
        last_3 = recent.tail(3)
        check_low = recent['Low'].iloc[:-3].tail(10).min() # 檢查過去10天的低點
        
        for i in range(len(last_3)):
            candle = last_3.iloc[i]
            if candle['Low'] < check_low and candle['Close'] > check_low:
                found_sweep = True
                best_entry = check_low # 獵殺點即入場點
                break
        
        # 2. 偵測 FVG
        for i in range(2, len(recent)):
            if recent['Low'].iloc[i] > recent['High'].iloc[i-2]:
                fvg = float(recent['Low'].iloc[i])
                if fvg < eq:
                    if not found_sweep: best_entry = fvg
                    found_fvg = True
                    break
                    
        return bsl, ssl_long, eq, best_entry, ssl_long*0.99, found_fvg, found_sweep
    except:
        last = float(df['Close'].iloc[-1])
        return last*1.05, last*0.95, last, last, last*0.94, False, False

# --- 8. 繪圖核心 ---
def create_error_image(msg):
    fig, ax = plt.subplots(figsize=(5, 3))
    fig.patch.set_facecolor('#0f172a')
    ax.set_facecolor('#0f172a')
    ax.text(0.5, 0.5, msg, color='white', ha='center', va
