# Product overview

## What SignalDesk does

SignalDesk is a local research application for U.S. equities. It connects three tasks that are usually done separately:

1. identify unusually large daily price moves,
2. investigate public-source explanations for a selected date,
3. organize the company-specific conditions that could strengthen or weaken an investment thesis.

The product is designed for evidence review, not price prediction or automated trading.

## Product principles

### Numbers and interpretation are separate

Price returns, volume ratios and anomaly rules are computed in code. Generative AI is used for public-source research and interpretation. A large price move is therefore a research trigger, not an AI-generated buy or sell signal.

### A future event is not automatically good or bad

Upcoming events are shown separately from already reported positive or negative evidence. Where useful, the UI explains what would constitute a favorable outcome and what would weaken the thesis.

### Company-specific thesis, shared pipeline

The live thesis workflow does not contain fixed answers for individual tickers. It uses one shared research pipeline to describe the business model, the central thesis, material bottlenecks and the evidence that would confirm or break those conditions.

### Failures stay visible

Missing evidence, SEC access limits, stale saved results and AI-formatting failures are not converted into reassuring empty states. The application preserves usable saved results and surfaces uncertainty or failure separately.

### Paid actions are explicit

Price lookup and reading saved analysis do not trigger paid AI calls. Fresh research requires user consent, and paid requests are not automatically retried.

## Current scope

Implemented:

- adjusted daily U.S. equity price history and SPY comparison,
- rule-based anomaly detection,
- date-specific public-source cause research,
- positive / negative evidence and upcoming-event presentation,
- issuer-agnostic investment-thesis research and structuring,
- SEC dilution-related filing signal checks,
- local caching, request limits and explicit failure states.

Not claimed:

- real-time market data,
- complete news coverage,
- independent fact verification of AI summaries,
- target-price or return prediction,
- automatic trading,
- advance prediction of undisclosed financings,
- production multi-user hosting.

## Stack

- Python 3.11
- FastAPI / Uvicorn
- Next.js / React
- OpenAI Responses API
- SQLite and local JSON state
- yfinance / Yahoo Finance adjusted daily data

See [ARCHITECTURE.md](ARCHITECTURE.md) for the application flow and [THESIS_ENGINE.md](THESIS_ENGINE.md) for the two-stage research design.
