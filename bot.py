import os
import math
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

from ta.trend import EMAIndicator, ADXIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange


BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CAPITAL = 100000
RISK_PER_TRADE = 0.01
MAX_POSITIONS = 5
MAX_OPEN_TRADES = 4
MAX_ALLOCATION = 0.30
MIN_SCORE = 65

NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
TRADE_FILE = "trade_journal.csv"


def clean_data(df):
    if df is None or df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna()

    if df.empty:
        return None

    return df


def download_stock(symbol, period="1y", interval="1d"):
    try:
        df = yf.download(
            symbol,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False
        )
        return clean_data(df)
    except Exception:
        return None


def get_nifty500_symbols():
    df = pd.read_csv(NIFTY500_URL)
    return (df["Symbol"] + ".NS").tolist()


def download_benchmark():
    benchmark = download_stock("^NSEI")

    if benchmark is None:
        benchmark = download_stock("NIFTYBEES.NS")

    return benchmark
