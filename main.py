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
    growth_adds = ["PLTR", "SOFI", "COIN", "MARA", "MSTR", "HOOD", "DKNG", "RBLX", "U", "CVNA", "OPEN", "SHOP", "ARM", "SMCI", "APP", "RDDT", "HIMS", "ASTS", "IONQ"]
    full_list = list(set(raw_tickers + growth_adds))
    
    valid_tickers = []
    
    try:
        spy = yf.Ticker("SPY").history(period="1y")
        if spy.empty: return []
        spy_returns = spy['Close'].pct_change().dropna()
    except:
        return []
    
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
            if dollar_vol < 900_000_000: continue 
            
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

# --- 6. 評分系統 (修改：加入 Major/Minor Sweep 加分邏輯) ---
def calculate_quality_score(df, entry, sl, tp, is_bullish, market_bonus, sweep_type, indicators):
    try:
        score = 60 + market_bonus
        reasons = []
        rsi, rvol, golden_cross, trend, perf_30d = indicators
        
        strategies = 0
        
        # --- Sweep 評分邏輯修改 ---
        if sweep_type == "MAJOR":
            strategies += 1
            score += 25 # 強力獵殺加重分
            reasons.append("🌊 強力獵殺 (Major Sweep >20d)")
        elif sweep_type == "MINOR":
            strategies += 1
            score += 15 # 短線獵殺加分
            reasons.append("💧 短線獵殺 (Minor Sweep >10d)")
        # ------------------------

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

# --- 7. SMC 運算 (修改：區分 Major/Minor Sweep) ---
def calculate_smc(df):
    try:
        window = 50
        recent = df.tail(window)
        bsl = float(recent['High'].max())
        ssl_long = float(recent['Low'].min())
        
        eq = (bsl + ssl_long) / 2
        
        best_entry = eq
        found_fvg = False
        sweep_type = None # None, "MINOR", "MAJOR"
        
        last_3 = recent.tail(3)
        
        # 取得不包含最後 3 根 K 線的歷史數據，用來計算過去的低點
        prior_data = recent.iloc[:-3]
        
        # 計算 10日低點 和 20日低點
        low_10d = prior_data['Low'].tail(10).min()
        low_20d = prior_data['Low'].tail(20).min()
        
        for i in range(len(last_3)):
            candle = last_3.iloc[i]
            
            # 優先檢查是否跌破 20日低點 (Major)
            if candle['Low'] < low_20d and candle['Close'] > low_20d:
                sweep_type = "MAJOR"
                best_entry = low_20d # 獵殺點即入場點
                break # 找到最強訊號就停止
            
            # 再檢查是否跌破 10日低點 (Minor)
            elif candle['Low'] < low_10d and candle['Close'] > low_10d:
                # 只有還沒找到 Major 的時候才標記 Minor
                if sweep_type != "MAJOR":
                    sweep_type = "MINOR"
                    best_entry = low_10d
        
        # FVG 偵測
        for i in range(2, len(recent)):
            if recent['Low'].iloc[i] > recent['High'].iloc[i-2]:
                fvg = float(recent['Low'].iloc[i])
                if fvg < eq:
                    # 如果沒有發生 Sweep，才把 FVG 當作最佳入場
                    if not sweep_type: best_entry = fvg
                    found_fvg = True
                    break
                    
        return bsl, ssl_long, eq, best_entry, ssl_long*0.99, found_fvg, sweep_type
    except:
        last = float(df['Close'].iloc[-1])
        return last*1.05, last*0.95, last, last, last*0.94, False, None

# --- 8. 繪圖核心 (修改：根據 Sweep 類型顯示不同標籤) ---
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

def generate_chart(df, ticker, title, entry, sl, tp, is_wait, sweep_type):
    try:
        plt.close('all')
        if df is None or len(df) < 5: return create_error_image("No Data")
        
        plot_df = df.tail(80).copy()
        
        entry = float(entry) if not np.isnan(entry) else plot_df['Close'].iloc[-1]
        sl = float(sl) if not np.isnan(sl) else plot_df['Low'].min()
        tp = float(tp) if not np.isnan(tp) else plot_df['High'].max()

        mc = mpf.make_marketcolors(up='#10b981', down='#ef4444', edge='inherit', wick='inherit', volume={'up':'#1f2937', 'down':'#1f2937'})
        s  = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc, gridcolor='#1e293b', facecolor='#0f172a')
        
        fig, axlist = mpf.plot(plot_df, type='candle', style=s, volume=True, 
            mav=(50, 200), 
            title=dict(title=f"{ticker} - {title}", color='white', size=12, weight='bold'),
            figsize=(6, 4),
            panel_ratios=(7, 2), 
            scale_width_adjustment=dict(candle=1.2), 
            returnfig=True,
            tight_layout=True)
        
        ax = axlist[0]
        x_min, x_max = ax.get_xlim()
        
        for i in range(2, len(plot_df)):
            idx = i - 1
            if plot_df['Low'].iloc[i] > plot_df['High'].iloc[i-2]: 
                bot, top = plot_df['High'].iloc[i-2], plot_df['Low'].iloc[i]
                if (top - bot) > (plot_df['Close'].mean() * 0.002):
                    rect = patches.Rectangle((idx-0.4, bot), 10, top - bot, linewidth=0, facecolor='#10b981', alpha=0.15)
                    ax.add_patch(rect)
            elif plot_df['High'].iloc[i] < plot_df['Low'].iloc[i-2]:
                bot, top = plot_df['High'].iloc[i], plot_df['Low'].iloc[i-2]
                if (top - bot) > (plot_df['Close'].mean() * 0.002):
                    rect = patches.Rectangle((idx-0.4, bot), 10, top - bot, linewidth=0, facecolor='#ef4444', alpha=0.15)
                    ax.add_patch(rect)

        # --- Sweep 標記邏輯 ---
        if sweep_type:
            lowest = plot_df['Low'].min()
            
            if sweep_type == "MAJOR":
                label_text = "🌊 MAJOR SWEEP"
                label_color = "#ef4444" # 紅色
            else:
                label_text = "💧 MINOR SWEEP"
                label_color = "#fbbf24" # 黃色

            ax.annotate(label_text, xy=(x_max-3, lowest), xytext=(x_max-3, lowest*0.98),
                        arrowprops=dict(facecolor=label_color, shrink=0.05),
                        color=label_color, fontsize=9, fontweight='bold', ha='center')
        # --------------------

        line_style = ':' if is_wait else '-'
        ax.axhline(tp, color='#10b981', linestyle=line_style, linewidth=1, alpha=0.7)
        ax.axhline(entry, color='#3b82f6', linestyle=line_style, linewidth=1, alpha=0.9)
        ax.axhline(sl, color='#ef4444', linestyle=line_style, linewidth=1, alpha=0.7)
        
        ax.text(x_min, tp, " TP", color='#10b981', fontsize=8, va='bottom', fontweight='bold')
        ax.text(x_min, entry, " ENTRY", color='#3b82f6', fontsize=8, va='bottom', fontweight='bold')
        ax.text(x_min, sl, " SL", color='#ef4444', fontsize=8, va='top', fontweight='bold')

        if not is_wait:
            ax.add_patch(patches.Rectangle((x_min, entry), x_max-x_min, tp-entry, linewidth=0, facecolor='#10b981', alpha=0.05))
            ax.add_patch(patches.Rectangle((x_min, sl), x_max-x_min, entry-sl, linewidth=0, facecolor='#ef4444', alpha=0.05))

        buf = BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', transparent=True, dpi=90)
        plt.close(fig)
        buf.seek(0)
        return f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
    except Exception as e: 
        print(f"Plot Error: {e}")
        return create_error_image("Plot Error")

# --- 9. 單一股票處理 ---
def process_ticker(t, app_data_dict, market_bonus):
    try:
        df_d = fetch_data_safe(t, "1y", "1d")
        if df_d is None or len(df_d) < 50: return None
        df_h = fetch_data_safe(t, "1mo", "1h")
        if df_h is None or df_h.empty: df_h = df_d

        curr = float(df_d['Close'].iloc[-1])
        sma200 = float(df_d['Close'].rolling(200).mean().iloc[-1])
        if pd.isna(sma200): sma200 = curr

        # 這裡接收 sweep_type
        bsl, ssl, eq, entry, sl, found_fvg, sweep_type = calculate_smc(df_d)
        tp = bsl

        is_bullish = curr > sma200
        in_discount = curr < eq
        # 修改 Signal 判斷：只要有 Sweep (無論 Major/Minor) 或 FVG 就考慮
        signal = "LONG" if (is_bullish and in_discount and (found_fvg or sweep_type)) else "WAIT"
        
        indicators = calculate_indicators(df_d)
        # 傳入 sweep_type 給評分系統
        score, reasons, rr, rvol, perf_30d, strategies = calculate_quality_score(df_d, entry, sl, tp, is_bullish, market_bonus, sweep_type, indicators)
        
        is_wait = (signal == "WAIT")
        # 傳入 sweep_type 給繪圖系統
        img_d = generate_chart(df_d, t, "Daily SMC", entry, sl, tp, is_wait, sweep_type)
        img_h = generate_chart(df_h, t, "Hourly Entry", entry, sl, tp, is_wait, sweep_type)

        cls = "b-long" if signal == "LONG" else "b-wait"
        score_color = "#10b981" if score >= 85 else ("#3b82f6" if score >= 70 else "#fbbf24")
        
        elite_html = ""
        # 只要分數高，或有 Sweep，或爆量，就顯示詳細分析
        if score >= 85 or sweep_type or rvol > 1.5:
            reasons_html = "".join([f"<li>✅ {r}</li>" for r in reasons])
            confluence_text = f"🔥 <b>策略共振：</b> {strategies} 訊號" if strategies >= 2 else ""
            
            sweep_text = ""
            if sweep_type == "MAJOR":
                sweep_text = "<div style='margin-top:8px;padding:8px;background:rgba(239,68,68,0.1);border-left:3px solid #ef4444;color:#fca5a5;font-size:0.85rem;'><b>🌊 強力獵殺 (Major Sweep)</b><br>跌破20日低點後強勢收回，機構掃盤跡象明顯。</div>"
            elif sweep_type == "MINOR":
                sweep_text = "<div style='margin-top:8px;padding:8px;background:rgba(251,191,36,0.1);border-left:3px solid #fbbf24;color:#fcd34d;font-size:0.85rem;'><b>💧 短線獵殺 (Minor Sweep)</b><br>跌破10日低點後收回，短線資金進場。</div>"
            
            elite_html = f"""
            <div style='background:rgba(16,185,129,0.1);border:1px solid #10b981;padding:12px;border-radius:8px;margin:10px 0;'>
                <div style='font-weight:bold;color:#10b981;'>💎 AI 分析 (Score {score})</div>
                <div style='font-size:0.85rem;color:#e2e8f0;'>{confluence_text}</div>
                <ul style='margin:0;padding-left:20px;font-size:0.8rem;color:#d1d5db;'>{reasons_html}</ul>
                {sweep_text}
            </div>
            """
        
        if signal == "LONG":
            ai_html = f"""
            <div class='deploy-box long'>
                <div class='deploy-title'>✅ LONG SETUP</div>
                
                <div style='display:flex;justify-content:space-between;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,0.1);margin-bottom:10px;'>
                    <div style='text-align:center'>
                        <div style='font-size:0.75rem;color:#94a3b8'>Current</div>
                        <div style='font-size:1.1rem;font-weight:bold;color:#f8fafc'>${curr:.2f}</div>
                    </div>
                    <div style='text-align:center'>
                        <div style='font-size:0.75rem;color:#94a3b8'>Target (TP)</div>
                        <div style='font-size:1.1rem;font-weight:bold;color:#10b981'>${tp:.2f}</div>
                    </div>
                    <div style='text-align:center'>
                        <div style='font-size:0.75rem;color:#94a3b8'>R:R</div>
                        <div style='font-size:1.1rem;font-weight:bold;color:#fbbf24'>{rr:.1f}R</div>
                    </div>
                </div>

                {elite_html}
                <ul class='deploy-list'>
                    <li>Entry: ${entry:.2f}</li>
                    <li>SL: ${sl:.2f}</li>
                </ul>
            </div>"""
        else:
            reason = "無FVG/Sweep" if (not found_fvg and not sweep_type) else ("逆勢" if not is_bullish else "溢價區")
            ai_html = f"<div class='deploy-box wait'><div class='deploy-title'>⏳ WAIT</div><div>狀態: {reason}</div></div>"
            
        app_data_dict[t] = {"signal": signal, "deploy": ai_html, "img_d": img_d, "img_h": img_h, "score": score, "rvol": rvol}
        return {"ticker": t, "price": curr, "signal": signal, "cls": cls, "score": score, "rvol": rvol, "perf": perf_30d}
    except Exception as e:
        print(f"Err {t}: {e}")
        return None

# --- 10. 主程式 ---
def main():
    print("🚀 啟動超級篩選器 (Beta > 1, $Vol > 900M)...")
    weekly_news_html = get_polygon_news()
    market_status, market_text, market_bonus = get_market_condition()
    market_color = "#10b981" if market_status == "BULLISH" else ("#ef4444" if market_status == "BEARISH" else "#fbbf24")
    
    APP_DATA, sector_html_blocks, screener_rows_list = {}, "", []

    auto_picked_tickers = auto_select_candidates()
    SECTORS_DYNAMIC = {
        "🔥 超級強勢股 (Filtered)": auto_picked_tickers
    }

    for sector, tickers in SECTORS_DYNAMIC.items():
        if not tickers: 
            sector_html_blocks += f"<h3 class='sector-title'>{sector}</h3><div style='padding:20px'>今天沒有符合嚴格條件的股票 🤷‍♂️</div>"
            continue
            
        cards = ""
        sector_results = []
        for t in tickers:
            if t in APP_DATA:
                data = APP_DATA[t]
                sector_results.append({'ticker': t, 'score': data['score'], 'rvol': data.get('rvol', 0)})
            else:
                res = process_ticker(t, APP_DATA, market_bonus)
                if res:
                    if res['signal'] == "LONG": screener_rows_list.append(res)
                    sector_results.append({'ticker': t, 'score': res['score'], 'rvol': res['rvol']})
        
        sector_results.sort(key=lambda x: x['score'], reverse=True)
        for item in sector_results:
            t = item['ticker']
            if t not in APP_DATA: continue
            data = APP_DATA[t]
            
            rvol_val = item['rvol']
            rvol_str = f"Vol {rvol_val:.1f}x"
            rvol_html = f"<span style='color:#64748b;font-size:0.75rem'>{rvol_str}</span>"
            
            if rvol_val > 1.5:
                rvol_html = f"<span style='color:#f472b6;font-weight:bold;font-size:0.8rem'>{rvol_str} 🔥</span>"
            elif rvol_val > 1.2:
                rvol_html = f"<span style='color:#fbbf24;font-size:0.8rem'>{rvol_str} ⚡</span>"

            cards += f"<div class='card' onclick=\"openModal('{t}')\"><div class='head'><div><div class='code'>{t}</div></div><div style='text-align:right'><span class='badge {('b-long' if data['signal']=='LONG' else 'b-wait')}'>{data['signal']}</span></div></div><div style='display:flex;justify-content:space-between;align-items:center;margin-top:5px'><span style='font-size:0.8rem;color:{('#10b981' if item['score']>=85 else '#3b82f6')}'>Score {item['score']}</span>{rvol_html}</div></div>"
            
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
    final_html = f"""<!DOCTYPE html>
    <html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="https://cdn-icons-png.flaticon.com/512/3310/3310624.png"><title>DailyDip Pro</title>
    <style>:root {{ --bg:#0f172a; --card:#1e293b; --text:#f8fafc; --acc:#3b82f6; --g:#10b981; --r:#ef4444; --y:#fbbf24; }} body {{ background:var(--bg); color:var(--text); font-family:sans-serif; margin:0; padding:10px; }} .tabs {{ display:flex; gap:10px; overflow-x:auto; border-bottom:1px solid #333; padding-bottom:10px; }} .tab {{ padding:8px 16px; background:#334155; border-radius:6px; cursor:pointer; font-weight:bold; white-space:nowrap; }} .tab.active {{ background:var(--acc); }} .content {{ display:none; }} .content.active {{ display:block; }} .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:12px; }} .card {{ background:rgba(30,41,59,0.7); backdrop-filter:blur(10px); border:1px solid #333; border-radius:12px; padding:12px; cursor:pointer; }} .modal {{ display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.95); z-index:99; justify-content:center; overflow-y:auto; padding:10px; }} .m-content {{ background:var(--card); width:100%; max-width:600px; padding:15px; margin-top:20px; border-radius:12px; }} .sector-title {{ border-left:4px solid var(--acc); padding-left:10px; margin:20px 0 10px; }} table {{ width:100%; border-collapse:collapse; }} td, th {{ padding:8px; border-bottom:1px solid #333; text-align:left; }} .badge {{ padding:4px 8px; border-radius:6px; font-weight:bold; font-size:0.75rem; }} .b-long {{ color:var(--g); border:1px solid var(--g); background:rgba(16,185,129,0.2); }} .b-wait {{ color:#94a3b8; border:1px solid #555; }} .market-bar {{ background:#1e293b; padding:10px; border-radius:8px; margin-bottom:20px; display:flex; gap:10px; border:1px solid #333; }}</style></head>
    <body>
    <div class="market-bar" style="border-left:4px solid {market_color}"><div>{ "🟢" if market_status=="BULLISH" else "🔴" }</div><div><b>Market: {market_status}</b><div style="font-size:0.8rem;color:#94a3b8">{market_text}</div></div></div>
    <div class="tabs"><div class="tab active" onclick="setTab('overview',this)">📊 篩選結果</div><div class="tab" onclick="setTab('news',this)">📰 News</div></div>
    <div id="overview" class="content active">{sector_html_blocks}</div>
    <div id="news" class="content">{weekly_news_html}</div>
    <div style="text-align:center;color:#666;margin-top:30px;font-size:0.8rem">Updated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</div>
    
    <div id="modal" class="modal" onclick="this.style.display='none'">
        <div class="m-content" onclick="event.stopPropagation()">
            <div style="display:flex;justify-content:space-between;margin-bottom:15px;"><h2 id="m-ticker" style="margin:0"></h2><div id="btn-area"></div></div>
            <div id="m-deploy"></div><div><b>Daily</b><div id="chart-d"></div></div><div><b>Hourly</b><div id="chart-h"></div></div>
            <button onclick="document.getElementById('modal').style.display='none'" style="width:100%;padding:12px;background:var(--acc);border:none;color:white;border-radius:6px;margin-top:10px;">Close</button>
        </div>
    </div>

    <script>
    const DATA={json_data};
    function setTab(id,el){{document.querySelectorAll('.content').forEach(c=>c.classList.remove('active'));document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));document.getElementById(id).classList.add('active');el.classList.add('active');}}
    function openModal(t){{
        const d=DATA[t];if(!d)return;
        document.getElementById('modal').style.display='flex';
        document.getElementById('m-ticker').innerText=t;
        document.getElementById('m-deploy').innerHTML=d.deploy;
        document.getElementById('chart-d').innerHTML='<img src="'+d.img_d+'" style="width:100%;border-radius:6px">';
        document.getElementById('chart-h').innerHTML='<img src="'+d.img_h+'" style="width:100%;border-radius:6px">';
        
        const btnArea=document.getElementById('btn-area'); btnArea.innerHTML='';
        const tvBtn=document.createElement('button'); tvBtn.innerText='📈 Chart';
        tvBtn.style.cssText='background:#2962FF;border:none;color:white;padding:5px 12px;border-radius:5px;font-weight:bold;cursor:pointer';
        tvBtn.onclick=()=>window.open('https://www.tradingview.com/chart/?symbol='+t,'_blank');
        btnArea.appendChild(tvBtn);
    }}
    </script></body></html>"""
    
    with open("index.html", "w", encoding="utf-8") as f: f.write(final_html)
    print("✅ index.html generated!")

if __name__ == "__main__":
    main()
