# Maker-Fill Study at the Price Extremes

> **Status: design plan, not code-verified. Start on or after 2026-11-08** (about a month of order-book snapshots).

**Question:** Would a resting maker order at the extremes (YES priced at or under 5 cents, or at or over 95 cents) have filled, and did it fill only when the price was about to move against it? Taker trades there lose to fees, but maker fees are zero on standard series, so a fill can be profitable even if the edge is one cent.

**Data:** `/opt/stack/volumes/tradehub-cache/orderbooks/<date>/<hour>.jsonl.gz` on the VPS (hourly top of book for every traded market closing within 3 days, plus full books for up to 300 extreme-priced markets), paired with the public trade tape (`KalshiHistoryClient.trades`) and the settled result. Note each file is `truncated: true` when the listing hit its page limit: report the share of markets covered.

**Method:**
1. For each snapshot-market at an extreme, place a hypothetical resting order at the best bid (buy) or best ask (sell) of the NO/YES side that earns the favorite-longshot lean.
2. A fill requires the trade tape to show a trade at or through that price within the next hour (conservative: queue position unknown, so also report the stricter case of a trade strictly through the price).
3. P&L of filled orders to settlement; the adverse-selection check is the fill rate and the P&L conditional on fill, against unfilled orders' hypothetical P&L. If filled orders lose more than unfilled would have, the edge is adverse selection, not an edge.
4. Event-clustered intervals, a time split, a count of variants tried, capacity (size at the touch).

**Deliverable:** a report in the format of the calibration study, with a plain verdict and what would falsify it live. No orders are placed by this repo; if the study shows a rule, it is registered as a journal forecaster so it is graded live first.
