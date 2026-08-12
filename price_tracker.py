#!/usr/bin/env python
# coding: utf-8

# In[1]:


import sqlite3
import pandas as pd
import yfinance as yf
from datetime import datetime

DB_NAME = "trade_lifecycle.db"

def check_and_update_positions():
    """Scans active swing and long-term positions against current price action to evaluate exits."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    # ---------------------------------------------------------
    # 1. EVALUATE ACTIVE SWING TRADES
    # ---------------------------------------------------------
    df_swing = pd.read_sql("SELECT * FROM swing_trades WHERE status = 'ACTIVE'", conn)
    
    if not df_swing.empty:
        print(f"🔍 Monitoring {len(df_swing)} active swing positions...")
        tickers = [f"{sym}.NS" for sym in df_swing['symbol'].tolist()]
        
        # Download daily high/low data
        data = yf.download(tickers, period="2d", interval="1d", progress=False, threads=False)
        
        for _, row in df_swing.iterrows():
            sym = row['symbol']
            ticker_sym = f"{sym}.NS"
            entry = row['entry']
            target = row['target']
            sl = row['stop_loss']
            trade_id = row['id']
            
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    high_price = float(data['High'][ticker_sym].iloc[-1])
                    low_price = float(data['Low'][ticker_sym].iloc[-1])
                    close_price = float(data['Close'][ticker_sym].iloc[-1])
                else:
                    high_price = float(data['High'].iloc[-1])
                    low_price = float(data['Low'].iloc[-1])
                    close_price = float(data['Close'].iloc[-1])
                
                # Check Target Hit
                if high_price >= target:
                    ret_pct = round(((target - entry) / entry) * 100, 2)
                    cursor.execute('''
                        UPDATE swing_trades 
                        SET status = 'TARGET_HIT', exit_date = ?, exit_price = ?, return_pct = ?
                        WHERE id = ?
                    ''', (today_str, target, ret_pct, trade_id))
                    print(f"🎯 Target Hit for {sym}! Gain: +{ret_pct}%")
                
                # Check Stop Loss Hit
                elif low_price <= sl:
                    ret_pct = round(((sl - entry) / entry) * 100, 2)
                    cursor.execute('''
                        UPDATE swing_trades 
                        SET status = 'STOPLOSS_HIT', exit_date = ?, exit_price = ?, return_pct = ?
                        WHERE id = ?
                    ''', (today_str, sl, ret_pct, trade_id))
                    print(f"🛑 Stop Loss Hit for {sym}. Loss: {ret_pct}%")
                    
            except Exception as e:
                print(f"Error evaluating {sym}: {e}")
    else:
        print("ℹ️ No active swing trades currently in database.")

    # ---------------------------------------------------------
    # 2. EVALUATE ACTIVE LONG-TERM TRADES
    # ---------------------------------------------------------
    df_lt = pd.read_sql("SELECT * FROM longterm_trades WHERE status = 'ACTIVE'", conn)
    
    if not df_lt.empty:
        print(f"🔍 Monitoring {len(df_lt)} active long-term positions...")
        tickers_lt = [f"{sym}.NS" for sym in df_lt['symbol'].tolist()]
        data_lt = yf.download(tickers_lt, period="2d", interval="1d", progress=False, threads=False)
        
        for _, row in df_lt.iterrows():
            sym = row['symbol']
            ticker_sym = f"{sym}.NS"
            entry = row['entry']
            target = row['target']
            sl = row['stop_loss']
            trade_id = row['id']
            
            try:
                if isinstance(data_lt.columns, pd.MultiIndex):
                    high_price = float(data_lt['High'][ticker_sym].iloc[-1])
                    low_price = float(data_lt['Low'][ticker_sym].iloc[-1])
                else:
                    high_price = float(data_lt['High'].iloc[-1])
                    low_price = float(data_lt['Low'].iloc[-1])
                
                if high_price >= target:
                    ret_pct = round(((target - entry) / entry) * 100, 2)
                    cursor.execute('''
                        UPDATE longterm_trades 
                        SET status = 'TARGET_HIT', exit_date = ?, exit_price = ?, return_pct = ?
                        WHERE id = ?
                    ''', (today_str, target, ret_pct, trade_id))
                    print(f"🎯 Long-Term Target Hit for {sym}! Gain: +{ret_pct}%")
                elif low_price <= sl:
                    ret_pct = round(((sl - entry) / entry) * 100, 2)
                    cursor.execute('''
                        UPDATE longterm_trades 
                        SET status = 'STOPLOSS_HIT', exit_date = ?, exit_price = ?, return_pct = ?
                        WHERE id = ?
                    ''', (today_str, sl, ret_pct, trade_id))
                    print(f"🛑 Long-Term Stop Loss Hit for {sym}. Loss: {ret_pct}%")
            except Exception as e:
                print(f"Error evaluating {sym}: {e}")

    conn.commit()
    conn.close()
    print("✅ Price tracking check completed!")

if __name__ == "__main__":
    check_and_update_positions()


# In[ ]:




