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

# --- 1. 自動化選股核心 (超級篩選器) ---

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
        # 備用名單
        return ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "NFLX", "INTC"]

def calculate_beta(stock_returns, market_returns):
    """手動計算 Beta"""
    if len(stock_returns) != len(market_returns):
        min_len = min(len(stock_returns), len(market_returns))
        stock_returns = stock_returns[-min_len:]
        market_returns = market_returns[-min_len:]
    
    if len(market_returns) < 2: return 0 
    
    covariance = np.cov(stock_returns, market_returns)[0][1]
    variance = np.var(market_returns)
    if variance == 0: return 0
    return covariance / variance

def auto_select_candidates():
    print("🚀 啟動超級篩選器 (Criteria: Cap>3B, Price>SMA200, Vol>900M, Beta>=1)...")
    
    raw_tickers = get_sp500_tickers()
    # 補上一些熱門成長股
    growth_adds = ["PLTR", "SOFI", "COIN", "MARA", "MSTR", "HOOD", "DKNG", "RBLX", "U", "CVNA", "OPEN", "SHOP", "ARM", "SMCI", "APP", "RDDT", "HIMS", "ASTS", "IONQ"]
    full_list = list(set(raw_tickers + growth_adds))
    
    valid_tickers = []
    
    # 抓取大盤數據用於計算 Beta
    try:
        spy = yf.Ticker("SPY").history(period="1y")
        if spy.empty: return []
        spy_returns = spy['Close'].pct_change().dropna()
    except:
        return []
    
    print(f"🔍 開始掃描 {len(full_list)} 隻股票...")
    
    for ticker in full_list:
        try:
            # 優化：先檢查市值 (速度快)
            try:
                info = yf.Ticker(ticker).fast_info
                if info.market_cap < 3_000_000_000: continue
            except: pass

            # 抓 K 線
            df = yf.Ticker(ticker).history(period="1y")
            if df is None or len(df) < 200: continue
            
            # A. 股價 > 200MA
            close = df['Close'].iloc[-1]
            sma200 = df['Close'].rolling(200).mean().iloc[-1]
            if close < sma200: continue 
            
            # B. 30日成交額 > 900M
            avg_vol = df['Volume'].tail(30).mean()
            avg_price = df['Close'].tail(30).mean()
            dollar_vol = avg_vol * avg_price
            if dollar_vol < 900_000_000: continue 
            
            # C. Beta >= 1
            stock_returns = df['Close'].pct_change().dropna()
            beta = calculate_beta(stock_returns, spy_returns)
            if beta < 1.0: continue
            
            print(f"   ✅ {ticker} 入選! (Beta: {beta:.2f}, Vol: ${dollar_vol/1e6:.0f}M)")
            valid_tickers.append(ticker)
            
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
    else:
        perf_30d = 0
    
    return rsi, rvol, golden_cross, trend_bullish, perf_30d

# --- 6. 評分系統 ---
def calculate_quality_score(df, entry, sl, tp, is_bullish, market_bonus, found_sweep, indicators):
    try:
        score = 60 + market_bonus
        reasons = []
        rsi, rvol, golden_cross, trend, perf_30d = indicators
        
        strategies = 0
        if found_sweep: strategies += 1
        if golden_cross: strategies += 1
        if 40 <= rsi.iloc[-1] <= 55: strategies += 1
        
        risk = entry - sl
        reward = tp - entry
        rr = reward / risk if risk > 0 else 0
        if rr >= 3.0: 
            score += 15
            reasons.append(f"💰 盈虧比極佳 ({rr:.1f}R)")
        elif rr >= 2.0: 
            score += 10
            reasons.append(f"💰 盈虧比優秀 ({rr:.1f}R)")

        curr_rsi = rsi.iloc[-1]
        if 40 <= curr_rsi <= 55: 
            score += 10
            reasons.append(f"📉 RSI 完美回調 ({int(curr_rsi)})")
        elif curr_rsi > 70: score -= 15

        curr_rvol = rvol.iloc[-1]
        if curr_rvol > 1.5:
            score += 10
            reasons.append(f"🔥 爆量確認 (Vol {curr_rvol:.1f}x)")
        elif curr_rvol > 1.1: score += 5

        if found_sweep:
            score += 20
            reasons.append("💧 觸發流動性獵殺 (Sweep)")
            
        if golden_cross:
            score += 10
            reasons.append("✨ 出現黃金交叉")

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

# --- 7. SMC 運算 ---
def calculate_smc(df):
    try:
        window = 50
        recent = df.tail(window)
        bsl = float(recent['High'].max())
        ssl_long = float(recent['Low'].min())
        
        eq = (bsl + ssl_long) / 2
        
        best_entry = eq
        found_fvg = False
        found_sweep = False
        
        last_3 = recent.tail(3)
        check_low = recent['Low'].iloc[:-3].tail(10).min()
        
        for i in range(len(last_3)):
            candle = last_3.iloc[i]
            if candle['Low'] < check_low and candle['Close'] > check_low:
                found_sweep = True
                best_entry = check_low
                break
        
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

# --- 8. 繪圖核心 (升級版：含成交量 + 均線) ---
def create_error_image(msg):
    fig, ax = plt.subplots(figsize=(5, 3))
    fig.patch.set_facecolor('#0f172a')
    ax.set_facecolor('#0f172a')
    ax.text(0.5, 0.5, msg, color='white', ha='center', va='center')
    ax.axis('off')
    buf = BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', facecolor='#0f172a')
    plt.close(fig)
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"

def generate_chart(df, ticker, title, entry, sl, tp, is_wait, found_sweep):
    try:
        plt.close('all')
        if df is None or len(df) < 5: return create_error_image("No Data")
        
        # 抓取數據並畫圖，這裡使用 tail(80) 讓均線有足夠數據顯示
        plot_df = df.tail(80).copy()
        
        entry = float(entry) if not np.isnan(entry) else plot_df['Close'].iloc[-1]
        sl = float(sl) if not np.isnan(sl) else plot_df['Low'].min()
        tp = float(tp) if not np.isnan(tp) else plot_df['High'].max()

        # 設定外觀風格
        mc = mpf.make_marketcolors(up='#10b981', down='#ef4444', edge='inherit', wick='inherit', volume={'up':'#1f2937', 'down':'#1f2937'})
        s  = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc, gridcolor='#1e293b', facecolor='#0f172a')
        
        # 繪圖 (啟用 volume=True, mav畫出均線)
        fig, axlist = mpf.plot(plot_df, type='candle', style=s, volume=True, 
            mav=(50, 200), 
            title=dict(title=f"{ticker} - {title}", color='white', size=12, weight='bold'),
            figsize=(6, 4), # 放大圖片
            panel_ratios=(7, 2), 
            scale_width_adjustment=dict(candle=1.2), 
            returnfig=True,
            tight_layout=True)
        
        ax = axlist[0]
        x_min, x_max = ax.get_xlim()
        
        # FVG
        for i in range(2, len(plot_df)):
            idx = i - 1
            if plot_df['Low'].iloc[i] > plot_df['High'].iloc[i-2]: 
                bot, top = plot_df['High'].iloc[i-2],
