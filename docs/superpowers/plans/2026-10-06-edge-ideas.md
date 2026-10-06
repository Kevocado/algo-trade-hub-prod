# Edge Ideas Worth Testing (free public data)

Each idea below is a cheap probe first: fetch free data, line it up against Kalshi's price at a fixed horizon, and run the same replay method as the calibration study. Only an idea that beats the market price out of sample, after fees, becomes a journal forecaster. Ranked by how likely it is to work and how cheap it is to try.

| # | Idea | Free data | Why it might work | First probe |
|---|------|-----------|-------------------|-------------|
| 1 | Longshot and favorite bias | our own and Kalshi's settled history | Betting markets overprice longshots; needs no model | the calibration study |
| 2 | Gas prices from futures | EIA weekly, AAA, free RBOB/crude futures | Wholesale leads retail with a known lag; our model lost 4x, which suggests a bug rather than no signal | debug why gas loses, then refit on futures lag |
| 3 | TSA daily throughput | TSA publishes daily checkpoint numbers | Strong weekly and holiday seasonality, fewer sharp traders | day-of-week and holiday baseline vs Kalshi |
| 4 | Weekly jobless claims | DOL weekly release | Strong time pattern, easy baseline, markets thin | seasonal baseline vs Kalshi |
| 5 | Weather: ensemble spread | NOAA NBM, HRRR, station history | Calibrated probabilities from ensembles beat a point forecast | replace the point forecast with an ensemble quantile model, calibrate on past misses |
| 6 | GDPNow for GDP markets | Atlanta Fed | A public nowcast with a known error, like our CPI one | compare nowcast-implied probability with the market near close |
| 7 | Hurricane and storm tracks | National Hurricane Center | Official probabilities that markets may lag | track cone vs Kalshi storm markets |
| 8 | Fed funds futures vs rate markets | CME delayed data, FRED | A cross-venue check; arbitrage-style, not forecasting | compare implied probabilities daily |
| 9 | Box office and streaming charts | public daily figures, Google Trends, Wikipedia pageviews | Under-modelled, weak signal | one title, one weekend, fit a simple growth curve |

## What would change the answer

- A source that is also what the market is already using (CPI nowcast, Fed futures) gives no edge. Prefer data the market reads slowly.
- Fees: Kalshi's taker fee is 7% of price times (1 - price), about 1.7 cents at 50%. Edges under about 2 points at mid prices disappear.
- Sample size: a daily series needs about 200 settled days to judge; a monthly one about 50. Replay history first (as `journal/replay.py` does for the daily models) so there is an out-of-sample answer on day one, and label it "not counted".

## Order of work

1. Calibration study (`2026-10-06-market-calibration-study.md`).
2. Debug gas (idea 2), because the loss pattern says a fix is likely.
3. One slow, thin market (TSA or jobless claims) as the first new forecaster family.
4. Everything else only if one of the above works.
