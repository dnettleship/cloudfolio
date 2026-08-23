"""
Renders a scanner result dict to a simple static HTML dashboard.

Deliberately plain for now — no gauges/sparklines (that's Phase 4 in the
design doc). Evidence-first: shows level + percentile for each dimension,
never a blended score.
"""

import html


def _cls(value) -> str:
    if value is None:
        return ""
    return "pos" if value >= 0 else "neg"


def _fmt(value, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value}{suffix}"


def render(result: dict) -> str:
    vol = result.get("volatility", {})
    breadth = result.get("breadth", {})
    commodities = result.get("commodities", {})
    screener_rows = result.get("screener", [])

    screener_html = "".join(
        f"""
        <tr>
          <td>{html.escape(row['ticker'])}</td>
          <td class="{_cls(row['gap_pct'])}">{_fmt(row['gap_pct'], '%')}</td>
          <td class="{_cls(row['return_5d_pct'])}">{_fmt(row['return_5d_pct'], '%')}</td>
          <td class="{_cls(row['relative_strength_vs_benchmark_pp'])}">{_fmt(row['relative_strength_vs_benchmark_pp'], ' pp')}</td>
        </tr>"""
        for row in screener_rows
    )

    def commodity_block(name: str, c: dict) -> str:
        return f"""
        <div class="stat">
          <div class="stat-label">{name}</div>
          <div class="stat-value">{_fmt(c.get('price'))}</div>
          <div class="stat-sub">price pct (1y): {_fmt(c.get('price_percentile_1y'))} &middot;
            realized vol: {_fmt(c.get('realized_vol_annualized_pct'), '%')}
            (pct {_fmt(c.get('realized_vol_percentile_1y'))})</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>Pre-session scanner</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          background: #f4f5f7; color: #1a1a2e; padding: 24px; }}
  h1 {{ font-size: 1.3rem; margin-bottom: 4px; }}
  .meta {{ color: #6b7280; font-size: 0.85rem; margin-bottom: 20px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 20px; }}
  .card {{ background: #fff; border-radius: 10px; padding: 18px 20px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .card h2 {{ font-size: 0.72rem; font-weight: 600; color: #6b7280; text-transform: uppercase;
              letter-spacing: 0.05em; margin-bottom: 10px; }}
  .stat-value {{ font-size: 1.4rem; font-weight: 700; }}
  .stat-sub {{ font-size: 0.8rem; color: #6b7280; margin-top: 4px; }}
  .stat-label {{ font-size: 0.72rem; color: #6b7280; font-weight: 600; text-transform: uppercase; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden;
           box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  th, td {{ padding: 9px 14px; text-align: right; font-size: 0.9rem; }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{ font-size: 0.72rem; color: #6b7280; text-transform: uppercase; border-bottom: 2px solid #f3f4f6; }}
  tr:not(:last-child) td {{ border-bottom: 1px solid #f3f4f6; }}
  .pos {{ color: #16a34a; }}
  .neg {{ color: #dc2626; }}
</style>
</head>
<body>

<h1>Pre-session scanner</h1>
<div class="meta">{html.escape(result.get('date', ''))} &middot; {html.escape(result.get('run_type', ''))}</div>

<div class="grid">
  <div class="card">
    <h2>Volatility</h2>
    <div class="stat-value">VIX {_fmt(vol.get('level'))}</div>
    <div class="stat-sub">percentile (1y): {_fmt(vol.get('percentile_1y'))} &middot;
      2 sessions ago: {_fmt(vol.get('percentile_1y_2_sessions_ago'))}</div>
  </div>
  <div class="card">
    <h2>Breadth (watchlist proxy)</h2>
    <div class="stat-value">{_fmt(breadth.get('pct_above_50dma'), '%')} above 50DMA</div>
    <div class="stat-sub">{_fmt(breadth.get('universe_size'))} tickers in universe</div>
  </div>
  <div class="card">{commodity_block('Oil', commodities.get('oil', {}))}</div>
  <div class="card">{commodity_block('Gold', commodities.get('gold', {}))}</div>
</div>

<table>
  <thead>
    <tr><th>Ticker</th><th>Gap</th><th>5d return</th><th>Rel. strength</th></tr>
  </thead>
  <tbody>{screener_html}
  </tbody>
</table>

</body>
</html>
"""


def write(result: dict, path) -> None:
    path.write_text(render(result))
