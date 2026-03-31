# Rules.md - algo-trade-hub-prod Global Operating Manual

## 1. Architectural Constraints (CRITICAL)
- **Database:** All data persistence MUST strictly align with our existing Supabase schema (referencing `migrations/20260223183727_init_trading_schema.sql`). Do NOT implement SQLite or local JSON storage as alternatives.
- **Environment:** Never log API keys, secrets, or database URIs. Fail gracefully if environment variables are missing.

## 2. Rate Limiting & API Constraints
- **Kalshi API:** `time.sleep(1)` is MANDATORY between all calls to prevent rate limiting.
- **yfinance:** One pull per hour maximum (no aggressive rate limit enforcement needed).
- **Circuit Breaker:** If any API is unreachable, catch the exception, log the failure, and halt the immediate execution rather than cascading errors.

## 3. Code Standards
- **Linter:** pylint (strict adherence).
- **Python:** 3.9+.
- **Formatting:** 100 characters max line length.
- **Documentation:** Google-style docstrings are required on all functions and classes.

## 4. Kalshi BTC Sniper Workflow (Non-Negotiable Order)
When working on the retail sniper bot, you must follow this exact execution order:
1. Check PROFITABLE_MATRIX against current Day/Hour.
2. Fetch last 48h BTC data via yfinance.
3. Apply `add_technical_features()`.
4. Inference via `btc_retail_sniper_v1.pkl`.
5. Fetch Kalshi Ask price (with 1s sleep).
6. Run `check_dynamic_trade()` EV math.
7. POST limit order ONLY if EV > 0.