import json
import base64
import io
import os

os.environ.setdefault("MPLCONFIGDIR", "/tmp")

import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
from datetime import date, timedelta


FOREX_PAIR = "GBPUSD=X"

PALETTE = [
    "#00A4EF", "#1877F2", "#FF9900", "#2ECC71",
    "#9B59B6", "#E67E22", "#1ABC9C", "#E74C3C",
]


def detect_currency(symbol: str) -> str:
    """GBP for London-listed tickers (.L suffix), USD otherwise."""
    return "GBP" if symbol.upper().endswith(".L") else "USD"


def fetch_closes(tickers: list, start: date, end: date) -> pd.DataFrame:
    raw = yf.download(
        tickers,
        start=start,
        end=end + timedelta(days=1),
        progress=False,
        auto_adjust=True,
    )
    if len(tickers) == 1:
        return raw["Close"].rename(tickers[0]).to_frame()
    return raw["Close"].dropna(how="all")


def get_period_return(ticker: str, start: date, end: date) -> dict:
    data = yf.download(
        ticker,
        start=start,
        end=end + timedelta(days=1),
        progress=False,
        auto_adjust=True,
    )
    if data.empty or len(data) < 2:
        raise ValueError(f"Insufficient data for {ticker}")
    close = data["Close"].squeeze().dropna()
    start_price = float(close.iloc[0])
    end_price = float(close.iloc[-1])
    return {
        "start_price": round(start_price, 4),
        "end_price": round(end_price, 4),
        "actual_start": str(close.index[0].date()),
        "actual_end": str(close.index[-1].date()),
        "return_local_pct": round((end_price / start_price - 1) * 100, 4),
    }


def build_table(tickers: list, index: str, days: int) -> tuple[list, dict]:
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    rows = []

    # Index row
    idx = get_period_return(index, start_date, end_date)
    index_return = idx["return_local_pct"]
    rows.append({
        "ticker": index,
        "currency": "GBP",
        "start_price": idx["start_price"],
        "end_price": idx["end_price"],
        "actual_start": idx["actual_start"],
        "actual_end": idx["actual_end"],
        "return_local_pct": index_return,
        "return_gbp_pct": index_return,
        "vs_index_pp": 0.0,
        "forex_adjustment_pp": None,
    })

    # Forex snapshot
    fx = get_period_return(FOREX_PAIR, start_date, end_date)
    gbpusd_start = fx["start_price"]
    gbpusd_end = fx["end_price"]

    # Basket rows
    for ticker in tickers:
        currency = detect_currency(ticker)
        stock = get_period_return(ticker, start_date, end_date)
        if currency == "USD":
            factor = (stock["end_price"] / stock["start_price"]) * (gbpusd_start / gbpusd_end)
            gbp_return = round((factor - 1) * 100, 4)
            forex_adj = round(gbp_return - stock["return_local_pct"], 4)
        else:
            gbp_return = stock["return_local_pct"]
            forex_adj = None
        rows.append({
            "ticker": ticker,
            "currency": currency,
            "start_price": stock["start_price"],
            "end_price": stock["end_price"],
            "actual_start": stock["actual_start"],
            "actual_end": stock["actual_end"],
            "return_local_pct": stock["return_local_pct"],
            "return_gbp_pct": gbp_return,
            "vs_index_pp": round(gbp_return - index_return, 4),
            "forex_adjustment_pp": forex_adj,
        })

    basket_returns = [r["return_gbp_pct"] for r in rows if r["ticker"] in tickers]
    basket_avg = round(sum(basket_returns) / len(basket_returns), 4)

    summary = {
        "period": {"start": str(start_date), "end": str(end_date)},
        "forex": {
            "pair": FOREX_PAIR,
            "gbpusd_start": gbpusd_start,
            "gbpusd_end": gbpusd_end,
            "change_pct": round((gbpusd_end / gbpusd_start - 1) * 100, 4),
        },
        "basket_avg_return_gbp_pct": basket_avg,
        "index_return_gbp_pct": index_return,
        "basket_vs_index_pp": round(basket_avg - index_return, 4),
    }

    return rows, summary


def _configure_xaxis(ax, days: int) -> None:
    """Set x-axis tick density and date format based on the window length."""
    if days <= 60:
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, days // 10)))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    elif days <= 360:
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=max(1, days // 70)))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    elif days <= 1095:
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=max(1, days // 300)))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    else:
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def build_chart(tickers: list, index: str, days: int) -> str:
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    all_tickers = tickers + [index, FOREX_PAIR]
    prices = fetch_closes(all_tickers, start_date, end_date)
    gbpusd = prices[FOREX_PAIR].dropna()

    fig, ax = plt.subplots(figsize=(11, 6))

    # Index line
    idx_series = prices[index].dropna()
    idx_indexed = (idx_series / idx_series.iloc[0]) * 100
    ax.plot(idx_indexed.index, idx_indexed.values,
            color="#E63946", linewidth=2.5, linestyle="--", label=f"{index} (benchmark)")

    # Basket lines
    for i, ticker in enumerate(tickers):
        series = prices[ticker].dropna()
        if detect_currency(ticker) == "USD":
            fx = gbpusd.reindex(series.index).ffill()
            series = series / fx
        indexed = (series / series.iloc[0]) * 100
        suffix = " (GBP-adj)" if detect_currency(ticker) == "USD" else ""
        ax.plot(indexed.index, indexed.values,
                color=PALETTE[i % len(PALETTE)], linewidth=1.8, label=f"{ticker}{suffix}")

    ax.axhline(100, color="grey", linewidth=0.8, linestyle=":")
    ax.set_title(
        f"Performance vs {index}  ·  {start_date} → {end_date}  (indexed to 100)",
        fontsize=13, pad=12,
    )
    ax.set_ylabel("Indexed return (100 = start)", fontsize=11)
    _configure_xaxis(ax, days)
    plt.xticks(rotation=30, ha="right")
    ax.legend(fontsize=10)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
    "Content-Type": "application/json",
}


def handler(event, context):
    # Handle CORS preflight
    method = (event.get("requestContext") or {}).get("http", {}).get("method", "")
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    try:
        body = json.loads(event.get("body") or "{}")
        tickers = [t.strip().upper() for t in body.get("tickers", []) if t.strip()]
        index = body.get("index", "VWRA.L").strip().upper()
        days = min(int(body.get("days", 30)), 3650)

        if not tickers:
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": "At least one ticker is required"}),
            }

        rows, summary = build_table(tickers, index, days)
        chart_b64 = build_chart(tickers, index, days)

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps({"rows": rows, "summary": summary, "chart_base64": chart_b64}),
        }

    except Exception as exc:
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(exc)}),
        }
