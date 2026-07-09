import os
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime

from ta.trend import EMAIndicator, ADXIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange


BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

GROWW_ACCESS_TOKEN = os.getenv("GROWW_ACCESS_TOKEN")
GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")

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
    payload = {"chat_id": CHAT_ID, "text": message}

    response = requests.post(url, json=payload, timeout=30)

    print("Telegram status:", response.status_code)
    print(response.text[:300])


def get_groww_client():
    try:
        from growwapi import GrowwAPI

        if not GROWW_ACCESS_TOKEN:
            print("Groww access token missing")
            return None

        return GrowwAPI(GROWW_ACCESS_TOKEN)

    except Exception as e:
        print("Groww login error:", e)
        return None


def extract_symbols_from_groww(data):
    symbols = set()

    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                k = str(key).lower()

                if k in [
                    "trading_symbol",
                    "tradingsymbol",
                    "symbol",
                    "nse_symbol",
                    "company_symbol"
                ]:
                    if value:
                        s = str(value).strip()
                        if s and not s.endswith(".NS"):
                            s = s + ".NS"
                        symbols.add(s)

                walk(value)

        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return sorted(symbols)


def get_broker_holdings():
    client = get_groww_client()

    if client is None:
        return [], None

    try:
        holdings = client.get_holdings_for_user()
        symbols = extract_symbols_from_groww(holdings)

        print("Groww holdings:", symbols)

        return symbols, holdings

    except Exception as e:
        print("Groww holdings error:", e)
        return [], None


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

        df["EMA20"] = EMAIndicator(close=close, window=20).ema_indicator()
        df["EMA50"] = EMAIndicator(close=close, window=50).ema_indicator()
        df["EMA200"] = EMAIndicator(close=close, window=200).ema_indicator()

        df["RSI"] = RSIIndicator(close=close, window=14).rsi()

        macd = MACD(close=close)
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
            close=close,
            window=20
        ).ema_indicator()

        weekly["EMA50"] = EMAIndicator(
            close=close,
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


def run_scanner(exclude_symbols=None):
    print("Starting Nifty 500 scanner...")

    if exclude_symbols is None:
        exclude_symbols = []

    symbols = get_nifty500_symbols()

    benchmark = download_benchmark()
    benchmark = add_indicators(benchmark)

    if benchmark is None:
        print("Benchmark failed")
        return pd.DataFrame(), pd.DataFrame()

    results = []

    for i, symbol in enumerate(symbols):
        if symbol in exclude_symbols:
            continue

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


def download_last_close(symbol):
    df = download_stock(symbol, period="6mo", interval="1d")

    if df is None or len(df) < 5:
        return None

    current = float(df["Close"].iloc[-1])
    previous = float(df["Close"].iloc[-2])
    change_pct = ((current - previous) / previous) * 100

    return {
        "symbol": symbol,
        "current": round(current, 2),
        "change_pct": round(change_pct, 2)
    }


def market_brief():
    items = {
        "Nifty 50": "^NSEI",
        "Bank Nifty": "^NSEBANK",
        "India VIX": "^INDIAVIX",
        "USD/INR": "INR=X",
        "Crude Oil": "CL=F",
        "Gold": "GC=F",
        "S&P 500": "^GSPC",
        "Nasdaq": "^IXIC"
    }

    msg = "📰 DAILY MARKET BRIEF\n\n"

    for name, symbol in items.items():
        data = download_last_close(symbol)

        if data is None:
            continue

        emoji = "🟢" if data["change_pct"] >= 0 else "🔴"

        msg += (
            f"{emoji} {name}: {data['current']} "
            f"({data['change_pct']}%)\n"
        )

    nifty = download_stock("^NSEI", period="1y", interval="1d")
    nifty = add_indicators(nifty)

    if nifty is not None and not nifty.empty:
        latest = nifty.iloc[-1]

        if latest["Close"] > latest["EMA200"] and latest["EMA20"] > latest["EMA50"]:
            mood = "🟢 Bullish"
        elif latest["Close"] > latest["EMA200"]:
            mood = "🟡 Neutral"
        else:
            mood = "🔴 Weak"

        msg += f"\nMarket Mood: {mood}\n"

    msg += "\nSignals will follow below."

    return msg


def format_signals(final, broker_holdings):
    today = datetime.now().strftime("%d-%b-%Y")

    msg = (
        "🏆 NIFTY 500 SWING SIGNALS V3\n\n"
        f"📅 Date: {today}\n"
        f"📌 Broker Holdings Detected: {len(broker_holdings)}\n"
        f"✅ Signals Found: {len(final)}\n\n"
    )

    if broker_holdings:
        msg += "Current Holdings:\n"
        for symbol in broker_holdings:
            msg += f"• {symbol}\n"
        msg += "\n"

    if final.empty:
        msg += "No new high-quality setups today."
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


def main():
    brief = market_brief()
    send_telegram(brief)

    broker_holdings, raw_holdings = get_broker_holdings()

    scanner, final = run_scanner(exclude_symbols=broker_holdings)

    print("Stocks analyzed:", len(scanner))
    print("Signals found:", len(final))

    signal_message = format_signals(final, broker_holdings)
    send_telegram(signal_message)

    save_reports(scanner, final)

    print("Done")


if __name__ == "__main__":
    main()
