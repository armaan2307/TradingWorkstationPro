import yfinance as yf
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime

DB_NAME = "trade_lifecycle.db"

# ---------------------------------------------------------
# DATABASE INITIALIZER
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
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
            exit_date TEXT,
            exit_price REAL,
            return_pct REAL
        )
    """)
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
            exit_date TEXT,
            exit_price REAL,
            return_pct REAL
        )
    """)
    conn.commit()
    conn.close()

# ---------------------------------------------------------
# UNIVERSE DEFINITION
# ---------------------------------------------------------
def fetch_universe():
    return [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
        "BHARTIARTL.NS", "SBIN.NS", "LICI.NS", "ITC.NS", "HINDUNILVR.NS",
        "LT.NS", "BAJFINANCE.NS", "HCLTECH.NS", "MARUTI.NS", "SUNPHARMA.NS",
        "TATAMOTORS.NS", "KOTAKBANK.NS", "NTPC.NS", "ONGC.NS", "TITAN.NS",
        "NATIONALUM.NS", "APARINDS.NS", "ZEEL.NS", "VIJAYA.NS", "SPLPETRO.NS",
        "AARTIIND.NS", "FORCEMOT.NS", "FINCABLES.NS", "IDEA.NS", "BERGEPAINT.NS",
        "MCX.NS", "BEML.NS", "PAYTM.NS", "POWERINDIA.NS", "GLAND.NS"
    ]

# ---------------------------------------------------------
# INTRADAY SCANNER (SINGLE-DAY VWAP & 1D MOMENTUM)
# ---------------------------------------------------------
def scan_intraday(tickers):
    print("⚡ Scanning Intraday Momentum...")
    candidates = []
    today_str = datetime.now().strftime('%Y-%m-%d')

    for ticker in tickers:
        try:
            df_1d = yf.Ticker(ticker).history(period="5d", interval="1d")
            df_15m = yf.Ticker(ticker).history(period="2d", interval="15m")

            if len(df_1d) < 2 or df_15m.empty:
                continue

            prev_close = float(df_1d['Close'].iloc[-2])
            curr_price = float(df_15m['Close'].iloc[-1])

            # Session-specific VWAP
            df_today = df_15m[df_15m.index.date == df_15m.index[-1].date()]
            if df_today.empty or df_today['Volume'].sum() == 0:
                day_vwap = curr_price
            else:
                tp = (df_today['High'] + df_today['Low'] + df_today['Close']) / 3
                day_vwap = float((tp * df_today['Volume']).sum() / df_today['Volume'].sum())

            # Real 1D Price Movement
            real_1d_change = round(((curr_price - prev_close) / prev_close) * 100, 2)

            # 14-period RSI
            delta = df_15m['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi_val = float((100 - (100 / (1 + rs))).iloc[-1])
            real_rsi = round(rsi_val, 1) if pd.notna(rsi_val) else 50.0

            candidates.append({
                "symbol": ticker.replace(".NS", ""),
                "entry": round(curr_price, 2),
                "target": round(curr_price * 1.02, 2),
                "stop_loss": round(curr_price * 0.99, 2),
                "vwap": round(day_vwap, 2),
                "rsi": real_rsi,
                "created_at": today_str,
                "status": "ACTIVE",
                "1D_Change_%": real_1d_change
            })
        except Exception:
            continue

    if candidates:
        df_res = pd.DataFrame(candidates).sort_values(by="1D_Change_%", ascending=False).head(10)
        conn = sqlite3.connect(DB_NAME)
        df_res.to_sql("intraday_trades", conn, if_exists="replace", index=False)
        conn.close()

# ---------------------------------------------------------
# SWING SCANNER
# ---------------------------------------------------------
def scan_swing(tickers):
    print("🎯 Scanning Swing Setups...")
    candidates = []
    today_str = datetime.now().strftime('%Y-%m-%d')

    for ticker in tickers:
        try:
            df = yf.Ticker(ticker).history(period="1mo")
            if len(df) < 14:
                continue

            curr_price = float(df['Close'].iloc[-1])
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi_val = float((100 - (100 / (1 + rs))).iloc[-1])

            candidates.append({
                "symbol": ticker.replace(".NS", ""),
                "category": "LargeCap",
                "entry": round(curr_price, 2),
                "target": round(curr_price * 1.08, 2),
                "stop_loss": round(curr_price * 0.95, 2),
                "rsi": round(rsi_val, 1) if pd.notna(rsi_val) else 50.0,
                "entry_date": today_str,
                "status": "ACTIVE",
                "exit_date": None,
                "exit_price": None,
                "return_pct": 0.0
            })
        except Exception:
            continue

    if candidates:
        df_res = pd.DataFrame(candidates).head(8)
        conn = sqlite3.connect(DB_NAME)
        df_res.to_sql("swing_trades", conn, if_exists="replace", index=False)
        conn.close()

# ---------------------------------------------------------
# LONG-TERM SCANNER (200 SMA)
# ---------------------------------------------------------
def scan_longterm(tickers):
    print("📈 Scanning Long-Term Structural Picks...")
    candidates = []
    today_str = datetime.now().strftime('%Y-%m-%d')

    for ticker in tickers:
        try:
            df = yf.Ticker(ticker).history(period="1y")
            if len(df) < 200:
                continue

            sma200 = float(df['Close'].rolling(200).mean().iloc[-1])
            curr_price = float(df['Close'].iloc[-1])

            if curr_price >= sma200:
                candidates.append({
                    "symbol": ticker.replace(".NS", ""),
                    "entry": round(curr_price, 2),
                    "target": round(curr_price * 1.25, 2),
                    "stop_loss": round(curr_price * 0.90, 2),
                    "sma_200": round(sma200, 2),
                    "rsi": 55.0,
                    "entry_date": today_str,
                    "status": "ACTIVE",
                    "exit_date": None,
                    "exit_price": None,
                    "return_pct": 0.0
                })
        except Exception:
            continue

    if candidates:
        df_res = pd.DataFrame(candidates).head(5)
        conn = sqlite3.connect(DB_NAME)
        df_res.to_sql("longterm_trades", conn, if_exists="replace", index=False)
        conn.close()

def run_screener():
    init_db()
    universe = fetch_universe()
    scan_intraday(universe)
    scan_swing(universe)
    scan_longterm(universe)

if __name__ == "__main__":
    run_screener()
