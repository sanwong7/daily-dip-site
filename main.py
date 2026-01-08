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
HISTORY_FILE = "history.json" # 🔥 歷史紀錄檔案

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

# --- 歷史紀錄管理 (New) ---
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except: return {}
    return {}

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

# --- 輔助函數 ---
def get_stock_sector(ticker):
    if ticker == "SPY": return "Market"
    if ticker in ["NVDA", "AMD", "TSM", "INTC", "MU", "QCOM", "ASML", "AMAT", "LRCX"]: return "⚡ 半導體"
    if ticker in ["AAPL", "MSFT", "GOOGL", "META", "CRM", "ADBE", "AMZN", "TSLA", "NFLX"]: return "💻 科技與軟體"
    if ticker in ["JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "BLK", "COIN", "HOOD"]: return "🏦 金融服務"
    if ticker in ["LLY", "JNJ", "PFE", "MRK", "ISRG"]: return "💊 醫療保健"
    return "🌐 其他產業"

def fetch_all_data():
    print("🚀 啟動批量下載引擎...")
    try:
        data = yf.download(ALL_TICKERS, period="1y", group_by='ticker', auto_adjust=True, threads=True)
        return data
    except Exception as e:
        print(f"❌ Bulk download failed: {e}")
        return None

def calculate_smc(df):
    try:
        if len(df) < 50: return None
        window = 50
        recent = df.tail(window)
        bsl = float(recent['High'].max())
        ssl_long = float(recent['Low'].min())
        eq = (bsl + ssl_long) / 2
        best_entry = eq
        low_20d = df['Low'].tail(20).min()
        last_low = df['Low'].iloc[-1]
        sweep_type = "MAJOR" if last_low <= low_20d else None
        return bsl, ssl_long, eq, best_entry, ssl_long*0.98, sweep_type
    except: return None

def calculate_quality_score(df, entry, sl, tp, is_bullish, sweep_type):
    score = 60
    if is_bullish: score += 5
    if sweep_type: score += 25
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    curr_rsi = rsi.iloc[-1]
    if 40 <= curr_rsi <= 60: score += 10
    vol_ma = df['Volume'].rolling(20).mean()
    rvol = 1.0
    if vol_ma.iloc[-1] > 0:
        rvol = df['Volume'].iloc[-1] / vol_ma.iloc[-1]
        if rvol > 1.5: score += 10
    return int(score), rvol

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
        ax.axhline(tp, color=col1, linestyle='--', label='TP')
        ax.axhline(entry, color='#3b82f6', linestyle='-', label='Entry')
        ax.axhline(sl, color=col2, linestyle='--', label='SL')
        ax.set_title(f"{ticker} - {title}", color='white', fontweight='bold')
        ax.tick_params(axis='x', colors='white', rotation=45)
        ax.tick_params(axis='y', colors='white')
        buf = BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', facecolor='#1e293b')
        plt.close(fig)
        return f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
    except: return ""

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

def generate_ticker_grid(picks, title, color_class="top-card"):
    """輔助函數：生成股票卡片 Grid HTML"""
    if not picks:
        return f"<h3 style='color:#888'>{title} (No Data)</h3><div style='margin-bottom:20px'></div>"
    
    html = f"<h3 style='color:#fbbf24'>{title}</h3><div class='top-grid'>"
    for p in picks:
        # 兼容舊格式
        ticker = p.get('ticker')
        score = p.get('score')
        sector = p.get('sector', '')
        
        html += f"<div class='card {color_class}' onclick=\"openModal('{ticker}')\">" \
                f"<div style='font-size:1.2rem;margin-bottom:5px'><b>{ticker}</b></div>" \
                f"<div style='color:#10b981;font-weight:bold'>{score}</div>" \
                f"<div style='font-size:0.7rem;color:#888'>{sector}</div></div>"
    html += "</div>"
    return html

# --- 主程式 ---
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
            smc = calculate_smc(df)
            if not smc: continue
            bsl, ssl, eq, entry, sl, sweep = smc
            score, rvol = calculate_quality_score(df, entry, sl, bsl, market_status=="BULLISH", sweep)
            signal = "LONG" if score >= 70 else "WAIT"
            img = generate_chart(df, ticker, "Daily Chart", entry, sl, bsl)
            
            res = {
                "ticker": ticker,
                "sector": get_stock_sector(ticker),
                "score": score,
                "signal": signal,
                "rvol": rvol,
                "data": {"entry": entry, "sl": sl},
                "img": img
            }
            results.append(res)
            app_data[ticker] = res
        except: continue

    results.sort(key=lambda x: x['score'], reverse=True)
    
    # --- 🔥 歷史數據處理 🔥 ---
    history = load_history()
    today_str = datetime.now().strftime('%Y-%m-%d')
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    day_before_str = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')

    # 1. 存入今天的精選 (只存簡單數據以節省空間)
    top_5_today = []
    for r in results[:5]:
        top_5_today.append({
            "ticker": r['ticker'], 
            "score": r['score'], 
            "sector": r['sector'],
            "rvol": r['rvol']
        })
    history[today_str] = top_5_today
    save_history(history)
    print(f"✅ Saved history for {today_str}")

    # 2. 讀取過去精選
    yesterday_picks = history.get(yesterday_str, [])
    day_before_picks = history.get(day_before_str, [])
    # --------------------------

    # Discord
    if DISCORD_WEBHOOK and results:
        top = results[:3]
        if top:
            embeds = [{"title": f"🚀 {x['ticker']}", "description": f"Score: {x['score']}"} for x in top]
            try: requests.post(DISCORD_WEBHOOK, json={"username": "Daily Dip Bot", "embeds": embeds})
            except: pass

    # HTML
    macro_html = get_macro_html()
    news_html = get_polygon_news()
    
    # 生成各區塊 HTML
    today_html = generate_ticker_grid(results[:5], "🏆 Today's Top 5")
    yesterday_html = generate_ticker_grid(yesterday_picks, f"🥈 Yesterday ({yesterday_str})", "card")
    day_before_html = generate_ticker_grid(day_before_picks, f"🥉 Day Before ({day_before_str})", "card")

    list_html = ""
    for r in results:
        badge = "<span class='badge long'>LONG</span>" if r['signal']=="LONG" else "<span class='badge wait'>WAIT</span>"
        rvol_badge = f"<span style='color:#f472b6;font-size:0.8rem'>Vol {r['rvol']:.1f}x</span>"
        list_html += f"<div class='card' onclick=\"openModal('{r['ticker']}')\"><div style='display:flex;justify-content:space-between'><b>{r['ticker']}</b>{badge}</div><div style='display:flex;justify-content:space-between;margin-top:5px'><span>Score: {r['score']}</span>{rvol_badge}</div></div>"

    json_str = json.dumps(app_data)
    
    final_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Dip Pro</title>
    <style>
        :root {{ --bg: #0f172a; --card: #1e293b; --text: #f8fafc; --acc: #3b82f6; }}
        body {{ background: var(--bg); color: var(--text); font-family: sans-serif; padding: 10px; margin: 0; }}
        .macro-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; height: 120px; }}
        .top-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 20px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }}
        .card {{ background: var(--card); padding: 15px; border-radius: 8px; border: 1px solid #334155; cursor: pointer; }}
        .top-card {{ text-align: center; background: rgba(251,191,36,0.1); border-color: #fbbf24; }}
        .badge {{ padding: 2px 6px; border-radius: 4px; font-size: 0.8rem; }}
        .long {{ background: rgba(16,185,129,0.2); color: #10b981; border: 1px solid #10b981; }}
        .wait {{ background: rgba(148,163,184,0.2); color: #94a3b8; border: 1px solid #94a3b8; }}
        .modal {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); z-index: 99; padding: 20px; justify-content: center; overflow-y: auto; }}
        .modal-content {{ background: var(--card); padding: 20px; border-radius: 12px; max-width: 600px; width: 100%; margin-top: 50px; }}
        img {{ width: 100%; border-radius: 8px; }}
        .news-card {{ background: var(--card); padding: 10px; margin-bottom: 10px; border-radius: 6px; border: 1px solid #334155; }}
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

    <h3>📊 Watchlist</h3>
    <div class="grid">{list_html}</div>

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
            </div>
            <button onclick="document.getElementById('modal').style.display='none'" style="width:100%; padding:15px; margin-top:20px; background:#3b82f6; color:white; border:none; border-radius:8px;">Close</button>
        </div>
    </div>

    <script>
        const DATA = {json_str};
        let current = null;
        function openModal(t) {{
            const d = DATA[t];
            if(!d) return; // 如果是歷史紀錄的股票，可能沒有今天的詳細數據
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
