import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

# ---------------------------------------------------------
# 1. PAGE CONFIGURATION & STYLING
# ---------------------------------------------------------
st.set_page_config(
    page_title="Multi-Timeframe Trading",
    page_icon="⚡",
    layout="wide"
)

st.markdown("""
<style>
div[data-testid="stMetricValue"] {
    font-size: 1.2rem !important;
    font-weight: 700 !important;
}
div[data-testid="stMetricLabel"] {
    font-size: 0.85rem !important;
    font-weight: 600 !important;
}
</style>
""", unsafe_allow_html=True)

st.title("⚡Equity Trading Dashboard")

# ---------------------------------------------------------
# 2. TOP BENCHMARK INDICES BAR
# ---------------------------------------------------------
@st.cache_data(ttl=300)
def fetch_index_data():
    indices = {
        "NIFTY 50": "^NSEI",
        "BANK NIFTY": "^NSEBANK",
        "SENSEX": "^BSESN",
        "NIFTY MIDCAP": "^NSEMDCP50"
    }
    index_results = {}
    for name, ticker in indices.items():
        try:
            data = yf.Ticker(ticker).history(period="5d")
            if len(data) >= 2:
                last_price = float(data['Close'].iloc[-1])
                prev_price = float(data['Close'].iloc[-2])
                change_pts = last_price - prev_price
                change_pct = (change_pts / prev_price) * 100
                index_results[name] = (last_price, change_pts, change_pct)
        except Exception:
            continue
    return index_results

indices_data = fetch_index_data()
if indices_data:
    cols = st.columns(len(indices_data))
    for i, (name, (price,pts,pct)) in enumerate(indices_data.items()):
        with cols[i].container(border=True):
            delta_str= f"{pts:+,.2f} ({pct:+.2f}%)"
            st.metric(label=name, value=f"{price:,.2f}", delta=delta_str)

st.markdown("---")

# ---------------------------------------------------------
# 3. DATABASE LOADER & SIDEBAR CONTROLS
# ---------------------------------------------------------
DB_NAME = "trade_lifecycle.db"

def load_data(table_name, status_filter=None):
    try:
        conn = sqlite3.connect(DB_NAME)
        query = f"SELECT * FROM {table_name}"
        if status_filter:
            query += f" WHERE status = '{status_filter}'"
        df = pd.read_sql(query, conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

st.sidebar.header("Workstation Controls")
if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("Admin Scanner Execution")
if st.sidebar.button("⚡ Run Screener Now (Cloud / Local)", use_container_width=True):
    with st.spinner("Running screener engine across market universe..."):
        try:
            import screener_engine
            screener_engine.run_screener()
            st.cache_data.clear()
            st.sidebar.success("Database scanned and updated successfully!")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"Screener execution error: {e}")

# ---------------------------------------------------------
# 4. COLOR-CODING & NUMBER FORMATTING STYLER
# ---------------------------------------------------------
# ---------------------------------------------------------
# 4. COLOR-CODING, NUMBER FORMATTING & LIVE CMP INJECTION
# ---------------------------------------------------------
def style_dataframe(df):
    """Replaces RSI with live Current Market Price (CMP) and formats rows with live P&L."""
    if df.empty:
        return df

    df_styled = df.copy()

    # 1. Fallback for Intraday Hub 1D Change
    if '1D_Change_%' not in df_styled.columns and 'entry' in df_styled.columns and 'vwap' in df_styled.columns:
        df_styled['1D_Change_%'] = ((df_styled['entry'] - df_styled['vwap']) / df_styled['vwap']) * 100

    # 2. Add 'current_price' Column & Calculate Dynamic P&L
    df_styled['current_price'] = df_styled.get('entry', 0.0)

    if 'status' in df_styled.columns and 'symbol' in df_styled.columns:
        active_mask = (df_styled['status'] == 'ACTIVE') & df_styled['symbol'].notna()
        
        for idx in df_styled[active_mask].index:
            try:
                sym = str(df_styled.loc[idx, 'symbol']).strip()
                sym_ticker = f"{sym}.NS" if not sym.endswith(".NS") else sym
                entry_price = float(df_styled.loc[idx, 'entry']) if 'entry' in df_styled.columns else 0.0

                t_data = yf.Ticker(sym_ticker).history(period="5d")
                if len(t_data) >= 1:
                    curr_price = float(t_data['Close'].iloc[-1])
                    df_styled.loc[idx, 'current_price'] = curr_price

                    if 'return_pct' in df_styled.columns and entry_price > 0:
                        pnl_pct = ((curr_price - entry_price) / entry_price) * 100
                        if abs(pnl_pct) < 0.01 and len(t_data) >= 2:
                            prev_close = float(t_data['Close'].iloc[-2])
                            pnl_pct = ((curr_price - prev_close) / prev_close) * 100
                        df_styled.loc[idx, 'return_pct'] = round(pnl_pct, 2)
            except Exception:
                continue

    # 3. Drop the redundant RSI column if present
    if 'rsi' in df_styled.columns:
        df_styled = df_styled.drop(columns=['rsi'])

    # 4. Reorder Columns to place current_price cleanly next to entry
    cols = list(df_styled.columns)
    if 'current_price' in cols and 'entry' in cols:
        cols.remove('current_price')
        entry_pos = cols.index('entry')
        cols.insert(entry_pos + 1, 'current_price')
        df_styled = df_styled[cols]

    # 5. Row Color Highlights
    def color_rows(row):
        val = row.get("1D_Change_%", row.get("return_pct", None))
        if pd.notna(val):
            if val > 0:
                return ['background-color: #d4edda; color: #155724; font-weight: bold'] * len(row)
            elif val < 0:
                return ['background-color: #f8d7da; color: #721c24; font-weight: bold'] * len(row)
            else:
                return ['background-color: #d4edda; color: #155724; font-weight: bold'] * len(row)
        return [''] * len(row)

    # 6. Formatters
    def fmt_currency(val):
        return f"₹{val:,.2f}" if pd.notna(val) else "-"

    def fmt_pct(val):
        return f"{val:+.2f}%" if pd.notna(val) else "-"

    format_dict = {
        "entry": fmt_currency,
        "current_price": fmt_currency,
        "target": fmt_currency,
        "stop_loss": fmt_currency,
        "vwap": fmt_currency,
        "exit_price": fmt_currency,
        "sma_200": fmt_currency,
        "1D_Change_%": fmt_pct,
        "return_pct": fmt_pct
    }

    active_formats = {k: v for k, v in format_dict.items() if k in df_styled.columns}
    return df_styled.style.apply(color_rows, axis=1).format(active_formats)
# ---------------------------------------------------------
# 5. FUNDAMENTALS & SUMMARY FETCH ENGINE
# ---------------------------------------------------------
@st.cache_data(ttl=1800)
def fetch_stock_info(symbol):
    """Fetches fundamental metrics and summary reliably across cloud and local runtimes."""
    ticker_sym = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
    try:
        ticker = yf.Ticker(ticker_sym)
        fast = getattr(ticker, 'fast_info', {})
        mcap = getattr(fast, 'market_cap', None)
        high52 = getattr(fast, 'year_high', None)
        low52 = getattr(fast, 'year_low', None)
        
        info = {}
        try:
            info = ticker.info or {}
        except Exception:
            pass

        mcap_val = mcap if mcap else info.get('marketCap')
        mcap_str = f"₹{mcap_val / 1e7:,.2f} Cr" if mcap_val else "N/A"

        high52_val = high52 if high52 else info.get('fiftyTwoWeekHigh')
        high52_str = f"₹{high52_val:,.2f}" if high52_val else "N/A"

        low52_val = low52 if low52 else info.get('fiftyTwoWeekLow')
        low52_str = f"₹{low52_val:,.2f}" if low52_val else "N/A"

        fundamentals = {
            "Company Name": info.get("longName", symbol),
            "Sector": info.get("sector", "N/A"),
            "Industry": info.get("industry", "N/A"),
            "Market Cap": mcap_str,
            "Trailing P/E": f"{info.get('trailingPE', 0):.2f}" if info.get('trailingPE') else "N/A",
            "Forward P/E": f"{info.get('forwardPE', 0):.2f}" if info.get('forwardPE') else "N/A",
            "EPS (TTM)": f"₹{info.get('trailingEps', 0):.2f}" if info.get('trailingEps') else "N/A",
            "52 Week High": high52_str,
            "52 Week Low": low52_str,
            "PB Ratio": f"{info.get('priceToBook', 0):.2f}" if info.get('priceToBook') else "N/A",
            "Dividend Yield": f"{info.get('dividendYield', 0)*100:.2f}%" if info.get('dividendYield') else "0.00%",
            "ROE": f"{info.get('returnOnEquity', 0)*100:.2f}%" if info.get('returnOnEquity') else "N/A"
        }
        
        summary_text = info.get("longBusinessSummary", "Company description temporarily rate-limited by data provider. Price and technical feeds remain fully operational.")
        return fundamentals, summary_text
    except Exception:
        return {}, "Could not load metrics at this time."

# ---------------------------------------------------------
# 6. PLOTLY CANDLESTICK & TECHNICAL CHART ENGINE
# ---------------------------------------------------------
def render_stock_chart(symbol, selected_tf="1M", active_indicators=[]):
    """Renders Plotly candlestick chart with technical indicators."""
    ticker_sym = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
    tf_map = {
        "1D": ("1d", "5m"), "5D": ("5d", "15m"), 
        "1M": ("1mo", "1d"), "6M": ("6mo", "1d"), "1Y": ("1y", "1d")
    }
    period, interval = tf_map.get(selected_tf, ("1mo", "1d"))

    try:
        data = yf.download(ticker_sym, period=period, interval=interval, progress=False)
        if data.empty:
            st.warning("Chart data unavailable.")
            return

        if isinstance(data.columns, pd.MultiIndex):
            data = data.xs(ticker_sym, level=1, axis=1)

        has_rsi = "RSI (14)" in active_indicators
        has_macd = "MACD" in active_indicators
        rows = 2 if (has_rsi or has_macd) else 1
        
        fig = make_subplots(
            rows=rows, cols=1, 
            shared_xaxes=True, 
            vertical_spacing=0.08, 
            row_heights=[0.7, 0.3] if rows == 2 else [1.0]
        )
        
        fig.add_trace(go.Candlestick(
            x=data.index, open=data['Open'], high=data['High'], 
            low=data['Low'], close=data['Close'], name="Price"
        ), row=1, col=1)

        if "20 SMA" in active_indicators:
            fig.add_trace(go.Scatter(x=data.index, y=data['Close'].rolling(20).mean(), line=dict(color='orange', width=1.5), name="20 SMA"), row=1, col=1)
        if "50 SMA" in active_indicators:
            fig.add_trace(go.Scatter(x=data.index, y=data['Close'].rolling(50).mean(), line=dict(color='blue', width=1.5), name="50 SMA"), row=1, col=1)
        if "200 SMA" in active_indicators:
            fig.add_trace(go.Scatter(x=data.index, y=data['Close'].rolling(200).mean(), line=dict(color='purple', width=2), name="200 SMA"), row=1, col=1)
        if "VWAP" in active_indicators:
            tp = (data['High'] + data['Low'] + data['Close']) / 3
            data['VWAP'] = (tp * data['Volume']).cumsum() / data['Volume'].cumsum()
            fig.add_trace(go.Scatter(x=data.index, y=data['VWAP'], line=dict(color='cyan', width=1.5, dash='dash'), name="VWAP"), row=1, col=1)

        if has_rsi:
            delta = data['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            fig.add_trace(go.Scatter(x=data.index, y=100 - (100 / (1 + rs)), line=dict(color='magenta', width=1.5), name="RSI (14)"), row=2, col=1)
            fig.add_hline(y=70, line=dict(color='red', dash='dash'), row=2, col=1)
            fig.add_hline(y=30, line=dict(color='green', dash='dash'), row=2, col=1)

        if has_macd and not has_rsi:
            exp1 = data['Close'].ewm(span=12, adjust=False).mean()
            exp2 = data['Close'].ewm(span=26, adjust=False).mean()
            macd = exp1 - exp2
            signal = macd.ewm(span=9, adjust=False).mean()
            fig.add_trace(go.Scatter(x=data.index, y=macd, line=dict(color='blue', width=1.5), name="MACD"), row=2, col=1)
            fig.add_trace(go.Scatter(x=data.index, y=signal, line=dict(color='orange', width=1.5), name="Signal"), row=2, col=1)

        fig.update_layout(
            xaxis_rangeslider_visible=False, 
            height=450, 
            template="plotly_dark", 
            margin=dict(l=10, r=10, t=30, b=10)
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Chart render error: {e}")

# ---------------------------------------------------------
# 7. RISK & POSITION SIZING CALCULATOR ENGINE
# ---------------------------------------------------------
# ---------------------------------------------------------
# RISK & POSITION SIZING CALCULATOR ENGINE
# ---------------------------------------------------------
def render_risk_calculator(symbol, entry_price, target_price, stop_loss_price):
    """Calculates position sizing capped strictly by available account capital and risk rules."""
    st.markdown("#### 🧮 Position Size & Risk Calculator")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        total_capital = st.number_input(
            "Total Trading Capital (₹)", 
            min_value=100.0, 
            value=10000.0, 
            step=1000.0, 
            key=f"cap_{symbol}"
        )
    with col2:
        risk_pct = st.slider(
            "Max Risk Per Trade (%)", 
            min_value=0.25, 
            max_value=5.0, 
            value=2.0, 
            step=0.25, 
            key=f"risk_pct_{symbol}"
        )
    with col3:
        leverage = st.selectbox(
            "Product Type / Margin", 
            ["1x (Cash CNC / Swing)", "5x (Intraday MIS)"], 
            key=f"lev_{symbol}"
        )

    # 1. Price Deltas
    per_share_risk = abs(entry_price - stop_loss_price)
    per_share_reward = abs(target_price - entry_price)
    
    if per_share_risk > 0 and entry_price > 0:
        margin_multiplier = 5.0 if "5x" in leverage else 1.0
        max_purchasing_power = total_capital * margin_multiplier
        
        # Max quantity allowed by risk limit
        risk_amount = total_capital * (risk_pct / 100.0)
        risk_qty = int(risk_amount // per_share_risk)
        
        # Max quantity allowed by capital limit
        capital_qty = int(max_purchasing_power // entry_price)
        
        # Take the stricter limit
        allowed_qty = min(risk_qty, capital_qty)
        
        # Final Metrics
        position_value = allowed_qty * entry_price
        required_capital = position_value / margin_multiplier
        rr_ratio = per_share_reward / per_share_risk
        actual_risk_amount = allowed_qty * per_share_risk
        actual_profit_amount = allowed_qty * per_share_reward

        # Display Metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Recommended Qty", f"{allowed_qty:,} shares")
        m2.metric("Total Trade Value", f"₹{position_value:,.2f}")
        m3.metric("Capital Required", f"₹{required_capital:,.2f}")
        m4.metric("Risk : Reward", f"1 : {rr_ratio:.2f}")

        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"**Actual Risk Exposure:** :red[₹{actual_risk_amount:,.2f}] ({(actual_risk_amount/total_capital)*100:.2f}%)")
        c2.markdown(f"**Expected Target Profit:** :green[₹{actual_profit_amount:,.2f}] (+{(actual_profit_amount/total_capital)*100:.2f}%)")
        c3.markdown(f"**Per Share Risk / Reward:** ₹{per_share_risk:.2f} / ₹{per_share_reward:.2f}")

        if allowed_qty == capital_qty and capital_qty < risk_qty:
            st.info("💡 Position size capped by available capital rather than the maximum risk threshold.")
    else:
        st.warning("Cannot calculate sizing: Entry and Stop Loss prices are identical or invalid.")
# ---------------------------------------------------------
# 8. IN-DEPTH ANALYSIS CONTAINER (4 TABS)
# ---------------------------------------------------------
def render_stock_analysis(row_data, key_suffix="intra"):
    """Renders Technicals, Fundamentals, Summary, and Risk Calculator in 4 clean tabs."""
    symbol = row_data['symbol']
    entry_price = float(row_data.get('entry', 0.0))
    target_price = float(row_data.get('target', 0.0))
    stop_loss_price = float(row_data.get('stop_loss', 0.0))

    st.markdown(f"### 🔍 Detailed Analysis: **{symbol}**")
    
    tab_tech, tab_fund, tab_summ, tab_risk = st.tabs([
        "📈 Technical Analysis", 
        "🏢 Fundamentals & Valuation", 
        "📝 Company Summary",
        "🧮 Risk & Position Calculator"
    ])

    # TAB A: TECHNICALS
    with tab_tech:
        c1, c2 = st.columns([1, 2])
        with c1:
            tf = st.select_slider("Timeframe", options=["1D", "5D", "1M", "6M", "1Y"], value="1M", key=f"tf_{symbol}_{key_suffix}")
        with c2:
            indicators = st.multiselect(
                "Overlay Indicators", 
                ["20 SMA", "50 SMA", "200 SMA", "VWAP", "RSI (14)", "MACD"], 
                default=["20 SMA", "VWAP", "RSI (14)"],
                key=f"ind_{symbol}_{key_suffix}"
            )
        render_stock_chart(symbol, selected_tf=tf, active_indicators=indicators)

    # TAB B: FUNDAMENTALS
    with tab_fund:
        fundamentals, _ = fetch_stock_info(symbol)
        if fundamentals:
            cols = st.columns(3)
            keys = list(fundamentals.keys())
            for i, key in enumerate(keys):
                cols[i % 3].metric(label=key, value=fundamentals[key])
        else:
            st.warning("Fundamental metrics unavailable for this symbol.")

    # TAB C: SUMMARY
    with tab_summ:
        fundamentals, summary_text = fetch_stock_info(symbol)
        st.subheader(f"About {fundamentals.get('Company Name', symbol)}")
        st.write(summary_text)

    # TAB D: RISK & POSITION SIZING
    with tab_risk:
        render_risk_calculator(symbol, entry_price, target_price, stop_loss_price)

# ---------------------------------------------------------
# 9. MULTI-TIMEFRAME WORKSTATION TABS
# ---------------------------------------------------------
tab_intraday, tab_swing, tab_longterm, tab_history = st.tabs([
    "⚡ Intraday Hub", 
    "🎯 Active Swing Portfolio", 
    "📈 Long-Term Compounders",
    "📜 Completed Trade History"
])

# --- TAB 1: INTRADAY HUB ---
with tab_intraday:
    st.subheader("⚡ Today's Intraday Momentum Setups")
    st.caption("Resets daily at 3:15 PM. Focus on high relative volume and VWAP support.")
    
    df_intra = load_data("intraday_trades", "ACTIVE")
    if not df_intra.empty:
        st.dataframe(style_dataframe(df_intra), use_container_width=True, hide_index=True)
        
        st.markdown("---")
        selected_stock = st.selectbox(
            "📊 Select a stock to view Technicals, Fundamentals, Summary & Risk:", 
            options=df_intra['symbol'].unique(),
            key="sb_intra"
        )
        if selected_stock:
            row_data = df_intra[df_intra['symbol'] == selected_stock].iloc[0].to_dict()
            render_stock_analysis(row_data, key_suffix="intra")
    else:
        st.info("No active intraday signals in database. Click '⚡ Run Screener Now' in the sidebar to scan the market.")

# --- TAB 2: SWING PORTFOLIO ---
with tab_swing:
    st.subheader("🎯 Active Swing Positions")
    st.caption("Positions remain ACTIVE until price action hits Target or Stop Loss.")
    
    df_swing = load_data("swing_trades", "ACTIVE")
    col_a, col_b = st.columns(2)
    col_a.metric("Active Swing Slots Used", f"{len(df_swing)} / 8")
    col_b.metric("Open Capacity Slots", f"{8 - len(df_swing)}")
    
    if not df_swing.empty:
        st.dataframe(style_dataframe(df_swing), use_container_width=True, hide_index=True)
        
        st.markdown("---")
        selected_swing_stock = st.selectbox(
            "📊 Select a swing position to view Technicals, Fundamentals, Summary & Risk:", 
            options=df_swing['symbol'].unique(),
            key="sb_swing"
        )
        if selected_swing_stock:
            row_data_swing = df_swing[df_swing['symbol'] == selected_swing_stock].iloc[0].to_dict()
            render_stock_analysis(row_data_swing, key_suffix="swing")
    else:
        st.info("No active swing positions in database.")

# --- TAB 3: LONG-TERM COMPOUNDERS ---
with tab_longterm:
    st.subheader("📈 Long-Term Structural Picks")
    st.caption("High-conviction structural momentum compounders.")
    
    df_lt = load_data("longterm_trades", "ACTIVE")
    if not df_lt.empty:
        st.dataframe(style_dataframe(df_lt), use_container_width=True, hide_index=True)
        
        st.markdown("---")
        selected_lt_stock = st.selectbox(
            "📊 Select a long-term pick to view Technicals, Fundamentals, Summary & Risk:", 
            options=df_lt['symbol'].unique(),
            key="sb_lt"
        )
        if selected_lt_stock:
            row_data_lt = df_lt[df_lt['symbol'] == selected_lt_stock].iloc[0].to_dict()
            render_stock_analysis(row_data_lt, key_suffix="lt")
    else:
        st.info("No active long-term positions in database.")

# --- TAB 4: COMPLETED TRADE HISTORY ---
with tab_history:
    st.subheader("📜 Historical Executed Trades & Performance")
    
    df_swing_history = load_data("swing_trades")
    df_closed = df_swing_history[df_swing_history['status'].isin(['TARGET_HIT', 'STOPLOSS_HIT'])] if not df_swing_history.empty else pd.DataFrame()
    
    if not df_closed.empty:
        win_rate = round((len(df_closed[df_closed['status'] == 'TARGET_HIT']) / len(df_closed)) * 100, 1)
        st.metric("Historical Win Rate", f"{win_rate}%")
        st.dataframe(style_dataframe(df_closed), use_container_width=True, hide_index=True)
    else:
        st.info("No completed (closed) trades recorded yet. History will populate automatically as targets/stop-losses are hit.")
