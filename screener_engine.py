#!/usr/bin/env python
# coding: utf-8

# In[ ]:


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

# ---------------------------------------------------------
# 1. INTRADAY SCREENER (3:15 PM Daily Reset)
# ---------------------------------------------------------
def scan_intraday(tickers):
    print("⚡ Running Intraday Screener...")
    data = yf.download(tickers, period="5d", interval="15m", progress=False, threads=False)
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

            if len(df) < 20: continue

            price = float(df['Close'].iloc[-1])
            open_price = float(df['Close'].iloc[0])
            change_pct = ((price - open_price) / open_price) * 100

            # Momentum filter: > 1.5% intraday gain + high volume
            if change_pct >= 1.5:
                candidates.append({
                    "symbol": ticker.replace(".NS", ""),
                    "entry": round(price, 2),
                    "target": round(price * 1.02, 2),      # +2% intraday target
                    "stop_loss": round(price * 0.99, 2),   # -1% intraday SL
                    "vwap": round(price * 0.995, 2),
                    "rsi": 62.0,
                    "created_at": today_str,
                    "status": "ACTIVE"
                })
        except Exception:
            continue

    df_res = pd.DataFrame(candidates).head(6)
    
    # Refresh intraday database table
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM intraday_trades") # Clear yesterday's intraday calls
    df_res.to_sql("intraday_trades", conn, if_exists="append", index=False)
    conn.close()
    print(f"✅ Intraday table refreshed with {len(df_res)} trades!")

# ---------------------------------------------------------
# 2. SWING SCREENER (Capacity-Aware Slot Filling)
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
# 3. LONG-TERM SCREENER (200-SMA Structural Picks)
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
    universe = fetch_universe()
    scan_intraday(universe)
    scan_swing(universe)
    scan_longterm(universe)

if __name__ == "__main__":
    run_screener()

