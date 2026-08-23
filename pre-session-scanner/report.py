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
    "You are writing a short pre-session market briefing from structured scan "
    "data. Write four parts.\n\n"
    "Part 1 — Conditions: describe the overall market backdrop, not just the "
    "watchlist. Reference specific numbers from the data provided. If a "
    "dimension is missing or empty, say so rather than guessing at it. "
    "Cover: overall regime (volatility, breadth), commodities (oil, gold), "
    "then anything notable in the screener — but frame the screener as one "
    "input into the broader picture, not the headline. If news.headlines "
    "has items relevant to the watchlist or commodities, you may reference "
    "1-2 of them by title — do not invent URLs or headlines, and don't "
    "list them all, just weave in what's actually decision-relevant. "
    "3-4 short paragraphs.\n\n"
    "Part 2 — Geopolitical risk factors: note any geopolitical themes "
    "evident from news.geopolitical (a keyword-matched subset of the same "
    "headlines, not a verified classification — treat it as a pointer, not "
    "a fact). Oil and gold are unusually geopolitically-driven, so weight "
    "those more if present. Reference 1-2 by title if relevant; do not "
    "invent URLs or headlines. If news.geopolitical is empty, say there's "
    "nothing notable rather than guessing. 1-2 sentences.\n\n"
    "Part 3 — Upcoming events: list each near-term watchlist earnings date "
    "individually from calendar.watchlist_earnings — ticker, date, and its "
    "consensus EPS estimate (eps_estimate_avg, with the low-high range) if "
    "present — never collapse them into just a count. Then give the next "
    "central bank (FOMC) meeting date from calendar.next_fomc_meeting. If "
    "the calendar field is empty or missing, say there's nothing near-term "
    "rather than guessing. Do not invent an analysis_url yourself — it's "
    "rendered separately by the frontend. Keep each entry to one line.\n\n"
    "Part 4 — Likely near-term bias: give a clear directional call for the "
    "broader market (equities overall — not narrowly the watchlist) "
    "(Bullish / Bearish / Neutral) with a stated confidence level (Low / "
    "Moderate / High), based on pattern-matching across the volatility, "
    "breadth, and commodities metrics above — the watchlist screener is "
    "supporting color, not the basis for this call. Name the 2-3 metrics "
    "driving the call. This is a heuristic read of the data provided, not "
    "a verified predictive signal with a track record — say that once, "
    "briefly, then give the call plainly without further hedging.\n\n"
    "Do not give trading advice or tell the reader to buy, sell, or hold "
    "anything — describe the bias, not an instruction. Keep the whole "
    "report readable in under a minute — this is read right before a "
    "trading session."
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
