#!/usr/bin/env python3
"""
Stock basket vs index tracker.
Compares returns of a chosen basket against VWRA.L over a given period,
accounting for GBP/USD forex fluctuations for USD-denominated stocks.

Usage:
    python3 tracker.py --basket tech-us
    python3 tracker.py --basket commodities
"""

import argparse
import json
import pathlib
import yfinance as yf
from datetime import date, timedelta


INDEX = "VWRA.L"
FOREX_PAIR = "GBPUSD=X"
BASKETS_FILE = pathlib.Path(__file__).parent / "baskets.json"


def load_basket(basket_id: str) -> dict:
    data = json.loads(BASKETS_FILE.read_text())
    for basket in data["baskets"]:
        if basket["id"] == basket_id:
            return basket
    ids = [b["id"] for b in data["baskets"]]
    raise ValueError(f"Basket '{basket_id}' not found. Available: {ids}")


def get_period_return(ticker: str, start: date, end: date) -> dict:
    """Fetch start/end prices and calculate simple return for a ticker."""
    data = yf.download(ticker, start=start, end=end + timedelta(days=1), progress=False, auto_adjust=True)
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


def main():
    parser = argparse.ArgumentParser(description="Compare a basket of stocks against VWRA.L")
    parser.add_argument("--basket", required=True, help="Basket ID from baskets.json")
    args = parser.parse_args()

    basket = load_basket(args.basket)
    end_date = date.today()
    start_date = end_date - timedelta(days=30)

    results = []

    # --- Index ---
    index_data = get_period_return(INDEX, start_date, end_date)
    index_return_pct = index_data["return_local_pct"]
    results.append({
        "ticker": INDEX,
        "currency": "GBP",
        "start_price": index_data["start_price"],
        "end_price": index_data["end_price"],
        "actual_start": index_data["actual_start"],
        "actual_end": index_data["actual_end"],
        "return_local_pct": index_return_pct,
        "return_gbp_pct": index_return_pct,
        "vs_index_pp": 0.0,
        "forex_adjustment_pp": None,
    })

    # --- Forex ---
    fx_data = get_period_return(FOREX_PAIR, start_date, end_date)
    gbpusd_start = fx_data["start_price"]
    gbpusd_end = fx_data["end_price"]

    # --- Basket tickers ---
    symbols = [t["symbol"] for t in basket["tickers"]]
    currencies = {t["symbol"]: t["currency"] for t in basket["tickers"]}

    for symbol in symbols:
        stock_data = get_period_return(symbol, start_date, end_date)
        currency = currencies[symbol]

        if currency == "USD":
            local_return_factor = stock_data["end_price"] / stock_data["start_price"]
            forex_factor = gbpusd_start / gbpusd_end
            gbp_return_pct = round((local_return_factor * forex_factor - 1) * 100, 4)
            forex_adj_pp = round(gbp_return_pct - stock_data["return_local_pct"], 4)
        else:
            # Already GBP-denominated — no adjustment needed
            gbp_return_pct = stock_data["return_local_pct"]
            forex_adj_pp = None

        results.append({
            "ticker": symbol,
            "currency": currency,
            "start_price": stock_data["start_price"],
            "end_price": stock_data["end_price"],
            "actual_start": stock_data["actual_start"],
            "actual_end": stock_data["actual_end"],
            "return_local_pct": stock_data["return_local_pct"],
            "return_gbp_pct": gbp_return_pct,
            "vs_index_pp": round(gbp_return_pct - index_return_pct, 4),
            "forex_adjustment_pp": forex_adj_pp,
        })

    basket_gbp_returns = [r["return_gbp_pct"] for r in results if r["ticker"] in symbols]
    basket_avg = round(sum(basket_gbp_returns) / len(basket_gbp_returns), 4)

    summary = {
        "basket": {"id": basket["id"], "name": basket["name"]},
        "period": {
            "requested_start": str(start_date),
            "requested_end": str(end_date),
        },
        "forex": {
            "pair": FOREX_PAIR,
            "start": gbpusd_start,
            "end": gbpusd_end,
            "change_pct": round((gbpusd_end / gbpusd_start - 1) * 100, 4),
        },
        "basket_avg_return_gbp_pct": basket_avg,
        "index_return_gbp_pct": index_return_pct,
        "basket_vs_index_pp": round(basket_avg - index_return_pct, 4),
        "rows": results,
    }

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
