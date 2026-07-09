import os
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
MAX_ALLOCATION = 0.30
MIN_SCORE = 65

NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("BOT_TOKEN or CHAT_ID missing")
        print(message)
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }

    r = requests.post(url, json=payload, timeout=30)

    print("Telegram status:", r.status_code)
    print(r.text[:300])


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

    except Exception as e:
        print("Download error:", symbol, e)
        return None


def get_nifty500_symbols():
    df = pd.read_csv(NIFTY500_URL)
    return (df["Symbol"] + ".NS").tolist()


def download_benchmark():
    benchmark = download_stock("^NSEI")

    if benchmark is None:
        benchmark = download_stock("NIFTYBEES.NS")

    return benchmark


def add_indicators(df):
    try:
        if df is None or len(df) < 220:
            return None

        df = df.copy()

        close = df["Close"].squeeze()
        high = df["High"].squeeze()
        low = df["Low"].squeeze()
        volume = df["Volume"].squeeze()

        df["EMA20"] = EMAIndicator(close, window=20).ema_indicator()
        df["EMA50"] = EMAIndicator(close, window=50).ema_indicator()
        df["EMA200"] = EMAIndicator(close, window=200).ema_indicator()

        df["RSI"] = RSIIndicator(close, window=14).rsi()

        macd = MACD(close)
        df["MACD"] = macd.macd()
        df["MACD_SIGNAL"] = macd.macd_signal()

        df["ADX"] = ADXIndicator(
            high=high,
            low=low,
            close=close,
            window=14
        ).adx()

        df["ATR"] = AverageTrueRange(
            high=high,
            low=low,
            close=close,
            window=14
        ).average_true_range()

        df["VOL_AVG20"] = volume.rolling(20).mean()
        df["HIGH_20"] = high.rolling(20).max()
        df["LOW_20"] = low.rolling(20).min()

        df = df.dropna()

        if df.empty:
            return None

        return df

    except Exception as e:
        print("Indicator error:", e)
        return None


def relative_strength(stock_df, benchmark_df, lookback=60):
    try:
        stock_df = stock_df.dropna()
        benchmark_df = benchmark_df.dropna()

        lb = min(
            lookback,
            len(stock_df) - 1,
            len(benchmark_df) - 1
        )

        if lb < 20:
            return 0.0

        stock_return = (
            float(stock_df["Close"].iloc[-1]) /
            float(stock_df["Close"].iloc[-lb])
        ) - 1

        benchmark_return = (
            float(benchmark_df["Close"].iloc[-1]) /
            float(benchmark_df["Close"].iloc[-lb])
        ) - 1

        return round(stock_return - benchmark_return, 4)

    except Exception:
        return 0.0


def weekly_trend(symbol):
    try:
        weekly = download_stock(symbol, period="3y", interval="1wk")

        if weekly is None or len(weekly) < 80:
            return False

        close = weekly["Close"].squeeze()

        weekly["EMA20"] = EMAIndicator(
            close,
            window=20
        ).ema_indicator()

        weekly["EMA50"] = EMAIndicator(
            close,
            window=50
        ).ema_indicator()

        weekly = weekly.dropna()

        if weekly.empty:
            return False

        latest = weekly.iloc[-1]

        return (
            latest["Close"] > latest["EMA20"]
            and latest["EMA20"] > latest["EMA50"]
        )

    except Exception:
        return False


def grade_stock(score):
    if score >= 90:
        return "Elite"
    elif score >= 80:
        return "Strong"
    elif score >= 70:
        return "Good"
    elif score >= 65:
        return "Watchlist"
    else:
        return "Ignore"


def analyze_stock(symbol, benchmark_df):
    try:
        raw_df = download_stock(symbol)

        if raw_df is None or len(raw_df) < 220:
            return None

        df = add_indicators(raw_df)

        if df is None or df.empty:
            return None

        latest = df.iloc[-1]

        score = 0
        reasons = []

        rs = relative_strength(df, benchmark_df)
        weekly_ok = weekly_trend(symbol)

        if latest["Close"] > latest["EMA200"]:
            score += 10
            reasons.append("Above EMA200")

        if latest["EMA20"] > latest["EMA50"]:
            score += 10
            reasons.append("EMA20 > EMA50")

        if weekly_ok:
            score += 15
            reasons.append("Weekly bullish")

        if rs >= 0.05:
            score += 15
            reasons.append("Strong RS")
        elif rs > 0:
            score += 7
            reasons.append("Positive RS")

        prev_high = df["HIGH_20"].shift(1).iloc[-1]

        if latest["Close"] > prev_high:
            score += 15
            reasons.append("20-day breakout")

        volume_ratio = latest["Volume"] / latest["VOL_AVG20"]

        if volume_ratio >= 2:
            score += 10
            reasons.append("High volume")
        elif volume_ratio >= 1.5:
            score += 7
            reasons.append("Volume breakout")
        elif volume_ratio >= 1.2:
            score += 4
            reasons.append("Volume above average")

        if latest["ADX"] >= 30:
            score += 10
            reasons.append("Strong ADX")
        elif latest["ADX"] >= 25:
            score += 7
            reasons.append("ADX positive")

        if 50 <= latest["RSI"] <= 68:
            score += 10
            reasons.append("Healthy RSI")
        elif 68 < latest["RSI"] <= 75:
            score += 5
            reasons.append("RSI elevated")

        entry = float(latest["Close"])
        stop_loss = entry - (1.5 * float(latest["ATR"]))
        risk = entry - stop_loss

        if risk <= 0:
            return None

        target = entry + (2 * risk)

        risk_amount = CAPITAL * RISK_PER_TRADE
        qty_risk = int(risk_amount / risk)
        qty_capital = int((CAPITAL * MAX_ALLOCATION) / entry)

        quantity = min(qty_risk, qty_capital)

        if quantity <= 0:
            return None

        capital_required = quantity * entry

        return {
            "Symbol": symbol,
            "Score": round(score, 2),
            "Grade": grade_stock(score),
            "Entry": round(entry, 2),
            "Stop Loss": round(stop_loss, 2),
            "Target": round(target, 2),
            "Quantity": quantity,
            "Capital Required": round(capital_required, 2),
            "Risk Reward": 2,
            "RS %": round(rs * 100, 2),
            "RSI": round(float(latest["RSI"]), 2),
            "ADX": round(float(latest["ADX"]), 2),
            "Volume Ratio": round(float(volume_ratio), 2),
            "Weekly Trend": weekly_ok,
            "Reasons": ", ".join(reasons)
        }

    except Exception as e:
        print("Analyze error:", symbol, e)
        return None


def run_scanner():
    print("Starting Nifty 500 scanner...")

    symbols = get_nifty500_symbols()

    benchmark = download_benchmark()
    benchmark = add_indicators(benchmark)

    if benchmark is None:
        print("Benchmark failed")
        return pd.DataFrame(), pd.DataFrame()

    results = []

    for i, symbol in enumerate(symbols):
        result = analyze_stock(symbol, benchmark)

        if result is not None:
            results.append(result)

        if (i + 1) % 50 == 0:
            print("Scanned", i + 1)

    scanner = pd.DataFrame(results)

    if scanner.empty:
        return scanner, pd.DataFrame()

    scanner = scanner.sort_values(
        ["Score", "RS %"],
        ascending=False
    ).reset_index(drop=True)

    final = scanner[
        scanner["Score"] >= MIN_SCORE
    ].head(MAX_POSITIONS).reset_index(drop=True)

    return scanner, final


def format_signals(final):
    today = datetime.now().strftime("%d-%b-%Y")

    msg = (
        "🏆 NIFTY 500 SWING SIGNALS V3\n\n"
        f"📅 Date: {today}\n"
        f"✅ Signals Found: {len(final)}\n\n"
    )

    if final.empty:
        msg += "No high-quality setups today."
        return msg

    for i, row in final.iterrows():
        msg += (
            f"{i + 1}. {row['Symbol']} — {row['Grade']}\n\n"
            f"Score: {row['Score']}/100\n"
            f"Entry: ₹{row['Entry']}\n"
            f"SL: ₹{row['Stop Loss']}\n"
            f"Target: ₹{row['Target']}\n"
            f"Qty: {row['Quantity']}\n"
            f"Capital: ₹{round(row['Capital Required'])}\n"
            f"RS: {row['RS %']}%\n"
            f"Reasons: {row['Reasons']}\n\n"
            "--------------------\n\n"
        )

    msg += "⚠️ Educational use only. Confirm manually before trading."

    return msg


def save_reports(scanner, final):
    today = datetime.now().strftime("%Y%m%d")

    if not scanner.empty:
        scanner.to_csv(f"scanner_{today}.csv", index=False)

    if not final.empty:
        final.to_csv(f"signals_{today}.csv", index=False)

    print("Reports saved")
TRADE_FILE = "trade_journal.csv"

def update_trade_journal(final):

    if final.empty:
        return

    if os.path.exists(TRADE_FILE):
        journal = pd.read_csv(TRADE_FILE)
    else:
        journal = pd.DataFrame(columns=[
            "Date","Symbol","Buy Price","Quantity",
            "Stop Loss","Target","Status",
            "Exit Price","PnL"
        ])

    for _, row in final.iterrows():

        open_symbols = journal[
            journal["Status"]=="Open"
        ]["Symbol"].tolist()

        if row["Symbol"] in open_symbols:
            continue

        journal.loc[len(journal)] = [
            datetime.now().strftime("%Y-%m-%d"),
            row["Symbol"],
            row["Entry"],
            row["Quantity"],
            row["Stop Loss"],
            row["Target"],
            "Open",
            "",
            ""
        ]

    journal.to_csv(TRADE_FILE,index=False)

def main():
    scanner, final = run_scanner()

    print("Stocks analyzed:", len(scanner))
    print("Signals found:", len(final))

    message = format_signals(final)
    send_telegram(message)

    save_reports(scanner, final)

    print("Done")


if __name__ == "__main__":
    main()
