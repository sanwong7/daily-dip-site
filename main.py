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
from collections import defaultdict

# ==================== 設定 ====================
API_KEY = os.environ.get("POLYGON_API_KEY")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")
HISTORY_FILE = "history.json"
BACKTEST_FILE = "backtest_results.json"

# ==================== 股票池 ====================
PRIORITY_TICKERS = ["TSLA", "AMZN", "NVDA", "AAPL", "MSFT", "GOOGL", "META", "AMD", "PLTR", "SOFI"]

STATIC_UNIVERSE = [
    "QCOM", "INTC", "MU", "AMAT", "LRCX", "ADI", "TXN", "KLAC", "MRVL", "ARM",
    "ORCL", "ADBE", "CRM", "INTU", "IBM", "NOW", "UBER", "ABNB", "PANW", "CRWD",
    "JPM", "V", "MA", "BAC", "WFC", "MS", "GS", "BLK", "PYPL",
    "WMT", "COST", "PG", "KO", "MCD", "SBUX", "NKE", "DIS", "HD",
    "LLY", "JNJ", "UNH", "ABBV", "TMO", "ISRG", "VRTX",
    "CAT", "DE", "GE", "HON", "XOM", "CVX",
    "TM", "F", "GM", "RIVN",
    "BABA", "PDD", "JD",
    "NFLX", "TMUS", "COIN", "MSTR"
]

SECTOR_MAP = {
    "Technology": "💻 科技與軟體",
    "Communication Services": "📡 通訊與媒體",
    "Consumer Cyclical": "🛍️ 非必需消費",
    "Consumer Defensive": "🛒 必需消費",
    "Financial Services": "🏦 金融服務",
    "Healthcare": "💊 醫療保健",
    "Energy": "🛢️ 能源",
    "Industrials": "🏭 工業",
    "Basic Materials": "🧱 原物料",
    "Real Estate": "🏠 房地產",
    "Utilities": "💡 公用事業"
}

# ==================== 歷史紀錄管理 ====================
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except: 
            return {}
    return {}

def save_history(history):
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=4)
    except Exception as e:
        print(f"❌ Failed to save history: {e}")

# ==================== 🔥 新增：Order Block 識別 ====================
def identify_order_blocks(df, lookback=30):
    """識別真正嘅 Order Block (機構訂單區)"""
    obs = []
    if len(df) < lookback + 5:
        return obs
    
    highs = df['High'].values
    lows = df['Low'].values
    closes = df['Close'].values
    opens = df['Open'].values
    volumes = df['Volume'].values
    
    for i in range(lookback, len(df)-1):
        # Bullish OB: 大陰線後出現強力反彈
        body_size = abs(closes[i] - opens[i])
        prev_body = abs(closes[i-1] - opens[i-1])
        
        # 陰線 + 放量
        is_bearish = closes[i] < opens[i]
        volume_spike = volumes[i] > np.mean(volumes[max(0, i-20):i]) * 1.3
        
        if is_bearish and body_size > prev_body * 0.8 and volume_spike:
            # 檢查之後係咪強力反彈
            if i+1 < len(closes):
                next_move = closes[i+1] - closes[i]
                if next_move > 0:  # 反彈
                    strength = next_move / body_size if body_size > 0 else 0
                    
                    if strength > 0.5:  # 反彈至少 50% 陰線幅度
                        obs.append({
                            'type': 'bullish',
                            'zone_low': lows[i],
                            'zone_high': min(opens[i], closes[i]),
                            'strength': strength,
                            'index': i,
                            'volume_ratio': volumes[i] / np.mean(volumes[max(0, i-20):i])
                        })
    
    # 保留最強嘅 5 個 OB
    obs.sort(key=lambda x: x['strength'] * x['volume_ratio'], reverse=True)
    return obs[:5]

# ==================== 🔥 新增：Market Structure Break 判斷 ====================
def detect_market_structure_break(df, lookback=50):
    """判斷市場結構突破 (BOS/CHoCH)"""
    if len(df) < lookback:
        return False, 0, "N/A"
    
    recent = df.tail(lookback)
    swing_highs = []
    swing_lows = []
    
    # 找出 Swing Points
    for i in range(2, len(recent)-2):
        if (recent['High'].iloc[i] > recent['High'].iloc[i-1] and 
            recent['High'].iloc[i] > recent['High'].iloc[i-2] and
            recent['High'].iloc[i] > recent['High'].iloc[i+1]):
            swing_highs.append((i, recent['High'].iloc[i]))
        
        if (recent['Low'].iloc[i] < recent['Low'].iloc[i-1] and 
            recent['Low'].iloc[i] < recent['Low'].iloc[i-2] and
            recent['Low'].iloc[i] < recent['Low'].iloc[i+1]):
            swing_lows.append((i, recent['Low'].iloc[i]))
    
    if len(swing_lows) < 2 or len(swing_highs) < 1:
        return False, 0, "Insufficient Data"
    
    # 檢查係咪上升趨勢 (Higher Lows)
    last_low = swing_lows[-1][1]
    prev_low = swing_lows[-2][1]
    
    if last_low > prev_low:
        # 檢查係咪破咗前高 (BOS)
        last_high = swing_highs[-1][1]
        current_price = recent['Close'].iloc[-1]
        
        if current_price > last_high:
            breakout_strength = (current_price - last_high) / last_high * 100
            return True, breakout_strength, "BOS (Break of Structure)"
    
    return False, 0, "No BOS"

# ==================== 🔥 新增：多時間框架確認 ====================
def multi_timeframe_confirmation(ticker):
    """檢查多個時間週期係咪一致看多"""
    try:
        scores = 0
        reasons = []
        
        # 4小時圖
        df_4h = yf.Ticker(ticker).history(period="3mo", interval="1h")
        if df_4h is not None and len(df_4h) > 50:
            sma20_4h = df_4h['Close'].rolling(20).mean().iloc[-1]
            if df_4h['Close'].iloc[-1] > sma20_4h:
                scores += 10
                reasons.append("⏰ 4H 趨勢確認")
        
        # 周線圖
        df_w = yf.Ticker(ticker).history(period="1y", interval="1wk")
        if df_w is not None and len(df_w) > 20:
            sma10_w = df_w['Close'].rolling(10).mean().iloc[-1]
            if df_w['Close'].iloc[-1] > sma10_w:
                scores += 15
                reasons.append("📅 周線看多")
        
        return scores, reasons
    except:
        return 0, []

# ==================== 🔥 改進：更精準嘅 Sweep 判斷 ====================
def calculate_smc_v2(df):
    """SMC 核心計算 - 優化版"""
    try:
        window = 50
        if len(df) < window:
            last = float(df['Close'].iloc[-1])
            return last*1.05, last*0.95, last, last, last*0.94, False, None
        
        recent = df.tail(window)
        bsl = float(recent['High'].max())
        ssl = float(recent['Low'].min())
        eq = (bsl + ssl) / 2
        
        # 找尋 Swing Lows
        swing_lows = []
        for i in range(5, len(recent)-2):
            if (recent['Low'].iloc[i] < recent['Low'].iloc[i-1] and
                recent['Low'].iloc[i] < recent['Low'].iloc[i-2] and
                recent['Low'].iloc[i] < recent['Low'].iloc[i+1]):
                swing_lows.append((i, recent['Low'].iloc[i]))
        
        if not swing_lows:
            return bsl, ssl, eq, eq, ssl*0.99, False, None
        
        # 檢查最近 5 根 K 線嘅 Sweep
        last_5 = recent.tail(5)
        sweep_type = None
        best_entry = eq
        last_swing = swing_lows[-1][1]
        
        for i in range(len(last_5)):
            candle = last_5.iloc[i]
            wick_length = abs(candle['Low'] - min(candle['Open'], candle['Close']))
            body_size = abs(candle['Close'] - candle['Open'])
            
            # 真正嘅 Sweep 條件：
            # 1. 破位
            # 2. 強力收回
            # 3. 長下影線
            # 4. 放量
            broke_low = candle['Low'] < last_swing
            closed_above = candle['Close'] > last_swing
            long_wick = wick_length > body_size * 1.2
            volume_confirm = candle['Volume'] > recent['Volume'].mean() * 1.15
            
            if broke_low and closed_above and long_wick and volume_confirm:
                sweep_type = "MAJOR"
                best_entry = last_swing * 1.003
                break
            elif broke_low and closed_above:
                if sweep_type != "MAJOR":
                    sweep_type = "MINOR"
                    best_entry = last_swing * 1.002
        
        # FVG 檢測（更嚴格）
        found_fvg = False
        avg_range = (recent['High'] - recent['Low']).tail(20).mean()
        
        for i in range(3, len(recent)):
            gap = recent['Low'].iloc[i] - recent['High'].iloc[i-2]
            if gap > avg_range * 0.3:  # Gap 夠大
                fvg_level = recent['High'].iloc[i-2]
                if fvg_level < eq and not sweep_type:
                    best_entry = fvg_level
                    found_fvg = True
                    break
        
        sl = ssl * 0.985  # SL 設在 SSL 下方 1.5%
        
        return bsl, ssl, eq, best_entry, sl, found_fvg, sweep_type
        
    except Exception as e:
        print(f"SMC Error: {e}")
        last = float(df['Close'].iloc[-1])
        return last*1.05, last*0.95, last, last, last*0.94, False, None

# ==================== 技術指標計算 ====================
def calculate_indicators(df):
    """計算技術指標"""
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    vol_ma = df['Volume'].rolling(20).mean()
    rvol = df['Volume'] / vol_ma
    
    sma50 = df['Close'].rolling(50).mean()
    sma200 = df['Close'].rolling(200).mean()
    
    golden_cross = False
    if len(sma50) > 5 and not pd.isna(sma50.iloc[-1]) and not pd.isna(sma200.iloc[-1]):
        if sma50.iloc[-1] > sma200.iloc[-1] and sma50.iloc[-5] <= sma200.iloc[-5]:
            golden_cross = True
    
    trend_bullish = sma50.iloc[-1] > sma200.iloc[-1] if len(sma200) > 0 else False
    
    if len(df) > 30:
        perf_30d = (df['Close'].iloc[-1] - df['Close'].iloc[-30]) / df['Close'].iloc[-30] * 100
    else:
        perf_30d = 0
    
    return rsi, rvol, golden_cross, trend_bullish, perf_30d

# ==================== 🔥 改進：動態評分系統 ====================
def calculate_advanced_score(ticker, df, entry, sl, tp, market_bonus, sweep_type, indicators):
    """更精準嘅評分系統"""
    try:
        score = 50 + market_bonus
        reasons = []
        confluence_count = 0
        
        rsi, rvol, golden_cross, trend, perf_30d = indicators
        
        # ===== 1. Order Block 確認 (+25分) =====
        obs = identify_order_blocks(df)
        if obs:
            closest_ob = min(obs, key=lambda x: abs(entry - x['zone_high']))
            distance_pct = abs(entry - closest_ob['zone_high']) / entry
            
            if distance_pct < 0.015:  # 1.5% 內
                bonus = int(25 * closest_ob['strength'])
                score += bonus
                confluence_count += 1
                reasons.append(f"💎 強力OB ({closest_ob['strength']:.2f}x 反彈)")
        
        # ===== 2. Market Structure Break (+20分) =====
        has_bos, bos_strength, bos_type = detect_market_structure_break(df)
        if has_bos:
            score += 20
            confluence_count += 1
            reasons.append(f"🔥 {bos_type} (+{bos_strength:.1f}%)")
        
        # ===== 3. 多時間框架確認 (+15分) =====
        mtf_score, mtf_reasons = multi_timeframe_confirmation(ticker)
        if mtf_score > 0:
            score += mtf_score
            confluence_count += 1
            reasons.extend(mtf_reasons)
        
        # ===== 4. Volume 分析 (改進) =====
        curr_rvol = rvol.iloc[-1] if not pd.isna(rvol.iloc[-1]) else 1.0
        recent_vol_trend = rvol.tail(5).mean()
        
        if curr_rvol > 2.5:
            score += 20
            confluence_count += 1
            reasons.append(f"🚀 爆量 ({curr_rvol:.1f}x)")
        elif curr_rvol > 1.8:
            score += 15
            confluence_count += 1
            reasons.append(f"📊 強量 ({curr_rvol:.1f}x)")
        elif curr_rvol > 1.3:
            score += 8
            reasons.append(f"📊 放量 ({curr_rvol:.1f}x)")
        
        # 持續放量加分
        if recent_vol_trend > 1.5:
            score += 5
            reasons.append("🔥 持續放量")
        
        # ===== 5. Sweep 確認 (+20分) =====
        if sweep_type == "MAJOR":
            score += 25
            confluence_count += 1
            reasons.append("🌊 Major Sweep (強力獵殺)")
        elif sweep_type == "MINOR":
            score += 12
            reasons.append("💧 Minor Sweep")
        
        # ===== 6. R:R 分析（更嚴格）=====
        risk = entry - sl
        reward = tp - entry
        rr = reward / risk if risk > 0 else 0
        
        if rr >= 4.0:
            score += 20
            confluence_count += 1
            reasons.append(f"💰 超高R:R ({rr:.1f})")
        elif rr >= 3.0:
            score += 15
            reasons.append(f"💰 優秀R:R ({rr:.1f})")
        elif rr >= 2.5:
            score += 8
            reasons.append(f"💵 良好R:R ({rr:.1f})")
        elif rr < 2.0:
            score -= 15
            reasons.append(f"⚠️ R:R不足 ({rr:.1f})")
        
        # ===== 7. RSI 完美區間 =====
        curr_rsi = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50
        
        if 35 <= curr_rsi <= 45:
            score += 18
            confluence_count += 1
            reasons.append(f"🎯 RSI黃金區 ({int(curr_rsi)})")
        elif 45 < curr_rsi <= 55:
            score += 10
            reasons.append(f"📉 RSI中性 ({int(curr_rsi)})")
        elif curr_rsi < 30:
            score += 8
            reasons.append(f"⚠️ RSI超賣 ({int(curr_rsi)})")
        elif curr_rsi > 70:
            score -= 20
            reasons.append(f"🔴 RSI超買 ({int(curr_rsi)})")
        elif curr_rsi > 65:
            score -= 10
        
        # ===== 8. 價格與入場點距離 =====
        curr_price = df['Close'].iloc[-1]
        dist_pct = abs(curr_price - entry) / entry
        
        if dist_pct < 0.008:  # 0.8% 內
            score += 18
            reasons.append("🎯 完美狙擊點")
        elif dist_pct < 0.02:
            score += 10
            reasons.append("✅ 入場點接近")
        elif dist_pct > 0.05:
            score -= 12
            reasons.append(f"⚠️ 入場點太遠 ({dist_pct*100:.1f}%)")
        
        # ===== 9. 趨勢確認 =====
        if trend:
            score += 8
            reasons.append("📈 長期趨勢向上")
        
        if golden_cross:
            score += 12
            confluence_count += 1
            reasons.append("✨ 黃金交叉")
        
        # ===== 10. 動能分析（新增）=====
        if len(df) > 5:
            recent_momentum = (df['Close'].iloc[-1] - df['Close'].iloc[-5]) / df['Close'].iloc[-5] * 100
            if recent_momentum > 3:
                score += 10
                reasons.append(f"⚡ 強勁動能 (+{recent_momentum:.1f}%)")
            elif recent_momentum < -5:
                score -= 8
                reasons.append(f"📉 動能轉弱 ({recent_momentum:.1f}%)")
        
        # ===== 11. 市場狀態調整 =====
        if market_bonus > 0:
            reasons.append("🌍 大盤順風 (+5)")
        elif market_bonus < 0:
            reasons.append("⚠️ 大盤逆風 (-10)")
        
        # ===== 12. 策略共振獎勵 =====
        if confluence_count >= 4:
            score += 15
            reasons.append(f"🔥 {confluence_count}個強勢共振")
        elif confluence_count >= 3:
            score += 8
        
        return max(int(score), 0), reasons, rr, curr_rvol, perf_30d, confluence_count
        
    except Exception as e:
        print(f"Scoring Error: {e}")
        return 50, ["❌ 評分錯誤"], 0, 1.0, 0, 0

# ==================== 🔥 完整回測系統 ====================
def comprehensive_backtest(ticker, lookback_days=180, holding_days=5):
    """完整回測單一股票策略表現"""
    try:
        print(f"📊 回測 {ticker}...")
        
        # 取得歷史數據
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days + 60)
        df = yf.Ticker(ticker).history(start=start_date, end=end_date, interval="1d")
        
        if df is None or len(df) < 100:
            return None
        
        trades = []
        equity_curve = [10000]  # 起始資金
        current_equity = 10000
        
        # 模擬每10天生成一次訊號
        for i in range(60, len(df) - holding_days, 10):
            historical_df = df.iloc[:i+1]
            
            # 執行 SMC 策略
            bsl, ssl, eq, entry, sl, found_fvg, sweep_type = calculate_smc_v2(historical_df)
            
            # 檢查入場條件
            curr_price = historical_df['Close'].iloc[-1]
            sma200 = historical_df['Close'].rolling(200).mean().iloc[-1]
            
            if pd.isna(sma200):
                continue
            
            is_bullish = curr_price > sma200
            in_discount = curr_price < eq
            
            # 必須符合基本條件
            if not (is_bullish and in_discount and (found_fvg or sweep_type)):
                continue
            
            # 計算指標
            indicators = calculate_indicators(historical_df)
            
            # 計算評分（用舊的市場狀態作參考）
            score, reasons, rr, rvol, perf_30d, conf = calculate_advanced_score(
                ticker, historical_df, entry, sl, bsl, 0, sweep_type, indicators
            )
            
            # 只取高分訊號
            if score < 75:
                continue
            
            # 模擬入場
            entry_price = curr_price  # 假設以當前價入場
            sl_price = sl
            tp_price = bsl
            
            # 風險管理：每次risque 1%
            risk_amount = current_equity * 0.01
            risk_per_share = entry_price - sl_price
            
            if risk_per_share <= 0:
                continue
            
            position_size = int(risk_amount / risk_per_share)
            if position_size <= 0:
                continue
            
            # 檢查後續價格走勢
            future_df = df.iloc[i+1:i+1+holding_days]
            
            if len(future_df) == 0:
                continue
            
            hit_sl = (future_df['Low'] <= sl_price).any()
            hit_tp = (future_df['High'] >= tp_price).any()
            
            # 判斷結果
            exit_price = entry_price
            result = "OPEN"
            pnl = 0
            
            if hit_sl and hit_tp:
                # 兩個都打到，睇邊個先
                sl_day = future_df[future_df['Low'] <= sl_price].index[0]
                tp_day = future_df[future_df['High'] >= tp_price].index[0]
                
                if sl_day < tp_day:
                    result = "LOSS"
                    exit_price = sl_price
                else:
                    result = "WIN"
                    exit_price = tp_price
            elif hit_sl:
                result = "LOSS"
                exit_price = sl_price
            elif hit_tp:
                result = "WIN"
                exit_price = tp_price
            else:
                # 持有期結束仍未觸及，以最後價格平倉
                exit_price = future_df['Close'].iloc[-1]
                if exit_price > entry_price:
                    result = "WIN"
                else:
                    result = "LOSS"
            
            # 計算損益
            pnl = (exit_price - entry_price) * position_size
            current_equity += pnl
            equity_curve.append(current_equity)
            
            trades.append({
                'date': historical_df.index[-1].strftime('%Y-%m-%d'),
                'ticker': ticker,
                'entry': entry_price,
                'sl': sl_price,
                'tp': tp_price,
                'exit': exit_price,
                'shares': position_size,
                'result': result,
                'pnl': pnl,
                'score': score,
                'rr': rr,
                'sweep': sweep_type or "FVG"
            })
        
        if len(trades) == 0:
            return None
        
        # 計算統計數據
        wins = [t for t in trades if t['result'] == 'WIN']
        losses = [t for t in trades if t['result'] == 'LOSS']
        
        total_trades = len(trades)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
        
        total_pnl = sum([t['pnl'] for t in trades])
        avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['pnl'] for t in losses]) if losses else 0
        
        profit_factor = abs(sum([t['pnl'] for t in wins]) / sum([t['pnl'] for t in losses])) if losses and sum([t['pnl'] for t in losses]) != 0 else 0
        
        # 計算最大回撤
        peak = equity_curve[0]
        max_dd = 0
        for val in equity_curve:
            if val > peak:
                peak = val
            dd = (peak - val) / peak * 100
            if dd > max_dd:
                max_dd = dd
        
        return {
            'ticker': ticker,
            'total_trades': total_trades,
            'wins': win_count,
            'losses': loss_count,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'final_equity': current_equity,
            'return_pct': (current_equity - 10000) / 10000 * 100,
            'max_drawdown': max_dd,
            'trades': trades,
            'equity_curve': equity_curve
        }
        
    except Exception as e:
        print(f"❌ Backtest error for {ticker}: {e}")
        return None

def run_portfolio_backtest(tickers, lookback_days=180):
    """批量回測多隻股票"""
    print("=" * 60)
    print("🚀 開始完整回測系統")
    print("=" * 60)
    
    results = []
    
    for ticker in tickers:
        result = comprehensive_backtest(ticker, lookback_days)
        if result:
            results.append(result)
        time.sleep(0.5)  # 避免 API 限制
    
    if not results:
        print("❌ 無回測結果")
        return None
    
    # 儲存詳細結果
    with open(BACKTEST_FILE, 'w') as f:
        json.dump(results, f, indent=4)
    
    # 生成報告
    generate_backtest_report(results)
    
    return results

def generate_backtest_report(results):
    """生成回測報告"""
    print("\n" + "=" * 60)
    print("📊 回測報告")
    print("=" * 60)
    
    # 整體統計
    total_trades = sum([r['total_trades'] for r in results])
    total_wins = sum([r['wins'] for r in results])
    total_losses = sum([r['losses'] for r in results])
    
    overall_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    
    avg_return = np.mean([r['return_pct'] for r in results])
    best_stock = max(results, key=lambda x: x['return
