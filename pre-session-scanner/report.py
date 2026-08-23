"""
Turns a scanner result dict into a short written report via the Claude API.

Evidence-first, same as the rest of this tool: the prompt explicitly asks for
a description of conditions, not a directional call — see the design doc's
core principle ("this tool describes market conditions, it does not predict
direction").
"""

import json
import os

import anthropic

MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You are writing a short, tight pre-session market briefing from "
    "structured scan data. Write five parts. Be terse throughout — cut "
    "any sentence that doesn't add a number or a new fact. Target under "
    "240 words total; this is read in the seconds before a trading "
    "session, not studied.\n\n"
    "Part 1 — Conditions: describe the overall market backdrop, not just "
    "the watchlist. Cover, in this order: futures (sp500_futures, "
    "nasdaq_futures — this is where the session opens, not a forecast of "
    "which way it trends afterward; overnight gaps and the rest of the "
    "session's direction are only weakly related historically), "
    "volatility and breadth, cross-asset context (ten_year_yield, "
    "dollar_index — note when either "
    "is a driver for the commodities read below, since a rising dollar or "
    "yields typically pressures gold), commodities (oil, gold), then "
    "anything notable in the screener framed as one input, not the "
    "headline. Reference specific numbers. If a dimension is missing or "
    "empty, say so rather than guessing. You may reference 1-2 "
    "news.headlines items by title if relevant — do not invent URLs or "
    "headlines, don't list them all. 2-3 short paragraphs, max.\n\n"
    "Part 2 — Geopolitical risk factors: 1 sentence. Note any theme "
    "evident from news.geopolitical (a keyword-matched subset of the same "
    "headlines, not a verified classification — a pointer, not a fact). "
    "Oil and gold are unusually geopolitically-driven, weight those more "
    "if present. Reference a headline by title only if it adds something "
    "Part 1 didn't already cover; do not invent URLs. If empty, say so in "
    "one short clause, don't pad it.\n\n"
    "Part 3 — Upcoming events: list each near-term watchlist earnings date "
    "individually from calendar.watchlist_earnings — ticker, date, and its "
    "consensus EPS estimate (eps_estimate_avg, with the low-high range) if "
    "present — never collapse them into just a count. Then give the next "
    "central bank (FOMC) meeting date from calendar.next_fomc_meeting. If "
    "the calendar field is empty or missing, say there's nothing near-term "
    "rather than guessing. Do not invent an analysis_url yourself — it's "
    "rendered separately by the frontend. One line per entry, no preamble.\n\n"
    "Part 4 — Likely near-term bias: give a clear directional call for the "
    "broader market (equities overall — not narrowly the watchlist) "
    "(Bullish / Bearish / Neutral) with a stated confidence level (Low / "
    "Moderate / High), based on pattern-matching across the volatility, "
    "breadth, cross-asset, and commodities metrics above — weight futures "
    "as context for where the session opens, not as a same-day directional "
    "driver (see Part 1), and the watchlist screener as supporting color, "
    "not the basis for this call. This is a heuristic read of the data "
    "provided, not a verified predictive signal with a track record — say "
    "that once, briefly, then give the call plainly without further "
    "hedging. 1-2 sentences, max — the reasoning behind it belongs in "
    "Part 5, not here.\n\n"
    "Part 5 — Key drivers: list the 2-3 specific metrics driving the Part "
    "4 call, one per bullet line as \"- metric: specific reading\", pulling "
    "the exact number from the data rather than just naming the "
    "dimension (e.g. \"- VIX: 15.13, 12th percentile, up from 8.4 two "
    "sessions ago\" not \"- volatility is elevated\"). Each bullet is "
    "evidence for the Part 4 call, not a new claim. 2-3 bullets, no more, "
    "no other text in this part.\n\n"
    "Do not give trading advice or tell the reader to buy, sell, or hold "
    "anything, in any part — describe the bias and its drivers, not an "
    "instruction."
)


def generate_report(result: dict, api_key: str | None = None) -> str:
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Today's pre-session scan data:\n\n{json.dumps(result, indent=2)}",
        }],
    )

    return "".join(block.text for block in response.content if block.type == "text")
