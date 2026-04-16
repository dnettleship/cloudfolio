# Stock Basket Tracker

Compares the returns of a chosen basket of stocks against the VWRA.L index over a rolling 30-day period, with GBP/USD forex adjustments applied per-ticker to USD-denominated holdings.

## Usage

```bash
python3 tracker.py --basket <id>
python3 chart.py --basket <id>
```

`tracker.py` prints a JSON summary to stdout. `chart.py` renders a time-series chart and saves it as `performance_chart_<id>.png`.

Available basket IDs are defined in [baskets.json](baskets.json).

## Baskets

Baskets are stored in [baskets.json](baskets.json) — edit that file to add tickers or create new baskets without touching the scripts. Each basket entry looks like:

```jsonc
{
  "id": "tech-us",         // used as the --basket argument
  "name": "US Tech",       // displayed in chart titles and JSON output
  "tickers": [
    { "symbol": "MSFT", "currency": "USD" },
    { "symbol": "LITG.L", "currency": "GBP" }
  ]
}
```

`currency` must be `"USD"` or `"GBP"`. GBP-denominated tickers are passed through unchanged; USD tickers have the forex adjustment applied.

### Current baskets

| ID | Name | Tickers |
|---|---|---|
| `tech-us` | US Tech | MSFT, META, AMZN |
| `commodities` | Commodities & Resources | LITG.L, COPX.L, SRUUF, SGLN.L |

## Forex adjustment

The index (VWRA.L) is GBP-denominated. For USD-denominated tickers, returns are converted to GBP using daily GBPUSD rates so all series are comparable:

```
GBP return = (end_price / start_price) × (GBPUSD_start / GBPUSD_end) − 1
```

If GBP strengthens over the period (`GBPUSD_end > GBPUSD_start`), it drags down the GBP-equivalent return of USD holdings, and vice versa. The `forex_adjustment_pp` field quantifies this effect in percentage points. It is `null` for GBP-denominated tickers.

In `chart.py` the same adjustment is applied daily so the indexed series reflects true GBP returns throughout the period, not just at start and end.

## Output schema (`tracker.py`)

```jsonc
{
  "basket": {
    "id":   "tech-us",
    "name": "US Tech"
  },
  "period": {
    "requested_start": "YYYY-MM-DD",  // 30 days before today
    "requested_end":   "YYYY-MM-DD"   // today
  },
  "forex": {
    "pair":       "GBPUSD=X",
    "start":      1.3314,
    "end":        1.3570,
    "change_pct": 1.9228
  },
  "basket_avg_return_gbp_pct": 6.7107,  // equal-weighted avg of basket in GBP
  "index_return_gbp_pct":      4.0371,  // VWRA.L return over the period
  "basket_vs_index_pp":        2.6736,  // basket avg minus index (pp)
  "rows": [ /* one entry per ticker — see table below */ ]
}
```

### Row fields

| Field | Description |
|---|---|
| `ticker` | Yahoo Finance ticker symbol |
| `currency` | Native currency as defined in `baskets.json` |
| `start_price` | Closing price on the first trading day in the window |
| `end_price` | Closing price on the last trading day in the window |
| `actual_start` | Date of the `start_price` observation |
| `actual_end` | Date of the `end_price` observation |
| `return_local_pct` | Return in the ticker's native currency (%) |
| `return_gbp_pct` | Return in GBP after forex adjustment (%) |
| `vs_index_pp` | `return_gbp_pct` minus the index GBP return (percentage points) |
| `forex_adjustment_pp` | `return_gbp_pct` minus `return_local_pct` — the forex drag/boost (pp). `null` for GBP tickers. |

## Dependencies

- [yfinance](https://ranaroussi.github.io/yfinance/) — market data
- `matplotlib` — charting (`chart.py` only)
- `json`, `datetime`, `pathlib`, `argparse` — standard library
