#!/usr/bin/env python3
"""
DCF fundamental analyser for stocks.
Estimates intrinsic value per share using a 2-stage DCF model,
and prints key valuation / quality metrics alongside a sensitivity table.

Usage:
    python3 tracker/dcf.py AAPL
    python3 tracker/dcf.py AAPL MSFT GOOGL
    python3 tracker/dcf.py AAPL --discount-rate 0.09 --terminal-growth 0.025
    python3 tracker/dcf.py AAPL --growth-rate 0.15   # override inferred growth
"""

import argparse
import sys
import warnings

import yfinance as yf

warnings.filterwarnings("ignore")

DEFAULT_DISCOUNT_RATE = 0.10  # required return / WACC
DEFAULT_TERMINAL_GROWTH = 0.03  # long-run perpetuity growth (~nominal GDP)
STAGE1_YEARS = 5
STAGE2_YEARS = 5
GROWTH_CAP = 0.40
GROWTH_FLOOR = -0.10


# ── Data layer ────────────────────────────────────────────────────────────────

def _ttm_fcf_from_cashflow(t: yf.Ticker) -> float | None:
    """Sum the 4 most recent quarterly FCF figures as a TTM fallback."""
    try:
        q = t.quarterly_cashflow
        if q is None or q.empty or q.shape[1] < 4:
            return None
        op = q.loc["Operating Cash Flow"].iloc[:4].sum() if "Operating Cash Flow" in q.index else None
        if op is None:
            return None
        capex = q.loc["Capital Expenditure"].iloc[:4].sum() if "Capital Expenditure" in q.index else 0
        return float(op + capex)  # capex is negative in yfinance convention
    except Exception:
        return None


def _analyst_growth(t: yf.Ticker) -> float | None:
    """Try to pull analyst 5-year EPS growth estimate from yfinance."""
    try:
        ge = t.growth_estimates
        if ge is None or ge.empty:
            return None
        for col in ge.columns:
            if "5" in str(col):
                series = ge[col].dropna()
                if not series.empty:
                    val = float(series.iloc[0])
                    if abs(val) <= GROWTH_CAP:
                        return val
    except Exception:
        pass
    return None


def fetch_financials(symbol: str) -> dict:
    t = yf.Ticker(symbol)
    info = t.info

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
    cash = info.get("totalCash") or 0
    debt = info.get("totalDebt") or 0
    fcf = info.get("freeCashflow") or _ttm_fcf_from_cashflow(t)

    # Growth: prefer analyst forward estimate, fall back to trailing metrics
    growth = _analyst_growth(t)
    growth_source = "analyst 5yr EPS estimate"
    if growth is None or abs(growth) > GROWTH_CAP:
        g_earn = info.get("earningsGrowth")
        g_rev = info.get("revenueGrowth")
        growth = g_earn if g_earn is not None else g_rev
        growth_source = "TTM earnings growth" if g_earn is not None else (
            "TTM revenue growth" if g_rev is not None else "default (10%)"
        )
        if growth is None:
            growth = 0.10

    growth = float(max(GROWTH_FLOOR, min(GROWTH_CAP, growth)))

    de = info.get("debtToEquity")  # yfinance returns this as a percentage (150 = 1.5×)

    return {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName", symbol),
        "currency": info.get("currency", "USD"),
        "price": price,
        "shares": shares,
        "cash": cash,
        "debt": debt,
        "fcf": fcf,
        "growth": growth,
        "growth_source": growth_source,
        "market_cap": info.get("marketCap"),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "revenue_growth": info.get("revenueGrowth"),
        "gross_margins": info.get("grossMargins"),
        "operating_margins": info.get("operatingMargins"),
        "profit_margins": info.get("profitMargins"),
        "return_on_equity": info.get("returnOnEquity"),
        "debt_to_equity": de / 100 if de is not None else None,
    }


# ── DCF model ─────────────────────────────────────────────────────────────────

def run_dcf(
    fcf: float,
    shares: float,
    cash: float,
    debt: float,
    growth_s1: float,
    discount_rate: float,
    terminal_growth: float,
) -> dict:
    """
    2-stage DCF.
    Stage 1 (yrs 1–5): user-supplied / inferred growth rate.
    Stage 2 (yrs 6–10): growth decays to halfway between stage 1 and terminal.
    Terminal: Gordon Growth Model at terminal_growth forever.
    Adds net cash (cash – debt) to enterprise value to get equity value.
    """
    growth_s2 = max(terminal_growth, growth_s1 * 0.5)
    growth_s2 = min(growth_s2, discount_rate - 0.01)
    terminal_growth = min(terminal_growth, discount_rate - 0.01)

    pv_s1, pv_s2 = 0.0, 0.0
    cf = fcf

    for yr in range(1, STAGE1_YEARS + 1):
        cf *= (1 + growth_s1)
        pv_s1 += cf / (1 + discount_rate) ** yr

    for yr in range(STAGE1_YEARS + 1, STAGE1_YEARS + STAGE2_YEARS + 1):
        cf *= (1 + growth_s2)
        pv_s2 += cf / (1 + discount_rate) ** yr

    tv = cf * (1 + terminal_growth) / (discount_rate - terminal_growth)
    pv_tv = tv / (1 + discount_rate) ** (STAGE1_YEARS + STAGE2_YEARS)

    ev = pv_s1 + pv_s2 + pv_tv
    equity = ev + cash - debt
    intrinsic = equity / shares

    return {
        "intrinsic": intrinsic,
        "ev": ev,
        "pv_s1": pv_s1,
        "pv_s2": pv_s2,
        "pv_tv": pv_tv,
        "tv_pct": pv_tv / ev * 100 if ev > 0 else None,
        "growth_s1": growth_s1,
        "growth_s2": growth_s2,
        "terminal_growth": terminal_growth,
        "discount_rate": discount_rate,
    }


def build_sensitivity(fin: dict, discount_rate: float, terminal_growth: float) -> dict | None:
    if not (fin["fcf"] and fin["fcf"] > 0 and fin["shares"]):
        return None
    g = fin["growth"]
    growths = [max(GROWTH_FLOOR, g * 0.6), g, min(GROWTH_CAP, g * 1.4)]
    discounts = [discount_rate - 0.01, discount_rate, discount_rate + 0.01]
    table = {
        gr: {
            d: run_dcf(fin["fcf"], fin["shares"], fin["cash"], fin["debt"], gr, d, terminal_growth)["intrinsic"]
            for d in discounts
        }
        for gr in growths
    }
    return {"growths": growths, "discounts": discounts, "table": table}


# ── Formatting helpers ────────────────────────────────────────────────────────

def _cur(currency: str) -> str:
    return {"USD": "$", "GBP": "£", "EUR": "€"}.get(currency, currency + " ")


def _pct(v, d=1) -> str:
    return f"{v * 100:.{d}f}%" if v is not None else "N/A"


def _mul(v, d=1) -> str:
    return f"{v:.{d}f}×" if v is not None else "N/A"


def _money(v, sym, billions=False) -> str:
    if v is None:
        return "N/A"
    if billions:
        return f"{sym}{v / 1e9:.2f}B"
    return f"{sym}{v:,.2f}"


# ── Report printer ────────────────────────────────────────────────────────────

def print_report(fin: dict, result: dict | None, sens: dict | None) -> None:
    W = 62
    c = _cur(fin["currency"])
    price = fin["price"]
    L = 30  # label column width

    print(f"\n{'═' * W}")
    print(f"  {fin['symbol']}  ·  {fin['name']}")
    print(f"{'═' * W}")

    # --- Price & intrinsic value ---
    print(f"\n  PRICE & INTRINSIC VALUE")
    print(f"  {'Current price':<{L}} {_money(price, c)}")

    if result and result["intrinsic"] > 0:
        iv = result["intrinsic"]
        upside = (iv / price - 1) * 100
        mos = (1 - price / iv) * 100
        print(f"  {'DCF intrinsic value':<{L}} {_money(iv, c)}")
        print(f"  {'Upside / (downside)':<{L}} {upside:+.1f}%")
        print(f"  {'Margin of safety':<{L}} {mos:.1f}%")
    else:
        note = "negative or zero FCF — DCF not applicable" if fin["fcf"] is not None and fin["fcf"] <= 0 else "insufficient data"
        print(f"  {'DCF intrinsic value':<{L}} N/A  ({note})")

    # --- Valuation multiples ---
    print(f"\n  VALUATION MULTIPLES")
    print(f"  {'Trailing P/E':<{L}} {_mul(fin['trailing_pe'])}")
    print(f"  {'Forward P/E':<{L}} {_mul(fin['forward_pe'])}")
    print(f"  {'EV / EBITDA':<{L}} {_mul(fin['ev_ebitda'])}")
    if fin["market_cap"] and fin["fcf"] and fin["fcf"] > 0:
        p_fcf = fin["market_cap"] / fin["fcf"]
        fcf_yield = fin["fcf"] / fin["market_cap"] * 100
        print(f"  {'Price / FCF':<{L}} {p_fcf:.1f}×")
        print(f"  {'FCF yield':<{L}} {fcf_yield:.2f}%")

    # --- Quality metrics ---
    print(f"\n  QUALITY METRICS")
    print(f"  {'Revenue growth (TTM)':<{L}} {_pct(fin['revenue_growth'])}")
    print(f"  {'Gross margin':<{L}} {_pct(fin['gross_margins'])}")
    print(f"  {'Operating margin':<{L}} {_pct(fin['operating_margins'])}")
    print(f"  {'Net margin':<{L}} {_pct(fin['profit_margins'])}")
    print(f"  {'Return on equity':<{L}} {_pct(fin['return_on_equity'])}")
    de = fin["debt_to_equity"]
    print(f"  {'Debt / equity':<{L}} {f'{de:.2f}×' if de is not None else 'N/A'}")

    # --- DCF assumptions ---
    if result:
        print(f"\n  DCF ASSUMPTIONS")
        print(f"  {'FCF (TTM)':<{L}} {_money(fin['fcf'], c, billions=True)}")
        print(f"  {'Growth source':<{L}} {fin['growth_source']}")
        print(f"  {'Stage 1 growth  (yrs 1–5)':<{L}} {_pct(result['growth_s1'])}")
        print(f"  {'Stage 2 growth  (yrs 6–10)':<{L}} {_pct(result['growth_s2'])}")
        print(f"  {'Terminal growth rate':<{L}} {_pct(result['terminal_growth'])}")
        print(f"  {'Discount rate (WACC)':<{L}} {_pct(result['discount_rate'])}")
        if result["tv_pct"] is not None:
            print(f"  {'Terminal value % of EV':<{L}} {result['tv_pct']:.0f}%")

    # --- Sensitivity table ---
    if sens:
        col_w = 13
        gs = sens["growths"]
        ds = sens["discounts"]
        tbl = sens["table"]
        labels = ["(bear)", "(base)", "(bull)"]

        print(f"\n  SENSITIVITY  —  intrinsic value ({c}/share)")
        header = f"  {'Growth ↓ / Disc →':<20}" + "".join(f"{d * 100:.0f}% disc".center(col_w) for d in ds)
        print(header)
        print(f"  {'─' * (20 + col_w * len(ds))}")
        for i, g in enumerate(gs):
            label = f"{g * 100:.0f}%  {labels[i]}"
            row = f"  {label:<20}"
            for d in ds:
                v = tbl[g][d]
                cell = f"{c}{v:,.0f}" if v > 0 else "N/A"
                row += cell.center(col_w)
            print(row)

    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def analyse(symbol: str, discount_rate: float, terminal_growth: float, growth_override: float | None) -> None:
    fin = fetch_financials(symbol)

    if growth_override is not None:
        fin["growth"] = float(max(GROWTH_FLOOR, min(GROWTH_CAP, growth_override)))
        fin["growth_source"] = "user-supplied override"

    result = None
    sens = None

    if fin["price"] and fin["shares"] and fin["fcf"] and fin["fcf"] > 0:
        result = run_dcf(
            fcf=fin["fcf"],
            shares=fin["shares"],
            cash=fin["cash"],
            debt=fin["debt"],
            growth_s1=fin["growth"],
            discount_rate=discount_rate,
            terminal_growth=terminal_growth,
        )
        sens = build_sensitivity(fin, discount_rate, terminal_growth)

    print_report(fin, result, sens)


def main() -> None:
    parser = argparse.ArgumentParser(description="DCF fundamental analysis for stocks")
    parser.add_argument("tickers", nargs="+", help="One or more ticker symbols, e.g. AAPL MSFT GOOGL")
    parser.add_argument(
        "--discount-rate", type=float, default=DEFAULT_DISCOUNT_RATE,
        metavar="RATE",
        help=f"Required return / WACC as a decimal (default: {DEFAULT_DISCOUNT_RATE})",
    )
    parser.add_argument(
        "--terminal-growth", type=float, default=DEFAULT_TERMINAL_GROWTH,
        metavar="RATE",
        help=f"Perpetuity growth rate (default: {DEFAULT_TERMINAL_GROWTH})",
    )
    parser.add_argument(
        "--growth-rate", type=float, default=None,
        metavar="RATE",
        help="Override the inferred stage-1 growth rate (e.g. 0.15 for 15%%)",
    )
    args = parser.parse_args()

    for sym in args.tickers:
        try:
            analyse(sym.upper(), args.discount_rate, args.terminal_growth, args.growth_rate)
        except Exception as e:
            print(f"\nERROR — {sym}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
