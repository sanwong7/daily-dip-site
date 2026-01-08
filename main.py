import os
import matplotlib
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

# --- 設定 ---
API_KEY = os.environ.get("POLYGON_API_KEY")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")
HISTORY_FILE = "history.json"

# --- 股票名單 ---
ALL_TICKERS = [
    "TSLA", "AMZN", "NVDA", "AAPL", "MSFT", "GOOGL", "META", "AMD", "PLTR", "SOFI", "HOOD", "COIN", "MSTR", "MARA", "TSM", "ASML", "ARM",
    "QCOM", "INTC", "MU", "AMAT", "LRCX", "ADI", "TXN", "KLAC", "MRVL", "STM", "ON", "GFS", "SMCI", "DELL", "HPQ",
    "ORCL", "ADBE", "CRM", "SAP", "INTU", "IBM", "NOW", "UBER", "ABNB", "PANW", "SNPS", "CDNS", "CRWD", "SQ", "SHOP", "WDAY", "ROP", "SNOW", "DDOG", "ZS", "NET", "TEAM", "MDB", "PATH", "U", "APP", "RDDT", "IONQ",
    "JPM", "V", "MA", "BAC", "WFC", "MS", "GS", "BLK", "C", "AXP", "PYPL", "AFRM", "UPST",
    "WMT", "COST", "PG", "KO", "PEP", "MCD", "SBUX", "NKE", "DIS", "HD", "LOW", "TGT", "CMG", "LULU", "BKNG", "MAR", "HILTON", "CL",
    "LLY", "JNJ", "UNH", "ABBV", "MRK", "TMO", "DHR", "ISRG", "VRTX", "REGN", "PFE", "AMGN", "BMY", "CVS", "HIMS",
    "CAT", "DE", "GE", "HON", "UNP", "UPS", "XOM", "CVX", "COP", "SLB", "EOG", "OXY",
    "TM", "HMC", "STLA", "F", "GM", "RIVN", "LCID", "NIO", "XPEV", "LI",
    "BABA", "PDD", "JD", "BIDU", "TCEHY",
    "NFLX", "CMCSA", "TMUS", "VZ", "T", "ASTS", "SPY"
]

# --- 歷史紀錄模組 ---
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f: return json.load(f)
        except: return {}
    return {}

def save_history(history):
    try:
        with open(HISTORY_FILE, "w") as f: json.dump(history, f, indent=4)
    except: pass

def generate_ticker_grid(picks, title, color_class="top-card"):
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

# --- 核心數據獲取 (批量) ---
def fetch_all_data():
    print("🚀 啟動批量下載引擎...")
    try:
        # 下載 Daily 數據
        data = yf.download(ALL_TICKERS, period="1y", group_by='ticker', auto_adjust=True, threads=True)
        return data
    except Exception as e:
        print(f"❌ Bulk download failed: {e}")
        return None

# 🔥 優化 B：獲取 1小時 數據確認 MSS (只針對候選股)
def check_hourly_mss(ticker):
    try:
        # 只抓最近 5 天的 1h K線
        df_h = yf.download(ticker, period="5d", interval="1h", progress=False, auto_adjust=True)
        if df_h is None or len(df_h) < 5: return False
        
        # 簡單 MSS 邏輯：最後一根 K 線的收盤價 > 前一根 K 線的最高價 (或前一個明顯高點)
        # 這裡採用動能判斷：最近 2 根 K 線是否有強勢反彈
        last_close = df_h['Close'].iloc[-1]
        prev_high = df_h['High'].iloc[-2]
        
        return last_close > prev_high
    except: return False

# --- 技術指標計算 ---
def calculate_atr(df, period=14):
    """🔥 優化 A：計算 ATR (平均真實波幅) 用於止損"""
    high = df['High']
    low = df['Low']
    close = df['Close'].shift(1)
    
    tr1 = high - low
    tr2 = (high - close).abs()
    tr3 = (low - close).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

def get_stock_sector(ticker):
    if ticker == "SPY": return "Market"
    if ticker in ["NVDA", "AMD", "TSM", "INTC", "MU", "QCOM", "ASML", "AMAT", "LRCX"]: return "⚡ 半導體"
    if ticker in ["AAPL", "MSFT", "GOOGL", "META", "CRM", "ADBE", "AMZN", "TSLA", "NFLX"]: return "💻 科技與軟體"
    if ticker in ["JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "BLK", "COIN", "HOOD"]: return "🏦 金融服務"
    return "🌐 其他產業"

# --- 核心策略運算 (SMC + ATR + VSA) ---
def calculate_smc_strategy(df, ticker):
    try:
        if len(df) < 50: return None
        
        # 基礎數據
        atr = calculate_atr(df).iloc[-1] # 獲取最新 ATR
        close = df['Close'].iloc[-1]
        low_50d = df['Low'].tail(50).min()
        high_50d = df['High'].tail(50).max()
        bsl = high_50d # 止盈目標 (上方流動性)
        
        # --- 1. 判斷 Sweep (獵殺) ---
        # 邏輯：今天的低點刺破了過去 10 天的低點，但收盤收上去了
        low_10d = df['Low'].tail(11).iloc[:-1].min() # 不包含今天的過去10天最低
        today_low = df['Low'].iloc[-1]
        today_close = df['Close'].iloc[-1]
        
        is_sweep = False
        sweep_type = None
        
        if today_low < low_10d and today_close > today_low:
            is_sweep = True
            sweep_type = "MAJOR" if today_low <= low_50d else "MINOR"
        
        # --- 2. 優化 A: ATR 止損計算 ---
        # 舊邏輯：sl = low_50d * 0.99 (太寬)
        # 新邏輯：sl = Sweep Candle Low - 1 * ATR (精確)
        if is_sweep:
            sl = today_low - (1.0 * atr)
            best_entry = today_close # 假設收盤價進場
        else:
            # 如果沒有 Sweep，用傳統折價區邏輯
            sl = low_50d * 0.99
            best_entry = (high_50d + low_50d) / 2
            
        # 確保 SL 合理
        if sl >= best_entry: sl = best_entry * 0.95

        return bsl, sl, best_entry, is_sweep, sweep_type
    except Exception as e:
        return None

def calculate_score_v2(df, is_sweep, sweep_type, is_bullish, ticker):
    """🔥 優化 C：包含 VSA 量價分析的評分系統"""
    score = 60
    
    # 1. 趨勢加分
    if is_bullish: score += 10
    
    # 2. Sweep 加分 (最重要)
    if is_sweep:
        score += 25
        if sweep_type == "MAJOR": score += 10 # 破50天低點更強
        
    # 3. 🔥 優化 C: VSA 成交量分析 (恐慌殺盤檢查)
    # 檢查：今天是否爆量？(比過去 5 天均量大 1.5 倍)
    vol_ma5 = df['Volume'].iloc[-6:-1].mean()
    today_vol = df['Volume'].iloc[-1]
    
    if vol_ma5 > 0:
        rvol = today_vol / vol_ma5
        if rvol > 1.5: 
            score += 15 # 爆量收針 = 機構進場鐵證
        elif rvol < 0.8:
            score -= 10 # 無量下跌 = 沒人接盤，危險
    else:
        rvol = 1.0

    # 4. RSI 超賣反彈
    rsi = calculate_rsi(df).iloc[-1]
    if 30 <= rsi <= 50: score += 10 # 黃金反彈區
    
    # 5. 🔥 優化 B: 1小時 MSS 確認 (二次請求)
    # 如果分數已經不錯 (>80)，我們去查 1小時圖來做最後確認
    hourly_confirmed = False
    if score >= 80:
        # print(f"🔎 Checking Hourly MSS for {ticker}...")
        if check_hourly_mss(ticker):
            score += 15
            hourly_confirmed = True
    
    return int(score), rvol, hourly_confirmed

def calculate_rsi(df, period=14):
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- 繪圖 ---
def generate_chart(df, ticker, title, entry, sl, tp):
    try:
        plt.close('all')
        plot_df = df.tail(60).copy()
        fig, ax = plt.subplots(figsize=(8, 5))
        fig.patch.set_facecolor('#1e293b')
        ax.set_facecolor('#1e293b')
        
        up = plot_df[plot_df.Close >= plot_df.Open]
        down = plot_df[plot_df.Close < plot_df.Open]
        col1 = '#22c55e'
        col2 = '#ef4444'
        
        ax.vlines(plot_df.index, plot_df.Low, plot_df.High, color='white', linewidth=1)
        ax.vlines(up.index, up.Open, up.Close, color=col1, linewidth=4)
        ax.vlines(down.index, down.Open, down.Close, color=col2, linewidth=4)
        
        # 畫 SL (ATR 優化版)
        ax.axhline(tp, color=col1, linestyle='--', label='TP')
        ax.axhline(entry, color='#3b82f6', linestyle='-', label='Entry')
        ax.axhline(sl, color=col2, linestyle='--', label='SL (ATR)')
        
        # 標註最新價格
        ax.text(plot_df.index[-1], entry, f" {entry:.2f}", color='#3b82f6', fontsize=10, va='center')
        ax.text(plot_df.index[-1], sl, f" {sl:.2f}", color=col2, fontsize=10, va='center')

        ax.set_title(f"{ticker} - {title}", color='white', fontweight='bold')
        ax.tick_params(axis='x', colors='white', rotation=45)
        ax.tick_params(axis='y', colors='white')
        
        buf = BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', facecolor='#1e293b')
        plt.close(fig)
        return f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
    except: return ""

# --- 網頁與主程式 ---
def get_polygon_news():
    if not API_KEY: return ""
    try:
        url = f"https://api.polygon.io/v2/reference/news?limit=10&apiKey={API_KEY}"
        data = requests.get(url, timeout=5).json()
        html = ""
        if data.get('results'):
            for item in data['results']:
                html += f"<div class='news-card'><a href='{item['article_url']}' target='_blank' style='color:#cbd5e1;text-decoration:none'>{item['title']}</a></div>"
        return html
    except: return ""

def get_macro_html():
    return """
    <div class="macro-grid">
        <div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js" async>{"symbol": "CBOE:VIX","width": "100%","height": "100%","locale": "en","dateRange": "1M","colorTheme": "dark","isTransparent": true,"autosize": true,"largeChartUrl": ""}</script></div>
        <div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js" async>{"symbol": "BINANCE:BTCUSDT","width": "100%","height": "100%","locale": "en","dateRange": "1M","colorTheme": "dark","isTransparent": true,"autosize": true,"largeChartUrl": ""}</script></div>
        <div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js" async>{"symbol": "TVC:DXY","width": "100%","height": "100%","locale": "en","dateRange": "1M","colorTheme": "dark","isTransparent": true,"autosize": true,"largeChartUrl": ""}</script></div>
        <div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js" async>{"symbol": "TVC:US10Y","width": "100%","height": "100%","locale": "en","dateRange": "1M","colorTheme": "dark","isTransparent": true,"autosize": true,"largeChartUrl": ""}</script></div>
    </div>"""

def main():
    data = fetch_all_data()
    if data is None or data.empty:
        print("❌ Critical Error: No data fetched.")
        return

    try:
        spy_df = data['SPY']
        spy_curr = spy_df['Close'].iloc[-1]
        spy_ma = spy_df['Close'].rolling(50).mean().iloc[-1]
        market_status = "BULLISH" if spy_curr > spy_ma else "BEARISH"
    except: market_status = "NEUTRAL"
    
    print(f"🌍 Market Status: {market_status}")
    market_color = "#10b981" if market_status == "BULLISH" else "#ef4444"

    results = []
    app_data = {}
    
    for ticker in ALL_TICKERS:
        if ticker == 'SPY': continue
        try:
            df = data[ticker].dropna()
            if len(df) < 50: continue
            
            # 1. 執行新策略運算 (含 ATR 止損)
            strat = calculate_smc_strategy(df, ticker)
            if not strat: continue
            bsl, sl, entry, is_sweep, sweep_type = strat
            
            # 2. 評分 (含 VSA 和 Hourly MSS)
            score, rvol, mss_confirmed = calculate_score_v2(df, is_sweep, sweep_type, market_status=="BULLISH", ticker)
            
            # 3. 決定訊號
            signal = "LONG" if score >= 75 else "WAIT"
            
            # 4. 繪圖
            chart_title = "Daily Chart + ATR SL"
            if mss_confirmed: chart_title += " + 1h MSS ✅"
            img = generate_chart(df, ticker, chart_title, entry, sl, bsl)
            
            res = {
                "ticker": ticker,
                "sector": get_stock_sector(ticker),
                "score": score,
                "signal": signal,
                "rvol": rvol,
                "data": {"entry": entry, "sl": sl}, # 這裡的 sl 已經是 ATR 優化過的了
                "img": img,
                "mss": mss_confirmed
            }
            results.append(res)
            app_data[ticker] = res
        except Exception as e: continue

    results.sort(key=lambda x: x['score'], reverse=True)
    
    # --- 歷史數據邏輯 ---
    history = load_history()
    today_str = datetime.now().strftime('%Y-%m-%d')
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    day_before_str = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')

    top_5_today = []
    for r in results[:5]:
        top_5_today.append({"ticker": r['ticker'], "score": r['score'], "sector": r['sector']})
    history[today_str] = top_5_today
    save_history(history)

    yesterday_picks = history.get(yesterday_str, [])
    day_before_picks = history.get(day_before_str, [])
    # ------------------

    # Discord 通知 (只發最強的)
    if DISCORD_WEBHOOK and results:
        top = [r for r in results if r['score'] >= 85][:3]
        if top:
            embeds = []
            for x in top:
                mss_text = "✅ 1h MSS Confirmed" if x['mss'] else "⚠️ No Hourly Conf."
                embeds.append({"title": f"🚀 {x['ticker']}", "description": f"Score: {x['score']} | Vol: {x['rvol']:.1f}x\n{mss_text}", "color": 5763717})
            try: requests.post(DISCORD_WEBHOOK, json={"username": "Daily Dip Bot", "embeds": embeds})
            except: pass

    # HTML 生成
    macro_html = get_macro_html()
    news_html = get_polygon_news()
    
    today_html = generate_ticker_grid(results[:5], "🏆 Today's Top 5 (AI + VSA)")
    yesterday_html = generate_ticker_grid(yesterday_picks, f"🥈 Yesterday ({yesterday_str})", "top-card")
    day_before_html = generate_ticker_grid(day_before_picks, f"🥉 Day Before ({day_before_str})", "top-card")

    sector_groups = {}
    for item in results:
        sec = item['sector']
        if sec not in sector_groups: sector_groups[sec] = []
        sector_groups[sec].append(item)
        
    sector_html_blocks = ""
    for sec_name, items in sector_groups.items():
        items.sort(key=lambda x: x['score'], reverse=True)
        cards = ""
        for item in items:
            t = item['ticker']
            d = app_data[t]
            rvol_html = f"<span style='color:#f472b6;font-size:0.8rem'>Vol {d['rvol']:.1f}x 🔥</span>" if d['rvol'] > 1.5 else f"<span style='color:#64748b;font-size:0.75rem'>Vol {d['rvol']:.1f}x</span>"
            badge_html = "<span class='badge long'>LONG</span>" if d['signal'] == 'LONG' else "<span class='badge wait'>WAIT</span>"
            mss_badge = "⚡" if d['mss'] else ""
            
            cards += f"<div class='card' onclick=\"openModal('{t}')\"><div class='head'><div><div class='code'>{t} {mss_badge}</div></div><div style='text-align:right'>{badge_html}</div></div><div style='display:flex;justify-content:space-between;align-items:center;margin-top:5px'><span>Score: {d['score']}</span>{rvol_html}</div></div>"
        sector_html_blocks += f"<h3 class='sector-title'>{sec_name}</h3><div class='grid'>{cards}</div>"

    json_str = json.dumps(app_data)
    
    final_html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Dip Pro (VSA+ATR)</title>
    <style>
        :root {{ --bg: #0f172a; --card: #1e293b; --text: #f8fafc; --acc: #3b82f6; }}
        body {{ background: var(--bg); color: var(--text); font-family: sans-serif; padding: 10px; margin: 0; }}
        .macro-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; height: 120px; }}
        .top-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 20px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; }}
        .card {{ background: var(--card); padding: 15px; border-radius: 8px; border: 1px solid #334155; cursor: pointer; }}
        .top-card {{ text-align: center; background: rgba(251,191,36,0.1); border-color: #fbbf24; }}
        .badge {{ padding: 2px 6px; border-radius: 4px; font-size: 0.8rem; }}
        .long {{ background: rgba(16,185,129,0.2); color: #10b981; border: 1px solid #10b981; }}
        .wait {{ background: rgba(148,163,184,0.2); color: #94a3b8; border: 1px solid #94a3b8; }}
        .modal {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); z-index: 99; padding: 20px; justify-content: center; overflow-y: auto; }}
        .modal-content {{ background: var(--card); padding: 20px; border-radius: 12px; max-width: 600px; width: 100%; margin-top: 50px; }}
        img {{ width: 100%; border-radius: 8px; }}
        .news-card {{ background: var(--card); padding: 10px; margin-bottom: 10px; border-radius: 6px; border: 1px solid #334155; }}
        .sector-title {{ border-left:4px solid var(--acc); padding-left:10px; margin:20px 0 10px; }}
        @media (max-width: 600px) {{ .macro-grid, .top-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
    </style>
</head>
<body>
    <div style="margin-bottom:15px; border-left: 4px solid {market_color}; background: #1e293b; padding: 10px;">
        <b>Market: {market_status}</b>
    </div>

    {macro_html}

    {today_html}
    {yesterday_html}
    {day_before_html}

    <div class="tabs" style="margin-top:40px; border-bottom:1px solid #333; padding-bottom:5px; font-weight:bold; color:#fbbf24;">📊 Watchlist by Sector</div>
    {sector_html_blocks}

    <h3>📰 News</h3>
    <div>{news_html}</div>
    <div style="text-align:center; color:#666; margin-top:30px; font-size:0.8rem">Updated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</div>

    <div id="modal" class="modal" onclick="this.style.display='none'">
        <div class="modal-content" onclick="event.stopPropagation()">
            <h2 id="m-title"></h2>
            <div id="m-chart"></div>
            <div style="background:#334155; padding:15px; border-radius:8px; margin-top:15px;">
                <h4>🧮 Calculator (Risk 1%)</h4>
                <div style="display:flex; gap:10px">
                    <input type="number" id="cap" placeholder="Capital ($)" style="width:100%; padding:8px;" oninput="calc()">
                    <div id="res" style="font-size:1.2rem; font-weight:bold; color:#fbbf24; align-self:center;">0 Shares</div>
                </div>
                <div style="font-size:0.7rem; color:#888; margin-top:5px;">*SL is now calculated using ATR volatility</div>
            </div>
            <button onclick="document.getElementById('modal').style.display='none'" style="width:100%; padding:15px; margin-top:20px; background:#3b82f6; color:white; border:none; border-radius:8px;">Close</button>
        </div>
    </div>

    <script>
        const DATA = {json_str};
        let current = null;
        function openModal(t) {{
            const d = DATA[t];
            if(!d) return; 
            current = d;
            document.getElementById('modal').style.display = 'flex';
            document.getElementById('m-title').innerText = t;
            document.getElementById('m-chart').innerHTML = '<img src="' + d.img + '">';
            calc();
        }}
        function calc() {{
            if(!current) return;
            const cap = parseFloat(document.getElementById('cap').value);
            const risk = cap * 0.01;
            const diff = current.data.entry - current.data.sl;
            if(cap > 0 && diff > 0) {{
                document.getElementById('res').innerText = Math.floor(risk / diff) + " Shares";
            }}
        }}
    </script>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f: f.write(final_html)
    print("✅ Index generated!")

if __name__ == "__main__":
    main()
