#!/usr/bin/env python
# coding: utf-8

# In[2]:


import streamlit as st
import sqlite3
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

# ---------------------------------------------------------
# 1. PAGE CONFIGURATION & STYLING
# ---------------------------------------------------------
st.set_page_config(
    page_title="Multi-Timeframe Trades",
    page_icon="⚡",
    layout="wide"
)

# Custom CSS for Index Cards & Metric Scaling
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

st.title("⚡ TRADING DASHBOARD")

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
                last_price = data['Close'].iloc[-1]
                prev_price = data['Close'].iloc[-2]
                change_pct = ((last_price - prev_price) / prev_price) * 100
                index_results[name] = (last_price, change_pct)
        except Exception:
            continue
    return index_results

indices_data = fetch_index_data()
if indices_data:
    cols = st.columns(len(indices_data))
    for i, (name, (price, change)) in enumerate(indices_data.items()):
        with cols[i].container(border=True):
            st.metric(label=name, value=f"{price:,.2f}", delta=f"{change:+.2f}%")

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

# Sidebar Controls
st.sidebar.header("Controls")
if st.sidebar.button("🔄 Refresh Data", key="refresh_btn_1"):
    st.cache_data.clear()
    st.rerun()

# ---------------------------------------------------------
# 4. COLOR-CODING & NUMBER FORMATTING STYLER
# ---------------------------------------------------------
def style_dataframe(df):
    """Formats numbers cleanly and highlights active trades based on REAL live return %."""
    if df.empty:
        return df

    df_styled = df.copy()

    # Fallback for Intraday Hub 1D Change if not explicitly provided
    if '1D_Change_%' not in df_styled.columns and 'entry' in df_styled.columns and 'vwap' in df_styled.columns:
        df_styled['1D_Change_%'] = ((df_styled['entry'] - df_styled['vwap']) / df_styled['vwap']) * 100

    # Live Floating Return % Calculation for Active Positions
    if 'return_pct' in df_styled.columns and 'status' in df_styled.columns:
        active_mask = (df_styled['status'] == 'ACTIVE') & df_styled['symbol'].notna() & df_styled['entry'].notna()
        
        if active_mask.any():
            try:
                active_symbols = [f"{sym}.NS" if not str(sym).endswith(".NS") else sym for sym in df_styled.loc[active_mask, 'symbol']]
                live_data = yf.download(active_symbols, period="1d", progress=False, threads=False)['Close']
                
                for idx in df_styled[active_mask].index:
                    sym = df_styled.loc[idx, 'symbol']
                    sym_ticker = f"{sym}.NS" if not str(sym).endswith(".NS") else sym
                    entry_price = float(df_styled.loc[idx, 'entry'])
                    
                    curr_price = None
                    if isinstance(live_data, pd.DataFrame) and sym_ticker in live_data.columns:
                        curr_price = float(live_data[sym_ticker].iloc[-1])
                    elif isinstance(live_data, pd.Series) and not live_data.empty:
                        curr_price = float(live_data.iloc[-1])
                    
                    if curr_price and entry_price > 0:
                        df_styled.loc[idx, 'return_pct'] = round(((curr_price - entry_price) / entry_price) * 100, 2)
            except Exception:
                pass

    def color_rows(row):
        val = row.get("1D_Change_%", row.get("return_pct", 0))
        if pd.notna(val) and val > 0:
            return ['background-color: #d4edda; color: #155724; font-weight: bold'] * len(row)
        elif pd.notna(val) and val < 0:
            return ['background-color: #f8d7da; color: #721c24; font-weight: bold'] * len(row)
        return [''] * len(row)

    def fmt_currency(val):
        return f"₹{val:,.2f}" if pd.notna(val) else "-"

    def fmt_num(val):
        return f"{val:.1f}" if pd.notna(val) else "-"

    def fmt_pct(val):
        return f"{val:+.2f}%" if pd.notna(val) else "-"

    format_dict = {
        "entry": fmt_currency,
        "target": fmt_currency,
        "stop_loss": fmt_currency,
        "vwap": fmt_currency,
        "exit_price": fmt_currency,
        "sma_200": fmt_currency,
        "rsi": fmt_num,
        "1D_Change_%": fmt_pct,
        "return_pct": fmt_pct
    }

    active_formats = {k: v for k, v in format_dict.items() if k in df_styled.columns}

    return df_styled.style.apply(color_rows, axis=1).format(active_formats)

# ---------------------------------------------------------
# 5. FUNDAMENTALS & SUMMARY FETCH ENGINE
# ---------------------------------------------------------
@st.cache_data(ttl=3600)
def fetch_stock_info(symbol):
    """Fetches fundamental metrics and company summary using yfinance."""
    ticker_sym = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
    try:
        ticker = yf.Ticker(ticker_sym)
        info = ticker.info
        
        fundamentals = {
            "Company Name": info.get("longName", symbol),
            "Sector": info.get("sector", "N/A"),
            "Industry": info.get("industry", "N/A"),
            "Market Cap (Cr)": f"₹{info.get('marketCap', 0) / 1e7:,.2f}" if info.get('marketCap') else "N/A",
            "Trailing P/E": f"{info.get('trailingPE', 0):.2f}" if info.get('trailingPE') else "N/A",
            "Forward P/E": f"{info.get('forwardPE', 0):.2f}" if info.get('forwardPE') else "N/A",
            "EPS (TTM)": f"₹{info.get('trailingEps', 0):.2f}" if info.get('trailingEps') else "N/A",
            "52 Week High": f"₹{info.get('fiftyTwoWeekHigh', 0):,.2f}" if info.get('fiftyTwoWeekHigh') else "N/A",
            "52 Week Low": f"₹{info.get('fiftyTwoWeekLow', 0):,.2f}" if info.get('fiftyTwoWeekLow') else "N/A",
            "PB Ratio": f"{info.get('priceToBook', 0):.2f}" if info.get('priceToBook') else "N/A",
            "Dividend Yield": f"{info.get('dividendYield', 0)*100:.2f}%" if info.get('dividendYield') else "0.00%",
            "ROE": f"{info.get('returnOnEquity', 0)*100:.2f}%" if info.get('returnOnEquity') else "N/A"
        }
        
        summary_text = info.get("longBusinessSummary", "No company summary available.")
        return fundamentals, summary_text
    except Exception:
        return {}, "Failed to load company details."

# ---------------------------------------------------------
# 6. PLOTLY CANDLESTICK & TECHNICAL CHART ENGINE
# ---------------------------------------------------------
def render_stock_chart(symbol, selected_tf="1M", active_indicators=[]):
    """Renders Plotly candlestick chart with overlays."""
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
            row_heights=[0.7, 0.3] if rows==2 else [1.0]
        )
        
        # Candlestick
        fig.add_trace(go.Candlestick(
            x=data.index, open=data['Open'], high=data['High'], 
            low=data['Low'], close=data['Close'], name="Price"
        ), row=1, col=1)

        # Overlays
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

        # Oscillators
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

        fig.update_layout(xaxis_rangeslider_visible=False, height=450, template="plotly_dark", margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Chart render error: {e}")

# ---------------------------------------------------------
# 7. IN-DEPTH ANALYSIS CONTAINER (3 TABS)
# ---------------------------------------------------------
def render_stock_analysis(symbol, key_suffix="intra"):
    """Renders Technicals, Fundamentals, and Summary in 3 clean tabs."""
    st.markdown(f"### 🔍 Detailed Stock Analysis: **{symbol}**")
    
    tab_tech, tab_fund, tab_summ = st.tabs([
        "📈 Technical Analysis", 
        "🏢 Fundamentals & Valuation", 
        "📝 Company Summary"
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

# ---------------------------------------------------------
# 8. MULTI-TIMEFRAME WORKSTATION TABS
# ---------------------------------------------------------
tab_intraday, tab_swing, tab_longterm, tab_history = st.tabs([
    "⚡ Intraday Active Ideas", 
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
            "📊 Select a stock to view Technicals, Fundamentals & Summary:", 
            options=df_intra['symbol'].unique(),
            key="sb_intra"
        )
        if selected_stock:
            render_stock_analysis(selected_stock, key_suffix="intra")
    else:
        st.info("No active intraday signals detected for today.")

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
            "📊 Select a swing position to view Technicals, Fundamentals & Summary:", 
            options=df_swing['symbol'].unique(),
            key="sb_swing"
        )
        if selected_swing_stock:
            render_stock_analysis(selected_swing_stock, key_suffix="swing")
    else:
        st.info("No active swing positions in database.")

# --- TAB 3: LONG-TERM COMPOUNDERS ---
with tab_longterm:
    st.subheader("📈 Long-Term Structural Picks ")
    st.caption("High-conviction structural momentum compounders.")
    
    df_lt = load_data("longterm_trades", "ACTIVE")
    if not df_lt.empty:
        st.dataframe(style_dataframe(df_lt), use_container_width=True, hide_index=True)
        
        st.markdown("---")
        selected_lt_stock = st.selectbox(
            "📊 Select a long-term pick to view Technicals, Fundamentals & Summary:", 
            options=df_lt['symbol'].unique(),
            key="sb_lt"
        )
        if selected_lt_stock:
            render_stock_analysis(selected_lt_stock, key_suffix="lt")
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
        


# In[ ]:




