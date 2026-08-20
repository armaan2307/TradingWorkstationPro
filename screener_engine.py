import io
import urllib.request
import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

DB_NAME = "trade_lifecycle.db"

def get_nse_tickers(url, fallback_list):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            csv_data = response.read().decode('utf-8')
        df_nse = pd.read_csv(io.StringIO(csv_data))
        symbols = df_nse['Symbol'].dropna().tolist()
        return [f"{str(sym).strip()}.NS" for sym in symbols]
    except Exception:
        return fallback_list

def fetch_universe():
    nifty50 = get_nse_tickers("https://archives.nseindia.com/content/indices/ind_nifty50list.csv", ["RELIANCE.NS", "TCS.NS"])
    midcap = get_nse_tickers("https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv", ["PERSISTENT.NS", "POLYCAB.NS"])
    smallcap = get_nse_tickers("https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv", ["SUZLON.NS", "CDSL.NS"])
    return list(set(nifty50 + midcap + smallcap))

def init_db():
    """Ensures all required SQLite tables exist before running screeners."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Intraday Trades Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS intraday_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            entry REAL,
            target REAL,
            stop_loss REAL,
            vwap REAL,
            rsi REAL,
            created_at TEXT,
            status TEXT,
            "1D_Change_%" REAL
        )
    """)
    
    # Swing Trades Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS swing_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            category TEXT,
            entry REAL,
            target REAL,
            stop_loss REAL,
            rsi REAL,
            entry_date TEXT,
            status TEXT,
            return_pct REAL
        )
    """)
    
    # Long-Term Compounders Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS longterm_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            entry REAL,
            target REAL,
            stop_loss REAL,
            sma_200 REAL,
            rsi REAL,
            entry_date TEXT,
            status TEXT,
            return_pct REAL
        )
    """)
    
    conn.commit()
    conn.close()
    print("DATABASE INITIALIZED READY FOR SCANNER!")
# ---------------------------------------------------------
# 1. INTRADAY SCREENER (3:15 PM Daily Reset)
# ---------------------------------------------------------
def scan_intraday(tickers):
    print("⚡ Running Intraday Screener with Single-Day VWAP & 1D Change...")
    
    # Fetch 5 days to get yesterday's close, but we filter for today's session
    data_15m = yf.download(tickers, period="5d", interval="15m", progress=False, threads=False)
    data_1d = yf.download(tickers, period="5d", interval="1d", progress=False, threads=False)
    
    candidates = []
    today_date = datetime.now().date()
    today_str = today_date.strftime('%Y-%m-%d')

    for ticker in tickers:
        try:
            # Extract intraday DataFrame
            if isinstance(data_15m.columns, pd.MultiIndex):
                if ticker in data_15m['Close'].columns:
                    df_15m = pd.DataFrame({
                        'Close': data_15m['Close'][ticker],
                        'High': data_15m['High'][ticker],
                        'Low': data_15m['Low'][ticker],
                        'Volume': data_15m['Volume'][ticker]
                    }).dropna()
                    df_daily = data_1d['Close'][ticker].dropna()
                else: continue
            else:
                df_15m = pd.DataFrame({
                    'Close': data_15m['Close'],
                    'High': data_15m['High'],
                    'Low': data_15m['Low'],
                    'Volume': data_15m['Volume']
                }).dropna()
                df_daily = data_1d['Close'].dropna()

            if len(df_15m) < 14 or len(df_daily) < 2: continue

            # 1. Get Exact Previous Day Close Price
            prev_close = float(df_daily.iloc[-2])
            current_price = float(df_15m['Close'].iloc[-1])

            # 2. Filter 15m data for TODAY ONLY for Single-Session VWAP
            df_today = df_15m[df_15m.index.date == df_15m.index[-1].date()]
            if df_today.empty:
                df_today = df_15m.tail(25) # Fallback to last session bars if market is closed

            # Single-day VWAP Calculation
            typical_price = (df_today['High'] + df_today['Low'] + df_today['Close']) / 3
            day_vwap = float((typical_price * df_today['Volume']).sum() / df_today['Volume'].sum())

            # 3. Exact 1-Day % Change relative to Previous Day Close
            real_1d_change = round(((current_price - prev_close) / prev_close) * 100, 2)

            # 4. RSI (14-period on 15m chart)
            delta = df_15m['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            real_rsi = float((100 - (100 / (1 + rs))).iloc[-1])

            candidates.append({
                "symbol": ticker.replace(".NS", ""),
                "entry": round(current_price, 2),
                "target": round(current_price * 1.02, 2),
                "stop_loss": round(current_price * 0.99, 2),
                "vwap": round(day_vwap, 2),
                "rsi": round(real_rsi, 1) if pd.notna(real_rsi) else 50.0,
                "created_at": today_str,
                "status": "ACTIVE",
                "1D_Change_%": real_1d_change
            })
        except Exception:
            continue

    df_res = pd.DataFrame(candidates).sort_values(by="1D_Change_%", ascending=False).head(10)

    # Save to SQLite Database
    conn = sqlite3.connect(DB_NAME)
    df_res.to_sql("intraday_trades", conn, if_exists="replace", index=False)
    conn.close()
    print(f"✅ Intraday table updated with true single-day VWAP and 1D change!")    
# 2. SWING SCREENER
# ---------------------------------------------------------
def scan_swing(tickers, max_capacity=8):
    conn = sqlite3.connect(DB_NAME)
    active_count = pd.read_sql("SELECT COUNT(*) as count FROM swing_trades WHERE status = 'ACTIVE'", conn)['count'].iloc[0]
    
    slots_open = max_capacity - active_count
    print(f"🎯 Active Swing Positions: {active_count}/{max_capacity} | Open Slots: {slots_open}")

    if slots_open <= 0:
        print("ℹ️ Swing portfolio is at max capacity. Skipping scan until a position hits Target/SL.")
        conn.close()
        return

    print("🔍 Scanning for Swing Trade setups to fill open slots...")
    data = yf.download(tickers, period="6mo", interval="1d", progress=False, threads=False)
    candidates = []
    today_str = datetime.now().strftime('%Y-%m-%d')

    for ticker in tickers:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if ticker in data['Close'].columns:
                    df = pd.DataFrame({'Close': data['Close'][ticker], 'Volume': data['Volume'][ticker]}).dropna()
                else: continue
            else:
                df = pd.DataFrame({'Close': data['Close'], 'Volume': data['Volume']}).dropna()

            if len(df) < 50: continue

            df['SMA50'] = df['Close'].rolling(50).mean()
            price = float(df['Close'].iloc[-1])
            sma50 = float(df['SMA50'].iloc[-1])

            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))
            rsi = float(df['RSI'].iloc[-1])

            if price > sma50 and (55 <= rsi <= 72):
                candidates.append({
                    "symbol": ticker.replace(".NS", ""),
                    "category": "MidCap" if "MID" in ticker else "LargeCap",
                    "entry": round(price, 2),
                    "target": round(price * 1.08, 2),     # +8% target
                    "stop_loss": round(price * 0.95, 2),  # -5% SL
                    "rsi": round(rsi, 1),
                    "entry_date": today_str,
                    "status": "ACTIVE"
                })
        except Exception:
            continue

    df_res = pd.DataFrame(candidates).head(slots_open)
    if not df_res.empty:
        df_res.to_sql("swing_trades", conn, if_exists="append", index=False)
        print(f"✅ Added {len(df_res)} new swing trade(s) to database!")
    conn.close()

# ---------------------------------------------------------
# 3. LONG-TERM SCREENER
# ---------------------------------------------------------
def scan_longterm(tickers, max_capacity=5):
    conn = sqlite3.connect(DB_NAME)
    active_count = pd.read_sql("SELECT COUNT(*) as count FROM longterm_trades WHERE status = 'ACTIVE'", conn)['count'].iloc[0]
    
    slots_open = max_capacity - active_count
    print(f"📈 Active Long-Term Positions: {active_count}/{max_capacity} | Open Slots: {slots_open}")

    if slots_open <= 0:
        print("ℹ️ Long-Term portfolio is full. Skipping scan.")
        conn.close()
        return

    print("🔍 Scanning for Long-Term compounder setups...")
    data = yf.download(tickers, period="1y", interval="1d", progress=False, threads=False)
    candidates = []
    today_str = datetime.now().strftime('%Y-%m-%d')

    for ticker in tickers:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if ticker in data['Close'].columns:
                    df = pd.DataFrame({'Close': data['Close'][ticker]}).dropna()
                else: continue
            else:
                df = pd.DataFrame({'Close': data['Close']}).dropna()

            if len(df) < 200: continue

            df['SMA200'] = df['Close'].rolling(200).mean()
            price = float(df['Close'].iloc[-1])
            sma200 = float(df['SMA200'].iloc[-1])

            if price > (1.05 * sma200): # Trading > 5% above 200 SMA
                candidates.append({
                    "symbol": ticker.replace(".NS", ""),
                    "entry": round(price, 2),
                    "target": round(price * 1.25, 2),     # +25% Long-term target
                    "stop_loss": round(price * 0.88, 2),  # -12% Trailing SL
                    "sma_200": round(sma200, 2),
                    "entry_date": today_str,
                    "status": "ACTIVE"
                })
        except Exception:
            continue

    df_res = pd.DataFrame(candidates).head(slots_open)
    if not df_res.empty:
        df_res.to_sql("longterm_trades", conn, if_exists="append", index=False)
        print(f"✅ Added {len(df_res)} new long-term trade(s) to database!")
    conn.close()

def run_screener():
    init_db()
    universe = fetch_universe()
    scan_intraday(universe)
    scan_swing(universe)
    scan_longterm(universe)

if __name__ == "__main__":
    run_screener()
