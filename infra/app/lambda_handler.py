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

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
    "Content-Type": "application/json",
}

# ── DCF constants ─────────────────────────────────────────────────────────────

DCF_STAGE1_YEARS = 5
DCF_STAGE2_YEARS = 5
DCF_GROWTH_CAP = 0.40
DCF_GROWTH_FLOOR = -0.10


# ── Tracker helpers ───────────────────────────────────────────────────────────

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

    fx = get_period_return(FOREX_PAIR, start_date, end_date)
    gbpusd_start = fx["start_price"]
    gbpusd_end = fx["end_price"]

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

    idx_series = prices[index].dropna()
    idx_indexed = (idx_series / idx_series.iloc[0]) * 100
    ax.plot(idx_indexed.index, idx_indexed.values,
            color="#E63946", linewidth=2.5, linestyle="--", label=f"{index} (benchmark)")

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


# ── DCF helpers ───────────────────────────────────────────────────────────────

def _ttm_fcf(t: yf.Ticker) -> float | None:
    """Sum 4 most-recent quarterly figures as a TTM fallback."""
    try:
        q = t.quarterly_cashflow
        if q is None or q.empty or q.shape[1] < 4:
            return None
        if "Operating Cash Flow" not in q.index:
            return None
        op = float(q.loc["Operating Cash Flow"].iloc[:4].sum())
        capex = float(q.loc["Capital Expenditure"].iloc[:4].sum()) if "Capital Expenditure" in q.index else 0.0
        return op + capex  # capex is negative in yfinance convention
    except Exception:
        return None


def _infer_growth(t: yf.Ticker, info: dict) -> tuple[float, str]:
    """Return (growth_rate, source_label). Prefers analyst 5yr estimate."""
    try:
        ge = t.growth_estimates
        if ge is not None and not ge.empty:
            for col in ge.columns:
                if "5" in str(col):
                    series = ge[col].dropna()
                    if not series.empty:
                        val = float(series.iloc[0])
                        if abs(val) <= DCF_GROWTH_CAP:
                            return val, "analyst 5yr EPS estimate"
    except Exception:
        pass

    g_earn = info.get("earningsGrowth")
    g_rev = info.get("revenueGrowth")
    if g_earn is not None:
        return float(g_earn), "TTM earnings growth"
    if g_rev is not None:
        return float(g_rev), "TTM revenue growth"
    return 0.10, "default (10%)"


def _run_dcf(
    fcf: float,
    shares: float,
    cash: float,
    debt: float,
    growth_s1: float,
    discount_rate: float,
    terminal_growth: float,
) -> float:
    """2-stage DCF. Returns intrinsic value per share."""
    growth_s2 = max(terminal_growth, growth_s1 * 0.5)
    growth_s2 = min(growth_s2, discount_rate - 0.01)
    terminal_growth = min(terminal_growth, discount_rate - 0.01)

    pv = 0.0
    cf = fcf
    for yr in range(1, DCF_STAGE1_YEARS + 1):
        cf *= (1 + growth_s1)
        pv += cf / (1 + discount_rate) ** yr

    pv_s1 = pv
    pv_s2 = 0.0
    for yr in range(DCF_STAGE1_YEARS + 1, DCF_STAGE1_YEARS + DCF_STAGE2_YEARS + 1):
        cf *= (1 + growth_s2)
        disc = cf / (1 + discount_rate) ** yr
        pv += disc
        pv_s2 += disc

    tv = cf * (1 + terminal_growth) / (discount_rate - terminal_growth)
    pv_tv = tv / (1 + discount_rate) ** (DCF_STAGE1_YEARS + DCF_STAGE2_YEARS)
    ev = pv_s1 + pv_s2 + pv_tv
    equity = ev + cash - debt
    return equity / shares, ev, pv_tv


def _analyse_ticker(symbol: str, discount_rate: float, terminal_growth: float, growth_override) -> dict:
    t = yf.Ticker(symbol)
    info = t.info

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
    cash = info.get("totalCash") or 0
    debt = info.get("totalDebt") or 0
    fcf = info.get("freeCashflow") or _ttm_fcf(t)

    if growth_override is not None:
        growth = float(max(DCF_GROWTH_FLOOR, min(DCF_GROWTH_CAP, growth_override)))
        growth_source = "user override"
    else:
        growth, growth_source = _infer_growth(t, info)
        growth = float(max(DCF_GROWTH_FLOOR, min(DCF_GROWTH_CAP, growth)))

    mc = info.get("marketCap")
    de_raw = info.get("debtToEquity")  # yfinance returns as percentage (150 = 1.5×)

    result = {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName", symbol),
        "currency": info.get("currency", "USD"),
        "price": price,
        "fcf_ttm": fcf,
        "growth_s1": growth,
        "growth_source": growth_source,
        "discount_rate": discount_rate,
        "terminal_growth": terminal_growth,
        "market_cap": mc,
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "p_fcf": mc / fcf if (mc and fcf and fcf > 0) else None,
        "fcf_yield": fcf / mc * 100 if (mc and fcf and fcf > 0) else None,
        "revenue_growth": info.get("revenueGrowth"),
        "gross_margins": info.get("grossMargins"),
        "operating_margins": info.get("operatingMargins"),
        "profit_margins": info.get("profitMargins"),
        "return_on_equity": info.get("returnOnEquity"),
        "debt_to_equity": de_raw / 100 if de_raw is not None else None,
        "error": None,
    }

    if price and shares and fcf and fcf > 0:
        intrinsic, ev, pv_tv = _run_dcf(fcf, shares, cash, debt, growth, discount_rate, terminal_growth)
        growth_s2 = max(terminal_growth, growth * 0.5)
        growth_s2 = min(growth_s2, discount_rate - 0.01)

        gs = [max(DCF_GROWTH_FLOOR, growth * 0.6), growth, min(DCF_GROWTH_CAP, growth * 1.4)]
        ds = [round(discount_rate - 0.01, 4), round(discount_rate, 4), round(discount_rate + 0.01, 4)]
        sens_table = {}
        for g in gs:
            row = {}
            for d in ds:
                iv, _, _ = _run_dcf(fcf, shares, cash, debt, g, d, terminal_growth)
                row[f"{d:.4f}"] = round(iv, 2)
            sens_table[f"{g:.4f}"] = row

        result.update({
            "intrinsic": round(intrinsic, 2),
            "upside_pct": round((intrinsic / price - 1) * 100, 1),
            "margin_of_safety": round((1 - price / intrinsic) * 100, 1) if intrinsic > 0 else None,
            "growth_s2": round(growth_s2, 4),
            "tv_pct": round(pv_tv / ev * 100, 0) if ev > 0 else None,
            "sensitivity": {
                "growths": [round(g, 4) for g in gs],
                "discounts": ds,
                "table": sens_table,
            },
        })
    else:
        result.update({
            "intrinsic": None,
            "upside_pct": None,
            "margin_of_safety": None,
            "growth_s2": None,
            "tv_pct": None,
            "sensitivity": None,
        })

    return result


# ── Route handlers ────────────────────────────────────────────────────────────

def handle_report(body: dict) -> dict:
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


def handle_dcf(body: dict) -> dict:
    tickers = [t.strip().upper() for t in body.get("tickers", []) if t.strip()]
    discount_rate = float(body.get("discount_rate", 0.10))
    terminal_growth = float(body.get("terminal_growth", 0.03))
    growth_override = body.get("growth_rate")
    if growth_override is not None:
        growth_override = float(growth_override)

    if not tickers:
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "At least one ticker is required"}),
        }

    results = []
    for sym in tickers:
        try:
            results.append(_analyse_ticker(sym, discount_rate, terminal_growth, growth_override))
        except Exception as e:
            results.append({"symbol": sym, "error": str(e)})

    return {
        "statusCode": 200,
        "headers": CORS_HEADERS,
        "body": json.dumps({"results": results}),
    }


# ── Lambda entry point ────────────────────────────────────────────────────────

def handler(event, context):
    method = (event.get("requestContext") or {}).get("http", {}).get("method", "")
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    try:
        body = json.loads(event.get("body") or "{}")
        path = event.get("rawPath", "/")

        if path.rstrip("/").endswith("/dcf"):
            return handle_dcf(body)

        return handle_report(body)

    except Exception as exc:
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(exc)}),
        }
