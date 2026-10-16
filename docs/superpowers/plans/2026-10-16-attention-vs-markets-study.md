# Do Wikipedia Pageviews and Google Trends Move Kalshi Markets?

> **Status: design plan, not code-verified. A running study, not a forecaster.** Start only after the order-book snapshots have about 3 weeks of data (2026-11-01).

**Question:** When public attention to a market's subject spikes, does the market's price move afterwards, by enough to beat fees?

## Data (free, keyless, checked 2026-10-16)
- Wikipedia daily pageviews: `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/<Article>/daily/<YYYYMMDD>/<YYYYMMDD>` (verified, JSON).
- Google Trends: no official API. `pytrends` is unofficial and rate-limited; treat it as optional and skip it if it breaks. Start with Wikipedia only.
- Kalshi prices: the public candles API (history) plus our own hourly snapshots under `/cache/orderbooks` on the VPS.

## Design (lazy version first)
1. **Pick the universe:** Kalshi series whose subject is a named thing with a Wikipedia page (people, films, artists, teams, countries, companies, events: entertainment, politics, sports props, some economics). A hand-written `series -> article` map of about 20 series is enough to start; do not build entity linking.
2. **Spike definition, fixed in advance:** a day's views over 3x the trailing 28-day median. Record every spike with its date and article.
3. **Outcome:** for each spike, the change in the related markets' mid price from the spike day's close to +1, +3 and +7 days, and the same for matched non-spike days (same series, same weekday) as the control.
4. **Statistics:** event-clustered standard errors, a time split (find on the earlier 70%, report on the later 30%), the count of definitions tried, and costs (taker fee and half spread from candles or snapshots). The deliverable is a table plus a verdict, same format as the calibration study (`2026-10-06-market-calibration-study.md`).
5. **Automate lightly:** a daily job on the VPS that appends the day's pageviews for the mapped articles to a small table or JSONL file; the analysis is run on demand. No page, no forecaster, until a spike rule survives costs out of sample.

**A negative result is a complete answer.** Report n spikes, n clusters and the interval for every cell.
