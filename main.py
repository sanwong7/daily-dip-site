import os
import matplotlib
# 強制設定後台繪圖
matplotlib.use('Agg') 
import requests
import yfinance as yf
import mplfinance as mpf
import pandas as pd
import numpy as np
import base64
import json
from io import BytesIO
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from datetime import datetime

# --- 設定 ---
API_KEY = os.environ.get("POLYGON_API_KEY")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")

# --- 1. 股票名單 ---
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

# --- 2. 輔助函數 ---
def get_stock_sector(ticker):
    try:
        info = yf.Ticker(ticker).info
        sector = info.get('sector', 'Unknown')
        industry = info.get('industry', 'Unknown')
        if "Semiconductor" in industry: return "⚡ 半導體"
        SECTOR_MAP = {
            "Technology": "💻 科技與軟體", "Communication Services": "📡 通訊與媒體", "Consumer Cyclical": "🛍️ 非必需消費 (循環)",
            "Consumer Defensive": "🛒 必需消費 (防禦)", "Financial Services": "🏦 金融服務", "Healthcare": "💊 醫療保健",
            "Energy": "🛢️ 能源", "Industrials": "🏭 工業", "Basic Materials": "🧱 原物料", "Real Estate": "🏠 房地產", "Utilities": "💡 公用事業"
        }
        return SECTOR_MAP.get(sector, "🌐 其他產業")
    except: return "🌐 其他產業"

def auto_select_candidates():
    print("🚀 啟動超級篩選器...")
    full_list = list(set(PRIORITY_TICKERS + STATIC_UNIVERSE))
    valid_tickers = []
    
    # 簡單獲取大盤數據
    try:
        spy = yf.Ticker("SPY").history(period="1y")
        spy_returns = spy['Close'].pct_change().dropna() if not spy.empty else []
    except: spy_returns = []

    for ticker in full_list:
        try:
            # 快速篩選：只有大於 200MA 的才要
            df = yf.Ticker(ticker).history(period="1y")
            if df is None or len(df) < 200: continue
            if df['Close'].iloc[-1] < df['Close'].rolling(200).mean().iloc[-1]: continue
            
            # 成交量過濾
            if (df['Volume'].tail(30).mean() * df['Close'].tail(30).mean()) < 300_000_000: continue
            
            sector = get_stock_sector(ticker)
            valid_tickers.append({'ticker': ticker, 'sector': sector})
        except: continue
    
    print(f"🏆 篩選完成! 共 {len(valid_tickers)} 隻。")
    return valid_tickers

# --- 3. 宏觀與新聞 ---
def get_polygon_news():
    if not API_KEY: return "<div style='padding:20px'>API Key Missing</div>"
    try:
        url = f"https://api.polygon.io/v2/reference/news?limit=15&order=desc&sort=published_utc&apiKey={API_KEY}"
        data = requests.get(url, timeout=10).json()
        html = ""
        if data.get('results'):
            for item in data['results']:
                dt = item.get('published_utc', '')[:10]
                html += f"<div class='news-card'><div class='news-meta'>{item.get('publisher',{}).get('name','')} • {dt}</div><a href='{item.get('article_url')}' target='_blank' class='news-title'>{item.get('title')}</a></div>"
            return html
    except: pass
    return "<div>No News</div>"

def get_market_condition():
    try:
        spy = yf.Ticker("SPY").history(period="6mo")
        return ("BULLISH", "🟢 市場順風", 5) if spy['Close'].iloc[-1] > spy['Close'].rolling(50).mean().iloc[-1] else ("NEUTRAL", "🟡 市場震盪", 0)
    except: return ("NEUTRAL", "Check Failed", 0)

# 🔥 宏觀數據 HTML (TradingView Widgets) 🔥
def get_macro_html():
    return """
    <div class="macro-grid">
        <div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js" async>{"symbol": "CBOE:VIX","width": "100%","height": "100%","locale": "en","dateRange": "1M","colorTheme": "dark","isTransparent": true,"autosize": true,"largeChartUrl": ""}</script></div>
        <div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js" async>{"symbol": "BINANCE:BTCUSDT","width": "100%","height": "100%","locale": "en","dateRange": "1M","colorTheme": "dark","isTransparent": true,"autosize": true,"largeChartUrl": ""}</script></div>
        <div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js" async>{"symbol": "TVC:DXY","width": "100%","height": "100%","locale": "en","dateRange": "1M","colorTheme": "dark","isTransparent": true,"autosize": true,"largeChartUrl": ""}</script></div>
        <div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js" async>{"symbol": "TVC:US10Y","width": "100%","height": "100%","locale": "en","dateRange": "1M","colorTheme": "dark","isTransparent": true,"autosize": true,"largeChartUrl": ""}</script></div>
    </div>"""

# --- 4. 計算與繪圖核心 ---
def process_ticker(t, app_data, bonus):
    try:
        df = yf.Ticker(t).history(period="1y", interval="1d")
        if df is None or len(df) < 50: return None
        
        # SMC 簡單計算
        close = df['Close'].iloc[-1]
        low_50 = df['Low'].tail(50).min()
        high_50 = df['High'].tail(50).max()
        
        # 簡單策略：在低位區 (Discount) 且有反彈
        is_discount = close < (low_50 + high_50) / 2
        score = 60 + bonus
        if is_discount: score += 20
        
        # 繪圖
        fig, ax = plt.subplots(figsize=(8, 5))
        fig.patch.set_facecolor('#1e293b')
        ax.set_facecolor('#1e293b')
        mpf.plot(df.tail(60), type='candle', style=mpf.make_mpf_style(base_mpf_style='nightclouds', gridcolor='#334155'), ax=ax, volume=False)
        ax.set_title(f"{t} Analysis", color='white')
        buf = BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', facecolor='#1e293b')
        plt.close(fig)
        img_str = f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
        
        # 數據包
        app_data[t] = {
            "score": score,
            "img": img_str,
            "entry": low_50,
            "sl": low_50 * 0.98,
            "signal": "LONG" if is_discount else "WAIT"
        }
        
        return {"ticker": t, "score": score, "signal": "LONG" if is_discount else "WAIT", "data": app_data[t]}
    except: return None

# --- 5. 主程式 ---
def main():
    print("🚀 Generating Site...")
    status, status_text, bonus = get_market_condition()
    macro = get_macro_html()
    news = get_polygon_news()
    
    app_data = {}
    results = []
    
    candidates = auto_select_candidates()
    for c in candidates:
        res = process_ticker(c['ticker'], app_data, bonus)
        if res: results.append(res)
            
    results.sort(key=lambda x: x['score'], reverse=True)
    
    # Discord Alert
    if DISCORD_WEBHOOK and results:
        top = [r for r in results if r['score'] >= 80][:3]
        if top:
            embeds = [{"title": f"🚀 {x['ticker']}", "description": f"Score: {x['score']}", "color": 5763717} for x in top]
            try: requests.post(DISCORD_WEBHOOK, json={"embeds": embeds})
            except: pass

    # HTML 生成
    json_data = json.dumps(app_data)
    
    # 生成 Top 5 HTML
    top_html = ""
    for r in results[:5]:
        top_html += f"<div class='card top-card' onclick=\"openModal('{r['ticker']}')\"><div>{r['ticker']}</div><div style='color:#10b981;font-weight:bold'>{r['score']}</div></div>"

    # 生成列表 HTML
    list_html = ""
    for r in results:
        badge = "<span class='badge long'>LONG</span>" if r['signal']=="LONG" else "<span class='badge wait'>WAIT</span>"
        list_html += f"<div class='card' onclick=\"openModal('{r['ticker']}')\"><div style='display:flex;justify-content:space-between'><b>{r['ticker']}</b>{badge}</div><div>Score: {r['score']}</div></div>"

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
        .top-card {{ text-align: center; font-size: 1.2rem; border-color: #fbbf24; }}
        .badge {{ padding: 2px 6px; border-radius: 4px; font-size: 0.8rem; }}
        .long {{ background: rgba(16,185,129,0.2); color: #10b981; border: 1px solid #10b981; }}
        .wait {{ background: rgba(148,163,184,0.2); color: #94a3b8; border: 1px solid #94a3b8; }}
        .modal {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); z-index: 99; padding: 20px; justify-content: center; overflow-y: auto; }}
        .modal-content {{ background: var(--card); padding: 20px; border-radius: 12px; max-width: 600px; width: 100%; margin-top: 50px; }}
        img {{ width: 100%; border-radius: 8px; }}
        @media (max-width: 600px) {{ .macro-grid, .top-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
    </style>
</head>
<body>
    <div style="margin-bottom:15px; border-left: 4px solid #10b981; background: #1e293b; padding: 10px;">
        <b>Market: {status}</b> <span style="font-size:0.8rem; color:#888">{status_text}</span>
    </div>

    {macro}

    <h3 style="color:#fbbf24">🏆 Top 5 Picks</h3>
    <div class="top-grid">{top_html}</div>

    <h3>📊 Watchlist</h3>
    <div class="grid">{list_html}</div>

    <h3>📰 News</h3>
    <div>{news}</div>
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
        const DATA = {json_data};
        let currentData = null;

        function openModal(t) {{
            const d = DATA[t];
            if(!d) return;
            currentData = d;
            document.getElementById('modal').style.display = 'flex';
            document.getElementById('m-title').innerText = t + " (" + d.signal + ")";
            document.getElementById('m-chart').innerHTML = '<img src="' + d.img + '">';
            calc();
        }}

        function calc() {{
            if(!currentData) return;
            const cap = parseFloat(document.getElementById('cap').value);
            const risk = cap * 0.01;
            const diff = currentData.entry - currentData.sl;
            if(cap > 0 && diff > 0) {{
                const shares = Math.floor(risk / diff);
                document.getElementById('res').innerText = shares + " Shares";
            }}
        }}
    </script>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f: f.write(final_html)
    print("✅ Index.html Generated!")

if __name__ == "__main__":
    main()
