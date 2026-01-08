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
import xml.etree.ElementTree as ET

# --- 0. 設定 ---
API_KEY = os.environ.get("POLYGON_API_KEY")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")
HISTORY_FILE = "history.json"  # 🔥 用來儲存歷史紀錄的檔案

# --- 1. 自動化選股核心 ---

PRIORITY_TICKERS = ["TSLA", "AMZN", "NVDA", "AAPL", "MSFT", "GOOGL", "META", "AMD", "PLTR", "SOFI", "HOOD", "COIN", "MSTR", "MARA", "TSM", "ASML", "ARM"]

STATIC_UNIVERSE = [
    "QCOM", "INTC", "MU", "AMAT", "LRCX", "ADI", "TXN", "KLAC", "MRVL", "STM", "ON", "GFS", "SMCI", "DELL", "HPQ",
    "ORCL", "ADBE", "CRM", "SAP", "INTU", "IBM", "NOW", "UBER", "ABNB", "PANW", "SNPS", "CDNS", "CRWD", "SQ", "SHOP", "WDAY", "ROP", "SNOW", "DDOG", "ZS", "NET", "TEAM", "MDB", "PATH", "U", "APP", "RDDT", "IONQ",
    "JPM", "V", "MA", "BAC", "WFC", "MS", "GS", "BLK", "C", "AXP", "PYPL", "AFRM", "UPST",
    "WMT", "COST", "PG", "KO", "PEP", "MCD", "SBUX", "NKE", "DIS", "HD", "LOW", "TGT", "CMG", "LULU", "BKNG", "MAR", "HILTON", "CL",
    "LLY", "JNJ", "UNH", "ABBV", "MRK", "TMO", "DHR", "ISRG", "VRTX", "REGN", "PFE", "AMGN", "BMY", "CVS", "HIMS",
    "CAT", "DE", "GE", "HON", "UNP", "UPS", "XOM", "CVX", "COP", "SLB", "EOG", "OXY",
    "TM", "HMC", "STLA", "F", "GM", "RIVN", "LCID", "NIO", "XPEV", "LI",
    "BABA", "PDD", "JD", "BIDU", "TCEHY",
    "NFLX", "CMCSA", "TMUS", "VZ", "T", "ASTS"
]

# --- 🔥 歷史紀錄管理模組 ---
def load_history():
    """讀取歷史紀錄"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except: return {}
    return {}

def save_history(history):
    """儲存歷史紀錄"""
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=4)
    except Exception as e:
        print(f"❌ Failed to save history: {e}")

def generate_ticker_grid(picks, title, color_class="top-card"):
    """輔助函數：生成股票卡片 Grid HTML"""
    if not picks:
        return f"<h3 style='color:#fbbf24; margin-top:30px;'>{title}</h3><div style='color:#666; margin-bottom:20px; padding:10px; background:rgba(255,255,255,0.05); border-radius:8px;'>暫無歷史數據</div>"
    
    html = f"<h3 style='color:#fbbf24; margin-top:30px;'>{title}</h3><div class='top-grid'>"
    for p in picks:
        ticker = p.get('ticker')
        score = p.get('score', 0)
        sector = p.get('sector', '')
        
        style = "border-color:#fbbf24;" if color_class == "top-card" else "border:1px solid #475569; background:rgba(30,41,59,0.5); opacity: 0.9;"
        
        html += f"<div class='card {color_class}' onclick=\"openModal('{ticker}')\" style='{style}'>" \
                f"<div style='font-size:1.2rem;margin-bottom:5px'><b>{ticker}</b></div>" \
                f"<div style='color:{'#10b981' if score >= 80 else '#94a3b8'};font-weight:bold'>{score}</div>" \
                f"<div style='font-size:0.7rem;color:#888'>{sector}</div></div>"
    html += "</div>"
    return html

# --- 核心計算 ---

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
    print("🚀 啟動超級篩選器 (Priority First)...")
    full_list = PRIORITY_TICKERS + list(set(STATIC_UNIVERSE) - set(PRIORITY_TICKERS))
    valid_tickers = [] 
    try:
        spy = yf.Ticker("SPY").history(period="1y")
        if spy.empty: return []
        spy_returns = spy['Close'].pct_change().dropna()
    except: return []
    
    print(f"🔍 開始過濾...")
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
        url = f"https://api.polygon.io/v2/reference/news?limit=15&order=desc&sort=published_utc&apiKey={API_KEY}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get('results'):
            for item in data['results']:
                title = item.get('title')
                url = item.get('article_url')
                pub = item.get('publisher', {}).get('name', 'Unknown')
                dt = item.get('published_utc', '')[:10]
                news_html += f"<div class='news-card'><div class='news-meta'><span class='news-source'>{pub}</span><span class='news-date'>{dt}</span></div><a href='{url}' target='_blank' class='news-title'>{title}</a></div>"
        else: news_html = "<div style='padding:20px;text-align:center'>No News Found</div>"
    except Exception as e: news_html = f"<div style='padding:20px'>News Error: {e}</div>"
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

# --- 4. 數據獲取 & 財報檢查 ---
def fetch_data_safe(ticker, period, interval):
    try:
        dat = yf.Ticker(ticker).history(period=period, interval=interval)
        if dat is None or dat.empty: return None
        if not isinstance(dat.index, pd.DatetimeIndex): dat.index = pd.to_datetime(dat.index)
        dat = dat.rename(columns={"Open": "Open", "High": "High", "Low": "Low", "Close": "Close", "Volume": "Volume"})
        return dat
    except: return None

def check_earnings(ticker):
    try:
        stock = yf.Ticker(ticker)
        calendar = stock.calendar
        if calendar is not None and not calendar.empty:
            earnings_date = calendar.iloc[0, 0] 
            if isinstance(earnings_date, (datetime, pd.Timestamp)):
                days_diff = (earnings_date.date() - datetime.now().date()).days
                if 0 <= days_diff <= 7:
                    return f"⚠️ Earnings: {days_diff}d"
    except: pass
    return ""

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
        return max(int(score), 0), reasons, rr, rvol.iloc[-1], perf_30d, strategies
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
        sweep_type = None 
        last_3 = recent.tail(3)
        prior_data = recent.iloc[:-3]
        low_10d = prior_data['Low'].tail(10).min()
        low_20d = prior_data['Low'].tail(20).min()
        for i in range(len(last_3)):
            candle = last_3.iloc[i]
            if candle['Low'] < low_20d and candle['Close'] > low_20d:
                sweep_type = "MAJOR"; best_entry = low_20d; break 
            elif candle['Low'] < low_10d and candle['Close'] > low_10d:
                if sweep_type != "MAJOR": sweep_type = "MINOR"; best_entry = low_10d
        for i in range(2, len(recent)):
            if recent['Low'].iloc[i] > recent['High'].iloc[i-2]:
                fvg = float(recent['Low'].iloc[i])
                if fvg < eq:
                    if not sweep_type: best_entry = fvg
                    found_fvg = True
                    break
        return bsl, ssl_long, eq, best_entry, ssl_long*0.99, found_fvg, sweep_type
    except:
        last = float(df['Close'].iloc[-1])
        return last*1.05, last*0.95, last, last, last*0.94, False, None

# --- 8. 繪圖核心 ---
def create_error_image(msg):
    fig, ax = plt.subplots(figsize=(5, 3))
    fig.patch.set_facecolor('#1e293b')
    ax.set_facecolor('#1e293b')
    ax.text(0.5, 0.5, msg, color='white', ha='center', va='center')
    ax.axis('off')
    buf = BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', facecolor='#1e293b')
    plt.close(fig)
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"

def generate_chart(df, ticker, title, entry, sl, tp, is_wait, sweep_type):
    try:
        plt.close('all')
        if df is None or len(df) < 5: return create_error_image("No Data")
        plot_df = df.tail(80).copy()
        entry = float(entry) if not np.isnan(entry) else plot_df['Close'].iloc[-1]
        sl = float(sl) if not np.isnan(sl) else plot_df['Low'].min()
        tp = float(tp) if not np.isnan(tp) else plot_df['High'].max()
        mc = mpf.make_marketcolors(up='#22c55e', down='#ef4444', edge='inherit', wick='inherit', volume={'up':'#334155', 'down':'#334155'})
        s  = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc, gridcolor='#334155', facecolor='#1e293b')
        fig, axlist = mpf.plot(plot_df, type='candle', style=s, volume=True, mav=(50, 200), title=dict(title=f"{ticker} - {title}", color='white', size=16, weight='bold'), figsize=(8, 5), panel_ratios=(6, 2), scale_width_adjustment=dict(candle=1.2), returnfig=True, tight_layout=True)
        fig.patch.set_facecolor('#1e293b')
        ax = axlist[0]; x_min, x_max = ax.get_xlim()
        for i in range(2, len(plot_df)):
            idx = i - 1
            if plot_df['Low'].iloc[i] > plot_df['High'].iloc[i-2]: 
                bot, top = plot_df['High'].iloc[i-2], plot_df['Low'].iloc[i]
                if (top - bot) > (plot_df['Close'].mean() * 0.002):
                    rect = patches.Rectangle((idx-0.4, bot), 10, top - bot, linewidth=0, facecolor='#22c55e', alpha=0.2)
                    ax.add_patch(rect)
            elif plot_df['High'].iloc[i] < plot_df['Low'].iloc[i-2]:
                bot, top = plot_df['High'].iloc[i], plot_df['Low'].iloc[i-2]
                if (top - bot) > (plot_df['Close'].mean() * 0.002):
                    rect = patches.Rectangle((idx-0.4, bot), 10, top - bot, linewidth=0, facecolor='#ef4444', alpha=0.2)
                    ax.add_patch(rect)
        if sweep_type:
            lowest = plot_df['Low'].min()
            label_text = "🌊 MAJOR SWEEP" if sweep_type == "MAJOR" else "💧 MINOR SWEEP"
            label_color = "#ef4444" if sweep_type == "MAJOR" else "#fbbf24" 
            ax.annotate(label_text, xy=(x_max-3, lowest), xytext=(x_max-10, lowest*0.98), arrowprops=dict(facecolor=label_color, shrink=0.05), color=label_color, fontsize=11, fontweight='bold', ha='center')
        line_style = ':' if is_wait else '-'
        ax.axhline(tp, color='#22c55e', linestyle=line_style, linewidth=1.5, alpha=0.8)
        ax.axhline(entry, color='#3b82f6', linestyle=line_style, linewidth=1.5, alpha=0.9)
        ax.axhline(sl, color='#ef4444', linestyle=line_style, linewidth=1.5, alpha=0.8)
        ax.text(x_min+1, tp, " TP", color='#22c55e', fontsize=10, va='bottom', fontweight='bold')
        ax.text(x_min+1, entry, " ENTRY", color='#3b82f6', fontsize=10, va='bottom', fontweight='bold')
        ax.text(x_min+1, sl, " SL", color='#ef4444', fontsize=10, va='top', fontweight='bold')
        if not is_wait:
            ax.add_patch(patches.Rectangle((x_min, entry), x_max-x_min, tp-entry, linewidth=0, facecolor='#22c55e', alpha=0.08))
            ax.add_patch(patches.Rectangle((x_min, sl), x_max-x_min, entry-sl, linewidth=0, facecolor='#ef4444', alpha=0.08))
        buf = BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.1, facecolor='#1e293b', edgecolor='none', dpi=100)
        plt.close(fig)
        buf.seek(0)
        return f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
    except Exception as e: 
        print(f"Plot Error: {e}")
        return create_error_image("Plot Error")

# --- 9. Discord 通知 ---
def send_discord_alert(results):
    if not DISCORD_WEBHOOK:
        print("⚠️ No Discord Webhook configured. Skipping alerts.")
        return

    top_picks = [r for r in results if r['score'] >= 85 and r['signal'] == "LONG"][:3]
    
    if not top_picks:
        print("ℹ️ No high-quality setups found to alert.")
        return

    print(f"🚀 Sending alerts for: {[p['ticker'] for p in top_picks]}")

    embeds = []
    for pick in top_picks:
        data = pick['data']
        embed = {
            "title": f"🚀 {pick['ticker']} - Potential Long Setup",
            "description": f"**Score: {pick['score']}** | Vol: {data['rvol']:.1f}x",
            "color": 5763717, # Green
            "fields": [
                {"name": "Entry", "value": f"${data['entry']:.2f}", "inline": True},
                {"name": "Stop Loss", "value": f"${data['sl']:.2f}", "inline": True},
                {"name": "Current", "value": f"${pick['price']:.2f}", "inline": True},
                {"name": "Status", "value": "✅ LONG", "inline": True}
            ],
            "footer": {"text": "Daily Dip Pro • SMC Strategy"}
        }
        embeds.append(embed)

    payload = {
        "username": "Daily Dip Bot",
        "embeds": embeds
    }

    try:
        resp = requests.post(DISCORD_WEBHOOK, json=payload)
        if resp.status_code == 204:
            print("✅ Discord alert sent successfully!")
        else:
            print(f"⚠️ Discord returned status code: {resp.status_code}")
            print(resp.text)
    except Exception as e:
        print(f"❌ Failed to send Discord alert: {e}")

# --- 10. 單一股票處理 ---
def process_ticker(t, app_data_dict, market_bonus):
    try:
        df_d = fetch_data_safe(t, "1y", "1d")
        if df_d is None or len(df_d) < 50: return None
        df_h = fetch_data_safe(t, "1mo", "1h")
        if df_h is None or df_h.empty: df_h = df_d
        curr = float(df_d['Close'].iloc[-1])
        sma200 = float(df_d['Close'].rolling(200).mean().iloc[-1])
        if pd.isna(sma200): sma200 = curr
        bsl, ssl, eq, entry, sl, found_fvg, sweep_type = calculate_smc(df_d)
        tp = bsl
        
        earnings_warning = check_earnings(t) 
        
        is_bullish = curr > sma200
        in_discount = curr < eq
        
        wait_reason = ""
        signal = "WAIT"
        
        if not is_bullish: wait_reason = "📉 逆勢"
        elif not in_discount: wait_reason = "💸 溢價"
        elif not (found_fvg or sweep_type): wait_reason = "💤 無訊號"
        else:
            signal = "LONG"
            wait_reason = ""

        indicators = calculate_indicators(df_d)
        score, reasons, rr, rvol, perf_30d, strategies = calculate_quality_score(df_d, entry, sl, tp, is_bullish, market_bonus, sweep_type, indicators)
        
        is_wait = (signal == "WAIT")
        img_d = generate_chart(df_d, t, "Daily SMC", entry, sl, tp, is_wait, sweep_type)
        img_h = generate_chart(df_h, t, "Hourly Entry", entry, sl, tp, is_wait, sweep_type)
        cls = "b-long" if signal == "LONG" else "b-wait"
        
        elite_html = ""
        if score >= 85 or sweep_type or rvol > 1.5:
            reasons_html = "".join([f"<li style='margin-bottom:4px;'>✅ {r}</li>" for r in reasons])
            confluence_text = f"🔥 <b>策略共振：</b> {strategies} 訊號" if strategies >= 2 else ""
            sweep_text = ""
            if sweep_type == "MAJOR":
                sweep_text = "<div style='margin-top:10px;padding:10px;background:rgba(239,68,68,0.15);border-radius:6px;border-left:4px solid #ef4444;color:#fca5a5;font-size:0.85rem;'><b>🌊 強力獵殺 (Major Sweep)</b><br>跌破20日低點後強勢收回，機構掃盤跡象明顯。</div>"
            elif sweep_type == "MINOR":
                sweep_text = "<div style='margin-top:10px;padding:10px;background:rgba(251,191,36,0.15);border-radius:6px;border-left:4px solid #fbbf24;color:#fcd34d;font-size:0.85rem;'><b>💧 短線獵殺 (Minor Sweep)</b><br>跌破10日低點後收回，短線資金進場。</div>"
            elite_html = f"<div style='background:#1e293b; border:1px solid #334155; padding:15px; border-radius:12px; margin:15px 0; box-shadow: 0 4px 6px rgba(0,0,0,0.2);'><div style='font-weight:bold; color:#10b981; font-size:1.1rem; margin-bottom:8px;'>💎 AI 戰略分析 (Score {score})</div><div style='font-size:0.9rem; color:#cbd5e1; margin-bottom:10px;'>{confluence_text}</div><ul style='margin:0; padding-left:20px; font-size:0.85rem; color:#94a3b8; line-height:1.5;'>{reasons_html}</ul>{sweep_text}</div>"
        
        stats_dashboard = f"<div style='display:grid; grid-template-columns: 1fr 1fr 1fr; gap:10px; margin-bottom:15px;'><div style='background:#334155; padding:10px; border-radius:8px; text-align:center;'><div style='font-size:0.75rem; color:#94a3b8; margin-bottom:2px;'>Current</div><div style='font-size:1.2rem; font-weight:900; color:#f8fafc;'>${curr:.2f}</div></div><div style='background:rgba(16,185,129,0.15); padding:10px; border-radius:8px; text-align:center; border:1px solid #10b981;'><div style='font-size:0.75rem; color:#10b981; margin-bottom:2px;'>Target (TP)</div><div style='font-size:1.2rem; font-weight:900; color:#10b981;'>${tp:.2f}</div></div><div style='background:rgba(251,191,36,0.15); padding:10px; border-radius:8px; text-align:center; border:1px solid #fbbf24;'><div style='font-size:0.75rem; color:#fbbf24; margin-bottom:2px;'>R:R</div><div style='font-size:1.2rem; font-weight:900; color:#fbbf24;'>{rr:.1f}R</div></div></div>"

        calculator_html = f"<div style='background:#334155; padding:15px; border-radius:12px; margin-top:20px; border:1px solid #475569;'><div style='font-weight:bold; color:#f8fafc; margin-bottom:10px; display:flex; align-items:center;'>🧮 風控計算器 <span style='font-size:0.7rem; color:#94a3b8; margin-left:auto;'>(Risk Management)</span></div><div style='display:flex; gap:10px; margin-bottom:10px;'><div style='flex:1;'><div style='font-size:0.7rem; color:#94a3b8; margin-bottom:4px;'>Account ($)</div><input type='number' id='calc-capital' placeholder='10000' style='width:100%; padding:8px; border-radius:6px; border:none; background:#1e293b; color:white; font-weight:bold;'></div><div style='flex:1;'><div style='font-size:0.7rem; color:#94a3b8; margin-bottom:4px;'>Risk (%)</div><input type='number' id='calc-risk' placeholder='1.0' value='1.0' style='width:100%; padding:8px; border-radius:6px; border:none; background:#1e293b; color:white; font-weight:bold;'></div></div><div style='background:#1e293b; padding:10px; border-radius:8px; display:flex; justify-content:space-between; align-items:center;'><div style='font-size:0.8rem; color:#94a3b8;'>建議股數:</div><div id='calc-result' style='font-size:1.2rem; font-weight:900; color:#fbbf24;'>0 股</div></div><div style='text-align:right; font-size:0.7rem; color:#64748b; margin-top:5px;'>Based on SL: ${sl:.2f}</div></div>"

        earn_html = ""
        if earnings_warning:
            earn_html = f"<div style='background:rgba(239,68,68,0.2); color:#fca5a5; padding:8px; border-radius:6px; font-weight:bold; margin-bottom:10px; text-align:center; border:1px solid #ef4444;'>💣 {earnings_warning}</div>"

        if signal == "LONG":
            ai_html = f"<div class='deploy-box long' style='border:none; padding:0;'><div class='deploy-title' style='color:#10b981; font-size:1.3rem; margin-bottom:15px;'>✅ LONG SETUP</div>{earn_html}{stats_dashboard}{elite_html}{calculator_html}<div style='background:#1e293b; padding:12px; border-radius:8px; margin-top:10px; display:flex; justify-content:space-between; font-family:monospace; color:#cbd5e1;'><span>🔵 Entry: ${entry:.2f}</span><span style='color:#ef4444;'>🔴 SL: ${sl:.2f}</span></div></div>"
        else:
            ai_html = f"<div class='deploy-box wait' style='background:#1e293b; border:1px solid #555;'><div class='deploy-title' style='color:#94a3b8;'>⏳ WAIT: {wait_reason}</div>{earn_html}<div style='padding:10px; color:#cbd5e1;'>目前不建議進場，因為：{wait_reason}</div></div>"
            
        app_data_dict[t] = {"signal": signal, "wait_reason": wait_reason, "deploy": ai_html, "img_d": img_d, "img_h": img_h, "score": score, "rvol": rvol, "entry": entry, "sl": sl}
        return {"ticker": t, "sector": item['sector'], "price": curr, "signal": signal, "wait_reason": wait_reason, "cls": cls, "score": score, "rvol": rvol, "perf": perf_30d, "data": {"entry": entry, "sl": sl, "rvol": rvol}, "earn": earnings_warning}
    except Exception as e:
        print(f"Err {t}: {e}")
        return None

# --- 11. 主程式 ---
def main():
    print("🚀 啟動超級篩選器 (Priority First)...")
    weekly_news_html = get_polygon_news()
    market_status, market_text, market_bonus = get_market_condition()
    market_color = "#10b981" if market_status == "BULLISH" else ("#ef4444" if market_status == "BEARISH" else "#fbbf24")
    
    APP_DATA, screener_rows_list = {}, []
    candidates_data = auto_select_candidates()
    processed_results = []
    
    for item in candidates_data:
        t = item['ticker']
        sector = item['sector']
        res = process_ticker(t, APP_DATA, market_bonus)
        if res:
            if res['signal'] == "LONG": screener_rows_list.append(res)
            processed_results.append({'ticker': t, 'sector': sector, 'score': res['score'], 'signal': res['signal'], 'price': res['price'], 'data': res['data'], 'earn': res['earn']})
            
    processed_results.sort(key=lambda x: x['score'], reverse=True)
    
    # --- 🔥 歷史數據處理邏輯 (History Logic) 🔥 ---
    history = load_history()
    
    # 設定日期字串
    today_str = datetime.now().strftime('%Y-%m-%d')
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    day_before_str = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')

    # 儲存今天的 Top 5
    top_5_today = []
    for r in processed_results[:5]:
        top_5_today.append({
            "ticker": r['ticker'], 
            "score": r['score'], 
            "sector": r['sector']
        })
    history[today_str] = top_5_today
    save_history(history) # 寫入檔案
    print(f"✅ History saved for {today_str}")

    # 讀取昨天的和前天的
    yesterday_picks = history.get(yesterday_str, [])
    day_before_picks = history.get(day_before_str, [])
    # ---------------------------------------------

    # 發送 Discord 通知
    send_discord_alert(processed_results)

    top_5_tickers = processed_results[:5]
    
    # --- 生成 HTML ---
    # 今日精選
    top_5_html = generate_ticker_grid(top_5_today, "🏆 Today's Top 5")
    # 昨日精選
    yesterday_html = generate_ticker_grid(yesterday_picks, f"🥈 Yesterday's Picks ({yesterday_str})", "top-card")
    # 前日精選
    day_before_html = generate_ticker_grid(day_before_picks, f"🥉 Day Before's Picks ({day_before_str})", "top-card")

    sector_groups = {}
    for item in processed_results:
        sec = item['sector']
        if sec not in sector_groups: sector_groups[sec] = []
        sector_groups[sec].append(item)
        
    sector_html_blocks = ""
    for sec_name, items in sector_groups.items():
        items.sort(key=lambda x: x['score'], reverse=True)
        cards = ""
        for item in items:
            t = item['ticker']
            d = APP_DATA[t]
            rvol_val = d['rvol']
            rvol_str = f"Vol {rvol_val:.1f}x"
            rvol_html = f"<span style='color:#64748b;font-size:0.75rem'>{rvol_str}</span>"
            if rvol_val > 1.5: rvol_html = f"<span style='color:#f472b6;font-weight:bold;font-size:0.8rem'>{rvol_str} 🔥</span>"
            elif rvol_val > 1.2: rvol_html = f"<span style='color:#fbbf24;font-size:0.8rem'>{rvol_str} ⚡</span>"
            
            if d['signal'] == 'WAIT':
                badge_html = f"<span class='badge b-wait' style='font-size:0.65rem'>{d['wait_reason']}</span>"
            else:
                badge_html = "<span class='badge b-long'>LONG</span>"

            # 🔥 在普通卡片也加上財報警告
            earn_badge = ""
            if item['earn']:
                earn_badge = f"<span style='color:#ef4444;font-weight:bold;font-size:0.7rem;margin-right:5px;'>{item['earn']}</span>"

            cards += f"<div class='card' onclick=\"openModal('{t}')\"><div class='head'><div><div class='code'>{t}</div></div><div style='text-align:right'>{badge_html}</div></div><div style='display:flex;justify-content:space-between;align-items:center;margin-top:5px'><span>{earn_badge}<span style='font-size:0.8rem;color:{('#10b981' if d['score']>=85 else '#3b82f6')}'>Score {d['score']}</span></span>{rvol_html}</div></div>"
        sector_html_blocks += f"<h3 class='sector-title'>{sec_name}</h3><div class='grid'>{cards}</div>"

    # 🔥 關鍵修復：使用 Base64 編碼傳輸數據，避免 JSON 語法錯誤
    json_str = json.dumps(APP_DATA)
    b64_data = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')

    final_html = f"""<!DOCTYPE html>
    <html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="https://cdn-icons-png.flaticon.com/512/3310/3310624.png"><title>DailyDip Pro</title>
    <style>:root {{ --bg:#0f172a; --card:#1e293b; --text:#f8fafc; --acc:#3b82f6; --g:#10b981; --r:#ef4444; --y:#fbbf24; }} body {{ background:var(--bg); color:var(--text); font-family:sans-serif; margin:0; padding:10px; }} .tabs {{ display:flex; gap:10px; overflow-x:auto; border-bottom:1px solid #333; padding-bottom:10px; }} .tab {{ padding:8px 16px; background:#334155; border-radius:6px; cursor:pointer; font-weight:bold; white-space:nowrap; }} .tab.active {{ background:var(--acc); }} .content {{ display:none; }} .content.active {{ display:block; }} .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:12px; }} .card {{ background:rgba(30,41,59,0.7); backdrop-filter:blur(10px); border:1px solid #333; border-radius:12px; padding:12px; cursor:pointer; }} .top-grid {{ display:grid; grid-template-columns:repeat(5, 1fr); gap:10px; margin-bottom:20px; overflow-x:auto; }} .top-card {{ text-align:center; min-width:100px; }} 
    .modal {{ display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); z-index:99; justify-content:center; overflow-y:auto; padding:10px; backdrop-filter: blur(5px); }} 
    .m-content {{ background:#1e293b; width:100%; max-width:600px; padding:20px; margin-top:40px; border-radius:16px; border: 1px solid #334155; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); }} 
    #chart-d, #chart-h {{ width: 100%; min-height: 300px; background: #1e293b; display: flex; align-items: center; justify-content: center; }}
    #chart-d img, #chart-h img {{ width: 100% !important; height: auto !important; display: block; border-radius: 8px; }}
    .sector-title {{ border-left:4px solid var(--acc); padding-left:10px; margin:20px 0 10px; }} table {{ width:100%; border-collapse:collapse; }} td, th {{ padding:8px; border-bottom:1px solid #333; text-align:left; }} .badge {{ padding:4px 8px; border-radius:6px; font-weight:bold; font-size:0.75rem; }} .b-long {{ color:var(--g); border:1px solid var(--g); background:rgba(16,185,129,0.2); }} .b-wait {{ color:#94a3b8; border:1px solid #555; }} .market-bar {{ background:#1e293b; padding:10px; border-radius:8px; margin-bottom:20px; display:flex; gap:10px; border:1px solid #333; }} 
    .macro-grid {{ display:grid; grid-template-columns: repeat(4, 1fr); gap:10px; margin-bottom:15px; height: 120px; }}
    .macro-card {{ width: 100%; height: 100%; }}
    .news-card {{ background:var(--card); padding:15px; border-radius:8px; border:1px solid #333; margin-bottom:10px; }}
    .news-title {{ font-size:1rem; font-weight:bold; color:var(--text); text-decoration:none; display:block; margin-top:5px; }}
    .news-meta {{ font-size:0.75rem; color:#94a3b8; display:flex; justify-content:space-between; }}
    @media (max-width: 600px) {{ .top-grid, .macro-grid {{ grid-template-columns: repeat(2, 1fr); }} }}</style></head>
    <body>
    <div class="tradingview-widget-container" style="margin-bottom:15px">
      <div class="tradingview-widget-container__widget"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js" async>
      {{
      "symbols": [{{"proName": "FOREXCOM:SPXUSD", "title": "S&P 500"}},{{"proName": "FOREXCOM:NSXUSD", "title": "US 100"}},{{"proName": "FX_IDC:EURUSD", "title": "EUR/USD"}},{{"proName": "BITSTAMP:BTCUSD", "title": "Bitcoin"}},{{"proName": "BITSTAMP:ETHUSD", "title": "Ethereum"}}],
      "showSymbolLogo": true, "colorTheme": "dark", "isTransparent": false, "displayMode": "adaptive", "locale": "en"
      }}
      </script>
    </div>
    <div class="market-bar" style="border-left:4px solid {market_color}"><div>{ "🟢" if market_status=="BULLISH" else "🔴" }</div><div><b>Market: {market_status}</b><div style="font-size:0.8rem;color:#94a3b8">{market_text}</div></div></div>
    
    <div class="macro-grid">
        <div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js" async>{{"symbol": "CBOE:VIX","width": "100%","height": "100%","locale": "en","dateRange": "1M","colorTheme": "dark","isTransparent": true,"autosize": true,"largeChartUrl": ""}}</script></div>
        <div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js" async>{{"symbol": "BINANCE:BTCUSDT","width": "100%","height": "100%","locale": "en","dateRange": "1M","colorTheme": "dark","isTransparent": true,"autosize": true,"largeChartUrl": ""}}</script></div>
        <div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js" async>{{"symbol": "TVC:DXY","width": "100%","height": "100%","locale": "en","dateRange": "1M","colorTheme": "dark","isTransparent": true,"autosize": true,"largeChartUrl": ""}}</script></div>
        <div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js" async>{{"symbol": "TVC:US10Y","width": "100%","height": "100%","locale": "en","dateRange": "1M","colorTheme": "dark","isTransparent": true,"autosize": true,"largeChartUrl": ""}}</script></div>
    </div>

    {top_5_html}
    {yesterday_html}
    {day_before_html}

    <div class="tabs"><div class="tab active" onclick="setTab('overview',this)">📊 板塊分類</div><div class="tab" onclick="setTab('news',this)">📰 News</div></div>
    
    <div id="overview" class="content active">
        {sector_html_blocks if sector_html_blocks else "<div style='text-align:center;padding:30px;color:#666'>今日市場極度冷清，無符合嚴格條件的股票 🐻</div>"}
        
        <h3 style="margin-top:40px; border-bottom:1px solid #333; padding-bottom:10px;">📅 財經日曆 (Economic Calendar)</h3>
        <div class="tradingview-widget-container" style="height:400px">
          <div class="tradingview-widget-container__widget"></div>
          <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-events.js" async>
          {{
          "colorTheme": "dark", "isTransparent": true, "width": "100%", "height": "100%", "locale": "en", "importanceFilter": "-1,0,1", "currencyFilter": "USD"
          }}
          </script>
        </div>
    </div>

    <div id="news" class="content">{weekly_news_html}</div>
    <div style="text-align:center;color:#666;margin-top:30px;font-size:0.8rem">Updated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</div>
    
    <div id="modal" class="modal" onclick="this.style.display='none'">
        <div class="m-content" onclick="event.stopPropagation()">
            <div style="display:flex;justify-content:space-between;margin-bottom:15px;align-items:center;">
                <h2 id="m-ticker" style="margin:0; font-size:2rem; font-weight:800;"></h2>
                <div id="btn-area"></div>
            </div>
            <div id="m-deploy"></div>
            <div style="margin-top:20px;">
                <div style="font-weight:bold;color:#cbd5e1;margin-bottom:5px;">Daily SMC</div>
                <div id="chart-d"></div>
            </div>
            <div style="margin-top:15px;">
                <div style="font-weight:bold;color:#cbd5e1;margin-bottom:5px;">Hourly Entry</div>
                <div id="chart-h"></div>
            </div>
            <button onclick="document.getElementById('modal').style.display='none'" style="width:100%;padding:15px;background:#334155;border:none;color:white;border-radius:8px;margin-top:20px;font-weight:bold;cursor:pointer;">Close</button>
        </div>
    </div>

    <script>
    // 🔥 使用 Base64 解碼，避免 JSON 語法錯誤
    const rawData = "{b64_data}";
    const DATA = JSON.parse(atob(rawData));

    function setTab(id,el){{document.querySelectorAll('.content').forEach(c=>c.classList.remove('active'));document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));document.getElementById(id).classList.add('active');el.classList.add('active');}}
    
    function updateCalculator(entry, sl) {{
        const cap = parseFloat(document.getElementById('calc-capital').value) || 0;
        const risk = parseFloat(document.getElementById('calc-risk').value) || 0;
        const resultEl = document.getElementById('calc-result');
        localStorage.setItem('user_capital', cap);
        localStorage.setItem('user_risk', risk);
        if (cap > 0 && risk > 0 && entry > 0 && sl > 0 && entry > sl) {{
            const riskAmount = cap * (risk / 100);
            const riskPerShare = entry - sl;
            const shares = Math.floor(riskAmount / riskPerShare);
            resultEl.innerText = shares + " 股";
            resultEl.style.color = "#fbbf24";
        }} else {{
            resultEl.innerText = "---";
            resultEl.style.color = "#64748b";
        }}
    }}

    function openModal(t){{
        const d=DATA[t];if(!d)return;
        document.getElementById('modal').style.display='flex';
        document.getElementById('m-ticker').innerText=t;
        document.getElementById('m-deploy').innerHTML=d.deploy;
        document.getElementById('chart-d').innerHTML='<img src="'+d.img_d+'" style="width:100%; display:block;">';
        document.getElementById('chart-h').innerHTML='<img src="'+d.img_h+'" style="width:100%; display:block;">';
        
        const btnArea=document.getElementById('btn-area'); btnArea.innerHTML='';
        const tvBtn=document.createElement('button'); tvBtn.innerText='📈 Chart';
        tvBtn.style.cssText='background:#2563eb;border:none;color:white;padding:8px 16px;border-radius:6px;font-weight:bold;cursor:pointer;box-shadow:0 2px 4px rgba(0,0,0,0.2);';
        
        tvBtn.onclick = function() {{
            const currentTicker = document.getElementById('m-ticker').innerText;
            const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
            
            if (isMobile) {{
                window.location.href = 'tradingview://chart?symbol=' + currentTicker;
                setTimeout(() => {{
                    window.location.href = 'https://www.tradingview.com/chart/?symbol=' + currentTicker;
                }}, 1500);
            }} else {{
                window.open('https://www.tradingview.com/chart/?symbol=' + currentTicker, '_blank');
            }}
        }};
        btnArea.appendChild(tvBtn);

        if (d.signal === "LONG") {{
            const capInput = document.getElementById('calc-capital');
            const riskInput = document.getElementById('calc-risk');
            capInput.value = localStorage.getItem('user_capital') || '';
            riskInput.value = localStorage.getItem('user_risk') || '1.0';
            const runCalc = () => updateCalculator(d.data.entry, d.data.sl);
            capInput.oninput = runCalc;
            riskInput.oninput = runCalc;
            runCalc();
        }}
    }}
    </script></body></html>"""
    
    with open("index.html", "w", encoding="utf-8") as f: f.write(final_html)
    print("✅ index.html generated!")

if __name__ == "__main__":
    main()
