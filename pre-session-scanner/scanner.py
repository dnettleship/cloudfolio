#!/usr/bin/env python3
"""
Pre-session market conditions scanner — Phase 1 MVP.

Evidence, not verdicts: every dimension below reports a level and a
percentile against its own trailing history, never a blended directional
score. See pre-session-equity-tool-design.md for the full design.

Phase 1 scope (yfinance-only, no paid sources yet):
  - Volatility:  VIX level + 1y percentile
  - Breadth:     % of the watchlist above its 50-day moving average
                 (a watchlist-based proxy, not full index breadth — see
                 design doc Phase 3)
  - Commodities: oil/gold price percentile + realized-vol percentile,
                 plus a trailing 90-session price history for charting
  - Screener:    overnight gap % and 5-day relative strength vs benchmark,
                 for the static watchlist
  - News:        recent headlines for the benchmark, VIX, oil and gold —
                 informational only, like screener, not part of the
                 publish gate. Scoped to these four tickers rather than
                 the whole watchlist to keep the yfinance call count
                 bounded (see build_result)

Usage:
    python3 scanner.py                    # JSON summary to stdout, writes dashboard.html
    python3 scanner.py --run-type pre-open
"""

import argparse
import datetime
import json
import pathlib
import sys

import yfinance as yf

import dashboard

CONFIG_FILE = pathlib.Path(__file__).parent / "watchlist.json"
HISTORY_DIR = pathlib.Path(__file__).parent / "history"
DASHBOARD_FILE = pathlib.Path(__file__).parent / "dashboard.html"


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text())


def fetch_history(ticker: str, period: str = "1y"):
    return yf.download(ticker, period=period, progress=False, auto_adjust=True)


def percentile_rank(series, value: float) -> float:
    """% of historical observations at or below the current value."""
    return round(float((series <= value).mean()) * 100, 1)


def volatility_dimension(vix_ticker: str) -> dict:
    close = fetch_history(vix_ticker)["Close"].squeeze().dropna()
    current = float(close.iloc[-1])
    prior = float(close.iloc[-3]) if len(close) >= 3 else None
    return {
        "level": round(current, 2),
        "percentile_1y": percentile_rank(close, current),
        "percentile_1y_2_sessions_ago": (
            percentile_rank(close.iloc[:-2], prior) if prior is not None else None
        ),
    }


def breadth_dimension(tickers: list) -> dict:
    above, total = 0, 0
    for ticker in tickers:
        close = fetch_history(ticker, period="6mo")["Close"].squeeze().dropna()
        if len(close) < 50:
            continue
        total += 1
        if float(close.iloc[-1]) > float(close.rolling(50).mean().iloc[-1]):
            above += 1
    return {
        "pct_above_50dma": round(above / total * 100, 1) if total else None,
        "universe_size": total,
        "note": "watchlist-based proxy, not full index breadth",
    }


def commodity_dimension(ticker: str) -> dict:
    close = fetch_history(ticker)["Close"].squeeze().dropna()
    current = float(close.iloc[-1])
    realized_vol = close.pct_change().dropna().rolling(20).std() * (252 ** 0.5)
    realized_vol = realized_vol.dropna()
    current_vol = float(realized_vol.iloc[-1])
    trend = close.tail(90)
    return {
        "price": round(current, 2),
        "price_percentile_1y": percentile_rank(close, current),
        "realized_vol_annualized_pct": round(current_vol * 100, 1),
        "realized_vol_percentile_1y": percentile_rank(realized_vol, current_vol),
        "price_history": [
            {"date": d.strftime("%Y-%m-%d"), "close": round(float(v), 2)}
            for d, v in trend.items()
        ],
    }


def news_dimension(vix_ticker: str, benchmark: str, commodities: dict, limit: int = 8) -> list:
    """Recent headlines for market-wide tickers.

    Scoped to the benchmark, VIX, oil and gold — not the full watchlist —
    to keep the yfinance call count bounded (build_result already makes
    roughly two calls per watchlist ticker for breadth and screener).
    """
    tickers = [benchmark, vix_ticker, commodities["oil"], commodities["gold"]]
    seen_titles = set()
    items = []
    for ticker in tickers:
        try:
            raw = yf.Ticker(ticker).news or []
        except Exception:
            continue
        for entry in raw:
            content = entry.get("content", {})
            title = content.get("title")
            link = (content.get("clickThroughUrl") or {}).get("url")
            if not title or not link or title in seen_titles:
                continue
            seen_titles.add(title)
            items.append({
                "title": title,
                "link": link,
                "publisher": (content.get("provider") or {}).get("displayName"),
                "published": content.get("pubDate"),
                "related_ticker": ticker,
            })

    items.sort(key=lambda i: i["published"] or "", reverse=True)
    return items[:limit]


def screener(tickers: list, benchmark: str) -> list:
    bench_close = fetch_history(benchmark, period="1mo")["Close"].squeeze().dropna()
    bench_return_5d = (
        float(bench_close.iloc[-1] / bench_close.iloc[-6] - 1)
        if len(bench_close) >= 6 else None
    )

    rows = []
    for ticker in tickers:
        data = fetch_history(ticker, period="1mo")
        close = data["Close"].squeeze().dropna()
        open_ = data["Open"].squeeze().dropna()
        if len(close) < 2:
            continue

        gap_pct = round(float(open_.iloc[-1] / close.iloc[-2] - 1) * 100, 2)
        return_5d = (
            float(close.iloc[-1] / close.iloc[-6] - 1) if len(close) >= 6 else None
        )
        rel_strength_pp = (
            round((return_5d - bench_return_5d) * 100, 2)
            if return_5d is not None and bench_return_5d is not None else None
        )
        rows.append({
            "ticker": ticker,
            "gap_pct": gap_pct,
            "return_5d_pct": round(return_5d * 100, 2) if return_5d is not None else None,
            "relative_strength_vs_benchmark_pp": rel_strength_pp,
        })

    rows.sort(key=lambda r: r["relative_strength_vs_benchmark_pp"] or float("-inf"), reverse=True)
    return rows


def build_result(run_type: str) -> tuple[dict, bool]:
    """Run all dimensions and apply the (Phase 1, trivial) publish gate.

    Shared by the CLI (main, below) and the Lambda handler
    (infra/pre-session-scanner/app/lambda_handler.py) so the two never
    drift apart.
    """
    config = load_config()
    result = {"date": datetime.date.today().isoformat(), "run_type": run_type}
    errors = []

    for key, fn in [
        ("volatility", lambda: volatility_dimension(config["vix_ticker"])),
        ("breadth", lambda: breadth_dimension(config["tickers"])),
        ("commodities", lambda: {
            "oil": commodity_dimension(config["commodities"]["oil"]),
            "gold": commodity_dimension(config["commodities"]["gold"]),
        }),
        ("screener", lambda: screener(config["tickers"], config["benchmark"])),
        ("news", lambda: news_dimension(config["vix_ticker"], config["benchmark"], config["commodities"])),
    ]:
        try:
            result[key] = fn()
        except Exception as exc:
            errors.append(f"{key}: {exc}")

    # Publish gate (trivial for Phase 1): volatility, breadth, and
    # commodities are required — screener and news are informational only.
    required_ok = all(k in result for k in ("volatility", "breadth", "commodities"))
    result["publish_ok"] = required_ok
    if errors:
        result["errors"] = errors

    return result, required_ok


def main():
    parser = argparse.ArgumentParser(description="Pre-session market conditions scanner")
    parser.add_argument("--run-type", default="manual", help="Tag for this run, e.g. uk-morning, pre-open")
    args = parser.parse_args()

    result, required_ok = build_result(args.run_type)

    if required_ok:
        HISTORY_DIR.mkdir(exist_ok=True)
        (HISTORY_DIR / f"{result['date']}-{args.run_type}.json").write_text(json.dumps(result, indent=2))
        dashboard.write(result, DASHBOARD_FILE)
    else:
        print("Publish gate failed — required data missing, snapshot/dashboard not updated", file=sys.stderr)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
