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

# --- 1. 自動化選股核心 (Screener) ---

def get_sp500_tickers():
    """從 Wikipedia 抓取 S&P 500 成分股"""
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        tables = pd.read_html(url)
        df = tables[0]
        tickers = df['Symbol'].tolist()
        # 修正一些格式 (例如 BRK.B -> BRK-B)
        tickers = [t.replace('.', '-') for t in tickers]
        print(f"📋 已抓取 S&P 500 名單，共 {len(tickers)} 隻。")
        return tickers
    except Exception as e:
        print(f"❌ 無法抓取 S&P 500 名單: {e}")
        # 備用名單 (萬一爬蟲失敗)
        return ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "NFLX", "INTC"]

def calculate_beta(stock_returns, market_returns):
    """手動計算 Beta (速度快，不依賴 API info)"""
    if len(stock_returns) != len(market_returns):
        min_len = min(len(stock_returns), len(market_returns))
        stock_returns = stock_returns[-min_len:]
        market_returns = market_returns[-min_len:]
    
    covariance = np.cov(stock_returns, market_returns)[0][1]
    variance = np.var(market_returns)
    if variance == 0: return 0
    return covariance / variance

def auto_select_candidates():
    print("🚀 啟動超級篩選器 (Criteria: Cap>3B, Price>SMA200, Vol>900M, Beta>=1)...")
    
    # 1. 獲取候選池 (S&P 500)
    raw_tickers = get_sp500_tickers()
    
    # 為了節省時間，我們加上一些熱門成長股 (不在 S&P 500 裡的)
    growth_adds = ["PLTR", "SOFI", "COIN", "MARA", "MSTR", "HOOD", "DKNG", "RBLX", "U", "CVNA", "OPEN", "SHOP", "ARM", "SMCI"]
    full_list = list(set(raw_tickers + growth_adds))
    
    valid_tickers = []
    
    # 2. 抓取大盤數據 (用於計算 Beta 和 市場趨勢)
    spy = yf.Ticker("SPY").history(period="1y")
    spy_returns = spy['Close'].pct_change().dropna()
    
    # 3. 開始過濾
    # 由於 GitHub Actions 有時間限制，我們分批處理或限制數量
    # 但為了精準，我們快速掃描。為了加速，我們只抓必要的歷史數據。
    
    print(f"🔍 開始掃描 {len(full_list)} 隻股票...")
    
    for ticker in full_list:
        try:
            # 取得歷史數據 (只抓 1 年，足夠算 200MA 和 Beta)
            df = yf.Ticker(ticker).history(period="1y")
            if df is None or len(df) < 200: continue
            
            # --- 條件 A: 股價在 SMA 200 以上 ---
            close = df['Close'].iloc[-1]
            sma200 = df['Close'].rolling(200).mean().iloc[-1]
            if close < sma200: continue # 淘汰
            
            # --- 條件 B: 30天平均成交額 > 900M USD ---
            # 這是非常高的門檻，如果不夠多股票入選，建議調低到 300M
            avg_vol_30 = df['Volume'].tail(30).mean()
            avg_price_30 = df['Close'].tail(30).mean()
            dollar_volume = avg_vol_30 * avg_price_30
            
            if dollar_volume < 900_000_000: continue # 淘汰 (9億美金)
            
            # --- 條件 C: Beta >= 1 ---
            stock_returns = df['Close'].pct_change().dropna()
            beta = calculate_beta(stock_returns, spy_returns)
            if beta < 1.0: continue # 淘汰
            
            # --- 條件 D: 市值 > 3B ---
            # yfinance 的 fast_info 比較快
            try:
                # 稍微延遲一下避免被鎖
                market_cap = yf.Ticker(ticker).fast_info.market_cap
                if market_cap < 3_000_000_000: continue # 淘汰
            except:
                # 如果抓不到市值，但前面條件都過了，通常是大股票，暫時保留
                pass

            print(f"   ✅ {ticker} 入選! (Beta: {beta:.2f}, $Vol: {dollar_volume/1e6:.0f}M)")
            valid_tickers.append(ticker)
            
        except Exception as e:
            continue
            
    print(f"🏆 篩選完成! 共找到 {len(valid_tickers)} 隻符合條件的強勢股。")
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

# --- 8. 繪圖核心 ---
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
        plot_df = df.tail(60).copy()
        
        entry = float(entry) if not np.isnan(entry) else plot_df['Close'].iloc[-1]
        sl = float(sl) if not np.isnan(sl) else plot_df['Low'].min()
        tp = float(tp) if not np.isnan(tp) else plot_df['High'].max()

        mc = mpf.make_marketcolors(up='#10b981', down='#ef4444', edge='inherit', wick='inherit', volume='in')
        s  = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc, gridcolor='#1e293b', facecolor='#0f172a')
        
        fig, axlist = mpf.plot(plot_df, type='candle', style=s, volume=False,
            title=dict(title=f"{ticker} - {title}", color='white', size=10),
            figsize=(5, 3), returnfig=True)
        
        ax = axlist[0]
        x_min, x_max = ax.get_xlim()
        
        for i in range(2, len(plot_df)):
            idx = i - 1
            if plot_df['Low'].iloc[i] > plot_df['High'].iloc[i-2]: 
                bot, top = plot_df['High'].iloc[i-2], plot_df['Low'].iloc[i]
                rect = patches.Rectangle((idx, bot), x_max - idx, top - bot, linewidth=0, facecolor='#10b981', alpha=0.25)
                ax.add_patch(rect)
            elif plot_df['High'].iloc[i] < plot_df['Low'].iloc[i-2]:
                bot, top = plot_df['High'].iloc[i], plot_df['Low'].iloc[i-2]
                rect = patches.Rectangle((idx, bot), x_max - idx, top - bot, linewidth=0, facecolor='#ef4444', alpha=0.25)
                ax.add_patch(rect)

        if found_sweep:
            lowest = plot_df['Low'].min()
            ax.text(x_min + 2, lowest, "💧 SWEEP", color='#fbbf24', fontsize=12, fontweight='bold', va='bottom')

        line_style = ':' if is_wait else '-'
        ax.axhline(tp, color='#10b981', linestyle=line_style, linewidth=1)
        ax.axhline(entry, color='#3b82f6', linestyle=line_style, linewidth=1)
        ax.axhline(sl, color='#ef4444', linestyle=line_style, linewidth=1)
        
        ax.text(x_min, tp, " TP", color='#10b981', fontsize=8, va='bottom', fontweight='bold')
        ax.text(x_min, entry, " ENTRY", color='#3b82f6', fontsize=8, va='bottom', fontweight='bold')
        ax.text(x_min, sl, " SL", color='#ef4444', fontsize=8, va='top', fontweight='bold')

        if not is_wait:
            ax.add_patch(patches.Rectangle((x_min, entry), x_max-x_min, tp-entry, linewidth=0, facecolor='#10b981', alpha=0.1))
            ax.add_patch(patches.Rectangle((x_min, sl), x_max-x_min, entry-sl, linewidth=0, facecolor='#ef4444', alpha=0.1))

        buf = BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', transparent=True, dpi=80)
        plt.close(fig)
        buf.seek(0)
        return f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
    except: return create_error_image("Plot Error")

# --- 9. 單一股票處理 ---
def process_ticker(t, app_data_dict, market_bonus):
    try:
        # 自動選股已經過濾過了，這裡直接畫圖即可，不用再嚴格檢查
        df_d = fetch_data_safe(t, "1y", "1d")
        if df_d is None or len(df_d) < 50: return None
        df_h = fetch_data_safe(t, "1mo", "1h")
        if df_h is None or df_h.empty: df_h = df_d

        curr = float(df_d['Close'].iloc[-1])
        sma200 = float(df_d['Close'].rolling(200).mean().iloc[-1])
        if pd.isna(sma200): sma200 = curr

        bsl, ssl, eq, entry, sl, found_fvg, found_sweep = calculate_smc(df_d)
        tp = bsl

        is_bullish = curr > sma200
        in_discount = curr < eq
        signal = "LONG" if (is_bullish and in_discount and (found_fvg or found_sweep)) else "WAIT"
        
        indicators = calculate_indicators(df_d)
        score, reasons, rr, rvol, perf_30d, strategies = calculate_quality_score(df_d, entry, sl, tp, is_bullish, market_bonus, found_sweep, indicators)
        
        is_wait = (signal == "WAIT")
        img_d = generate_chart(df_d, t, "Daily SMC", entry, sl, tp, is_wait, found_sweep)
        img_h = generate_chart(df_h, t, "Hourly Entry", entry, sl, tp, is_wait, found_sweep)

        cls = "b-long" if signal == "LONG" else "b-wait"
        score_color = "#10b981" if score >= 85 else ("#3b82f6" if score >= 70 else "#fbbf24")
        
        elite_html = ""
        if score >= 85 or found_sweep or rvol > 1.5:
            reasons_html = "".join([f"<li>✅ {r}</li>" for r in reasons])
            
            confluence_text = ""
            if strategies >= 2:
                confluence_text = f"🔥 <b>策略共振：</b> 同時觸發 {strategies} 種訊號，可靠度極高。"
            
            sweep_text = ""
            if found_sweep:
                sweep_text = """
                <div style='margin-top:8px; padding:8px; background:rgba(251,191,36,0.1); border-left:3px solid #fbbf24; color:#fcd34d; font-size:0.85rem;'>
                    <b>⚠️ 偵測到流動性獵殺 (Sweep)：</b><br>
                    這是勝率最高的翻轉訊號。<br>
                    策略價值：讓你買在「別人止損」的地方，取得比單純 FVG 更好的入場價格。
                </div>
                """
            
            elite_html = f"""
            <div style='background:rgba(16,185,129,0.1); border:1px solid #10b981; padding:12px; border-radius:8px; margin:10px 0;'>
                <div style='font-weight:bold; color:#10b981; margin-bottom:5px;'>💎 AI 戰略分析 (Score {score})</div>
                <div style='font-size:0.85rem; color:#e2e8f0; margin-bottom:8px;'>{confluence_text}</div>
                <ul style='margin:0; padding-left:20px; font-size:0.8rem; color:#d1d5db;'>{reasons_html}</ul>
                {sweep_text}
            </div>
            """
        
        if signal == "LONG":
            ai_html = f"""
            <div class='deploy-box long'>
                <div class='deploy-title'>✅ LONG SETUP</div>
                <div style='display:flex;justify-content:space-between;border-bottom:1px solid #333;padding-bottom:5px;margin-bottom:5px;'>
                    <span>🏆 評分: <b style='color:{score_color};font-size:1.1em'>{score}</b></span>
                    <span>💰 RR: <b style='color:#10b981'>{rr:.1f}R</b></span>
                </div>
                <div style='font-size:0.8rem; color:#94a3b8; margin-bottom:5px;'>📈 近30日績效: {perf_30d:+.1f}%</div>
                {elite_html}
                <ul class='deploy-list' style='margin-top:10px'>
                    <li>TP: ${tp:.2f}</li><li>Entry: ${entry:.2f}</li><li>SL: ${sl:.2f}</li>
                </ul>
            </div>"""
        else:
            reason = "無FVG/Sweep" if (not found_fvg and not found_sweep) else ("逆勢" if not is_bullish else "溢價區")
            ai_html = f"<div class='deploy-box wait'><div class='deploy-title'>⏳ WAIT</div><div>評分: <b style='color:#94a3b8'>{score}</b></div><ul class='deploy-list'><li>狀態: {reason}</li><li>參考入場: ${entry:.2f}</li></ul></div>"
            
        app_data_dict[t] = {"signal": signal, "deploy": ai_html, "img_d": img_d, "img_h": img_h, "score": score}
        return {"ticker": t, "price": curr, "signal": signal, "cls": cls, "score": score, "rvol": rvol, "perf": perf_30d}
    except Exception as e:
        print(f"Err {t}: {e}")
        return None

# --- 10. 主程式 ---
def main():
    print("🚀 Starting Fully Automated Analysis (Advanced Filter)...")
    weekly_news_html = get_polygon_news()
    
    market_status, market_text, market_bonus = get_market_condition()
    market_color = "#10b981" if market_status == "BULLISH" else ("#ef4444" if market_status == "BEARISH" else "#fbbf24")
    
    APP_DATA, sector_html_blocks, screener_rows_list = {}, "", []

    # ==========================================
    # 🔥 1. 執行自動掃描 (符合 4 大條件)
    # ==========================================
    # 這裡的邏輯是：先海選出符合基本面和技術面(200MA, Beta)的股票
    auto_picked_tickers = auto_select_candidates()
    
    # 建立一個動態的板塊
    SECTORS_DYNAMIC = {
        "🔥 超級強勢股 (Filtered)": auto_picked_tickers
    }

    # ==========================================
    # 🔥 2. 處理板塊
    # ==========================================
    for sector, tickers in SECTORS_DYNAMIC.items():
        if not tickers: continue
        
        cards = ""
        sector_results = []
        
        for t in tickers:
            if t in APP_DATA:
                data = APP_DATA[t]
                sector_results.append({'ticker': t, 'score': data['score']})
            else:
                res = process_ticker(t, APP_DATA, market_bonus)
                if res:
                    if res['signal'] == "LONG":
                        screener_rows_list.append(res)
                    sector_results.append({'ticker': t, 'score': res['score']})
        
        sector_results.sort(key=lambda x: x['score'], reverse=True)
        
        for item in sector_results:
            t = item['ticker']
            if t not in APP_DATA: continue
            
            data = APP_DATA[t]
            signal = data['signal']
            score = data['score']
            cls = "b-long" if signal == "LONG" else "b-wait"
            s_color = "#10b981" if score >= 85 else ("#3b82f6" if score >= 70 else "#fbbf24")
            
            cards += f"<div class='card' onclick=\"openModal('{t}')\"><div class='head'><div><div class='code'>{t}</div></div><div style='text-align:right'><span class='badge {cls}'>{signal}</span><div style='margin-top:2px'><span style='font-size:0.7rem;color:{s_color}'>Score {score}</span></div></div></div></div>"
            
        if cards: sector_html_blocks += f"<h3 class='sector-title'>{sector}</h3><div class='grid'>{cards}</div>"

    seen = set()
    unique_screener = []
    for r in screener_rows_list:
        if r['ticker'] not in seen:
            unique_screener.append(r)
            seen.add(r['ticker'])
            
    unique_screener.sort(key=lambda x: x['score'], reverse=True)
    screener_html = ""
    for res in unique_screener:
        score_cls = "g" if res['score'] >= 85 else ""
        vol_fire = "🔥" if res['rvol'] > 1.5 else ""
        screener_html += f"<tr><td>{res['ticker']}</td><td>${res['price']:.2f}</td><td class='{score_cls}'><b>{res['score']}</b> {vol_fire}</td><td><span class='badge {res['cls']}'>{res['signal']}</span></td></tr>"

    json_data = json.dumps(APP_DATA)
    final_html = f"""
    <!DOCTYPE html>
    <html lang="zh-Hant">
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="icon" href="https://cdn-icons-png.flaticon.com/512/3310/3310624.png" type="image/png">
    <title>DailyDip Pro</title>
    <style>
    :root {{ --bg:#0f172a; --card:#1e293b; --text:#f8fafc; --acc:#3b82f6; --g:#10b981; --r:#ef4444; --y:#fbbf24; }}
    body {{ background:var(--bg); color:var(--text); font-family:sans-serif; margin:0; padding:10px; }}
    .tabs {{ display:flex; gap:10px; padding-bottom:10px; margin-bottom:15px; border-bottom:1px solid #333; overflow-x:auto; }}
    .tab {{ padding:8px 16px; background:#334155; border-radius:6px; cursor:pointer; font-weight:bold; font-size:0.9rem; white-space:nowrap; }}
    .tab.active {{ background:var(--acc); color:white; }}
    .content {{ display:none; }} .content.active {{ display:block; }}
    .sector-title {{ border-left:4px solid var(--acc); padding-left:10px; margin:20px 0 10px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; padding-bottom: 20px; }}
    .card {{ 
        background: rgba(30, 41, 59, 0.7); 
        backdrop-filter: blur(10px); 
        border: 1px solid rgba(255, 255, 255, 0.1); 
        border-radius: 12px; 
        padding: 12px; 
        cursor: pointer; 
        transition: transform 0.2s, box-shadow 0.2s; 
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
    }}
    .card:hover {{
        transform: translateY(-3px); 
        box-shadow: 0 10px 15px rgba(0, 0, 0, 0.5);
        border-color: var(--acc);
    }}
    .head {{ display:flex; justify-content:space-between; margin-bottom:5px; }}
    .code {{ font-weight:900; }} .price {{ color:#94a3b8; font-family:monospace; }}
    .badge {{ padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; letter-spacing: 0.5px; font-weight:bold; }}
    .b-long {{ background:rgba(16,185,129,0.2); color:var(--g); border:1px solid var(--g); }}
    .b-wait {{ background:rgba(148,163,184,0.1); color:#94a3b8; border:1px solid #555; }}
    table {{ width:100%; border-collapse:collapse; font-size:0.85rem; }}
    th, td {{ padding:8px; text-align:left; border-bottom:1px solid #333; }}
    .g {{ color:var(--g); font-weight:bold; }}
    .news-item {{ background:var(--card); border:1px solid #333; border-radius:8px; padding:15px; margin-bottom:10px; }}
    .news-title {{ color:var(--text); text-decoration:none; font-weight:bold; display:block; }}
    .modal {{ display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.95); z-index:99; justify-content:center; align-items:start; overflow-y:auto; padding:10px; }}
    .m-content {{ background:var(--card); width:100%; max-width:600px; padding:15px; border-radius:12px; margin-top:20px; border:1px solid #555; }}
    .m-content img {{ width:100%; border-radius:6px; margin-bottom:10px; }}
    .deploy-box {{ padding:15px; border-radius:8px; margin-bottom:15px; border-left:4px solid; }}
    .deploy-box.long {{ background:rgba(16,185,129,0.1); border-color:var(--g); }}
    .deploy-box.wait {{ background:rgba(251,191,36,0.1); border-color:var(--y); }}
    .close-btn {{ width:100%; padding:12px; background:var(--acc); border:none; color:white; border-radius:6px; font-weight:bold; margin-top:10px; cursor:pointer; }}
    .time {{ text-align:center; color:#666; font-size:0.7rem; margin-top:30px; }}
    .market-bar {{ background: #1e293b; padding: 10px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #333; display: flex; align-items: center; gap: 10px; }}
    </style>
    </head>
    <body>
        <div class="market-bar" style="border-left: 4px solid {market_color}">
            <div style="font-size:1.2rem;">{ "🟢" if market_status=="BULLISH" else ("🔴" if market_status=="BEARISH" else "🟡") }</div>
            <div>
                <div style="font-weight:bold; color:{market_color}">Market: {market_status}</div>
                <div style="font-size:0.8rem; color:#94a3b8">{market_text}</div>
            </div>
        </div>

        <div class="tabs">
            <div class="tab active" onclick="setTab('overview', this)">📊 市場概況</div>
            <div class="tab" onclick="setTab('screener', this)">🔍 強勢篩選 (LONG)</div>
            <div class="tab" onclick="setTab('news', this)">📰 News</div>
        </div>
        
        <div id="overview" class="content active">{sector_html_blocks if sector_html_blocks else '<div style="text-align:center;padding:50px">載入中...</div>'}</div>
        <div id="screener" class="content"><table><thead><tr><th>Ticker</th><th>Price</th><th>Score</th><th>Signal</th></tr></thead><tbody>{screener_html}</tbody></table></div>
        <div id="news" class="content">{weekly_news_html}</div>
        
        <div class="time">Updated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</div>

        <div id="modal" class="modal" onclick="document.getElementById('modal').style.display='none'">
            <div class="m-content" onclick="event.stopPropagation()">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                    <h2 id="m-ticker" style="margin:0; font-size:2rem;"></h2>
                    <div>
                        <button id="copy-btn" onclick="copyTicker()" style="background:#334155; border:1px solid #555; color:white; padding:5px 10px; border-radius:5px; cursor:pointer;">Copy Ticker</button>
                    </div>
                </div>
                <div id="m-deploy"></div>
                <div><b>Daily SMC</b><div id="chart-d"></div></div>
                <div><b>Hourly Entry</b><div id="chart-h"></div></div>
                <button class="close-btn" onclick="document.getElementById('modal').style.display='none'">Close</button>
            </div>
        </div>

        <script>
        const STOCK_DATA = {json_data};
        
        function setTab(id, el) {{
            document.querySelectorAll('.content').forEach(c => c.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.getElementById(id).classList.add('active');
            el.classList.add('active');
        }}

        function openModal(ticker) {{
            const data = STOCK_DATA[ticker];
            if (!data) return;
            document.getElementById('modal').style.display = 'flex';
            const tickerEl = document.getElementById('m-ticker');
            tickerEl.innerText = ticker;
            
            let btnContainer = tickerEl.parentNode.querySelector('div');
            let oldTvBtn = document.getElementById('tv-btn');
            if (oldTvBtn) oldTvBtn.remove();

            const newBtn = document.createElement('button');
            newBtn.id = 'tv-btn';
            newBtn.innerText = '📈 Chart';
            newBtn.style.cssText = 'margin-left:10px; background:#2962FF; border:none; color:white; padding:5px 12px; border-radius:5px; cursor:pointer; font-weight:bold;';
            newBtn.onclick = function() {{
                const currentTicker = document.getElementById('m-ticker').innerText;
                window.open('https://www.tradingview.com/chart/?symbol=' + currentTicker, '_blank');
            }};
            if(btnContainer) btnContainer.appendChild(newBtn);

            document.getElementById('m-deploy').innerHTML = data.deploy;
            document.getElementById('chart-d').innerHTML = '<img src="'+data.img_d+'">';
            document.getElementById('chart-h').innerHTML = '<img src="'+data.img_h+'">';
        }}

        function copyTicker() {{
            const ticker = document.getElementById('m-ticker').innerText;
            navigator.clipboard.writeText(ticker).then(() => {{
                const btn = document.getElementById('copy-btn');
                btn.innerText = 'Copied!';
                setTimeout(() => btn.innerText = 'Copy Ticker', 2000);
            }});
        }}
        </script>
    </body></html>
    """
    
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(final_html)
    print("✅ index.html generated!")

if __name__ == "__main__":
    main()
# --- END OF CODE ---
