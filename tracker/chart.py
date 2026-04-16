#!/usr/bin/env python3
"""
Time-series chart: basket of stocks vs VWRA.L index.
Each series is indexed to 100 at the start of the period.
USD-denominated stocks are converted to GBP terms using daily GBPUSD rates.

Usage:
    python3 chart.py --basket tech-us
    python3 chart.py --basket commodities
"""

import argparse
import json
import pathlib
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
from datetime import date, timedelta


INDEX = "VWRA.L"
FOREX_PAIR = "GBPUSD=X"
LOOKBACK_DAYS = 30
MAX_DAYS = 3650
BASKETS_FILE = pathlib.Path(__file__).parent / "baskets.json"

PALETTE = [
    "#00A4EF", "#1877F2", "#FF9900", "#2ECC71",
    "#9B59B6", "#E67E22", "#1ABC9C", "#E74C3C",
]
INDEX_STYLE = dict(color="#E63946", linewidth=2.5, linestyle="--", label=f"{INDEX} (benchmark)")


def load_basket(basket_id: str) -> dict:
    data = json.loads(BASKETS_FILE.read_text())
    for basket in data["baskets"]:
        if basket["id"] == basket_id:
            return basket
    ids = [b["id"] for b in data["baskets"]]
    raise ValueError(f"Basket '{basket_id}' not found. Available: {ids}")


def fetch_closes(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    raw = yf.download(
        tickers,
        start=start,
        end=end + timedelta(days=1),
        progress=False,
        auto_adjust=True,
    )
    if len(tickers) == 1:
        closes = raw["Close"].rename(tickers[0])
        return closes.to_frame()
    return raw["Close"].dropna(how="all")


def to_indexed(series: pd.Series) -> pd.Series:
    clean = series.dropna()
    return (clean / clean.iloc[0]) * 100


def apply_forex(price_series: pd.Series, gbpusd: pd.Series) -> pd.Series:
    fx = gbpusd.reindex(price_series.index).ffill()
    return price_series / fx


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


def main():
    parser = argparse.ArgumentParser(description="Chart basket performance vs VWRA.L")
    parser.add_argument("--basket", required=True, help="Basket ID from baskets.json")
    parser.add_argument("--days", type=int, default=LOOKBACK_DAYS,
                        help=f"Lookback window in days (default: {LOOKBACK_DAYS}, max: {MAX_DAYS})")
    args = parser.parse_args()

    days = min(args.days, MAX_DAYS)
    basket = load_basket(args.basket)
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    symbols = [t["symbol"] for t in basket["tickers"]]
    currencies = {t["symbol"]: t["currency"] for t in basket["tickers"]}

    all_tickers = symbols + [INDEX, FOREX_PAIR]

    prices = fetch_closes(all_tickers, start_date, end_date)
    gbpusd = prices[FOREX_PAIR].dropna()

    fig, ax = plt.subplots(figsize=(11, 6))

    # --- Index ---
    ax.plot(prices[INDEX].dropna().pipe(to_indexed), **INDEX_STYLE)

    # --- Basket tickers ---
    for i, symbol in enumerate(symbols):
        series = prices[symbol].dropna()
        if currencies[symbol] == "USD":
            series = apply_forex(series, gbpusd)
        indexed = to_indexed(series)
        color = PALETTE[i % len(PALETTE)]
        suffix = " (GBP-adj)" if currencies[symbol] == "USD" else ""
        ax.plot(indexed.index, indexed.values, color=color, linewidth=1.8, label=f"{symbol}{suffix}")

    # --- Formatting ---
    ax.axhline(100, color="grey", linewidth=0.8, linestyle=":")
    ax.set_title(
        f"{basket['name']}  vs  {INDEX}  ·  {start_date} → {end_date}  (indexed to 100)",
        fontsize=13,
        pad=12,
    )
    ax.set_ylabel("Indexed return (100 = start)", fontsize=11)
    _configure_xaxis(ax, days)
    plt.xticks(rotation=30, ha="right")
    ax.legend(fontsize=10)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)

    plt.tight_layout()
    out_path = f"performance_chart_{basket['id']}.png"
    plt.savefig(out_path, dpi=150)
    print(f"Chart saved to {out_path}")
    plt.show()


if __name__ == "__main__":
    main()
