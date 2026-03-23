# CLAUDE CODE CLI PROMPT (Copy & Paste This Exactly)

---

## PART 1: INITIAL CONTEXT SETTING

```
I need you to completely rebuild this Kalshi prediction market analytics system. 

Read ARCHITECTURE.md in the project root - this contains the complete specification.

CRITICAL CONTEXT:
- Current state: Uses yfinance (delayed data), prioritizes SPX/BTC prediction (no real edge)
- Goal state: Weather/Macro arbitrage using official APIs (NWS, FRED), AI-validated trades
- The SPX/BTC models should become "paper trading only" educational projects
- All real money opportunities must come from markets where free data = settlement source

Your task: Execute all 7 phases from ARCHITECTURE.md in order.

Before we begin, confirm you have read ARCHITECTURE.md and understand:
1. Why yfinance must be completely removed
2. Why Weather + Macro engines are the priority (not Quant)
3. Why we need an AI validator (Gemini) to prevent value traps
4. Why the UI tab order matters

Respond with "READY" if you understand the full scope.
```

---

## PART 2: PHASE-BY-PHASE EXECUTION

After Claude responds "READY", paste this:

```
Begin Phase 1: Data Layer Migration

Execute these tasks:
1. Open src/data_loader.py
2. REMOVE: All yfinance imports and code
3. IMPLEMENT: Alpaca API integration using alpaca-py SDK
4. The function fetch_data(ticker, period, interval) must return a DataFrame with: Open, High, Low, Close, Volume
5. Map tickers: SPX→SPY, Nasdaq→QQQ, BTC→BTC/USD, ETH→ETH/USD
6. Use environment variables: APCA_API_KEY_ID, APCA_API_SECRET_KEY
7. Update requirements.txt: Remove yfinance, add alpaca-py>=0.14.0

After completing, show me:
- The new fetch_data() function
- Confirmation that yfinance is fully removed
- Test result: python -c "from src.data_loader import fetch_data; print(fetch_data('SPX').head())"

Begin now.
```

Wait for Claude to complete Phase 1, then continue:

```
Phase 1 confirmed. Begin Phase 2: Engine Architecture

Execute these tasks:
1. Create directory: scripts/engines/
2. MOVE: src/model.py → scripts/engines/quant_engine.py
3. MERGE: src/model_daily.py into quant_engine.py (combine into one file)
4. ADD to top of quant_engine.py: Warning docstring (see ARCHITECTURE.md section 2.1)
5. CREATE: scripts/engines/weather_engine.py (full implementation from ARCHITECTURE.md section 2.2)
6. CREATE: scripts/engines/macro_engine.py (full implementation from ARCHITECTURE.md section 2.3)

After completing, show me:
- File tree of scripts/engines/
- Confirmation that weather_engine.py includes NWS API calls
- Confirmation that macro_engine.py includes FRED API integration

Begin now.
```

Continue with each phase:

```
Phase 2 confirmed. Begin Phase 3: AI Scrutinizer

Execute these tasks:
1. CREATE: src/ai_validator.py
2. IMPLEMENT: AIValidator class using google-generativeai SDK
3. Method: validate_trade(opportunity) returns {approved: bool, ai_reasoning: str}
4. Must use GEMINI_API_KEY from environment
5. Update requirements.txt: Add google-generativeai>=0.3.0

Test:
python -c "from src.ai_validator import AIValidator; v = AIValidator(); print('OK')"

Begin now.
```

```
Phase 3 confirmed. Begin Phase 3.5: Hugging Face Sentiment Pre-Filter

Execute these tasks:
1. CREATE: src/sentiment_filter.py
2. IMPLEMENT: SentimentFilter class with three models:
   - FinBERT (ProsusAI/finbert) for Fed sentiment
   - BART Zero-Shot (facebook/bart-large-mnli) for news classification
   - DistilBERT NER (dslim/bert-base-NER) for entity extraction
3. MODIFY: src/ai_validator.py
   - Import SentimentFilter
   - Add pre_filter step before Gemini API call
   - Track usage stats (Gemini calls vs HF auto-approvals)
4. Update requirements.txt: Add transformers>=4.36.0, torch>=2.1.0, sentencepiece>=0.1.99

Why this matters:
- Saves ~70% of Gemini API costs (only escalate uncertain cases)
- FinBERT is faster (local) than Gemini API calls
- More accurate for Fed/macro sentiment (trained on financial text)

After completing, show me:
- SentimentFilter class structure
- Modified validate_trade() method showing two-tier validation
- Test: python -c "from src.sentiment_filter import SentimentFilter; sf = SentimentFilter(); print(sf.analyze_fed_statement('The Fed will maintain rates'))"

Begin now.
```

```
Phase 3.5 confirmed. Begin Phase 4: Background Scanner Update

Execute these tasks:
1. OPEN: scripts/background_scanner.py
2. REMOVE: Old scanning logic
3. IMPLEMENT: New structure (see ARCHITECTURE.md section 4.1)
   - Import new engines (weather_engine, macro_engine, quant_engine)
   - Import ai_validator
   - Run Weather + Macro engines FIRST
   - Pass all opportunities through AI validator
   - Only save AI-approved trades to Azure table "LiveOpportunities"
   - Save quant signals to separate table "PaperTradingSignals"
4. Each opportunity must include: engine, asset, strike, edge, ai_reasoning

After completing, show me:
- Confirmation that weather_engine and macro_engine run before quant_engine
- Confirmation that AI validator is integrated
- Test result: python scripts/background_scanner.py (dry run)

Begin now.
```

```
Phase 4 confirmed. Begin Phase 5: Streamlit UI Redesign

Execute these tasks:
1. OPEN: streamlit_app.py
2. FIND: st.tabs() definition
3. REORDER tabs to:
   - Tab 0: "⛈️ Weather Arb (Live Edge)"
   - Tab 1: "🏛️ Macro/Fed (Live Edge)"  
   - Tab 2: "💸 All Opportunities"
   - Tab 3: "🧪 Quant Lab (Paper Trading)"
4. ADD to Quant tab (top of with tabs[3]: block):
   st.warning("""
   ⚠️ PAPER TRADING ONLY - EDUCATIONAL PROJECT
   [Full warning text from ARCHITECTURE.md section 5.2]
   """)
5. UPDATE hero header to focus on "Weather Arbitrage • FRED Economics"

After completing, show me:
- New tab order
- Screenshot/text of warning in Quant tab
- New hero header text

Begin now.
```

```
Phase 5 confirmed. Begin Phase 6: GitHub Actions Fix

Execute these tasks:
1. OPEN: .github/workflows/scanner.yml
2. UNCOMMENT: schedule section (remove # from cron line)
3. SET: cron: '*/30 * * * *' (every 30 minutes)
4. ADD to env section:
   APCA_API_KEY_ID: ${{ secrets.APCA_API_KEY_ID }}
   APCA_API_SECRET_KEY: ${{ secrets.APCA_API_SECRET_KEY }}
   FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
   GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
   AZURE_CONNECTION_STRING: ${{ secrets.AZURE_CONNECTION_STRING }}
   KALSHI_API_KEY: ${{ secrets.KALSHI_API_KEY }}

After completing, show me:
- The uncommented schedule line
- The complete env section

Begin now.
```

```
Phase 6 confirmed. Begin Phase 7: Dependencies Update

Execute these tasks:
1. OPEN: requirements.txt
2. REMOVE: yfinance (if not already removed)
3. ADD if missing:
   alpaca-py>=0.14.0
   fredapi>=0.5.1
   google-generativeai>=0.3.0
4. Ensure these are present:
   streamlit>=1.29.0
   pandas>=2.0.0
   lightgbm>=4.1.0
   azure-storage-blob>=12.19.0
   azure-data-tables>=12.4.0

After completing, show me:
- Full requirements.txt
- Confirmation: pip install -r requirements.txt (dry run, show any errors)

Begin now.
```

---

## PART 3: FINAL VALIDATION

After Phase 7, paste this:

```
All phases complete. Now run final validation:

1. Grep check: Search entire codebase for "yfinance"
   Command: grep -r "yfinance" src/ scripts/
   Expected: No results (or only in comments/docs)

2. File structure check:
   ls -la scripts/engines/
   Expected files:
   - quant_engine.py
   - weather_engine.py
   - macro_engine.py

3. Integration test:
   python scripts/background_scanner.py
   Expected output:
   - "🌦️ Running Weather Engine..."
   - "🏛️ Running Macro Engine..."
   - "🤖 AI Validator scrutinizing..."
   - No errors

4. UI test:
   streamlit run streamlit_app.py
   Expected:
   - Tab 1 is Weather Arb
   - Quant tab has yellow warning box
   - Hero says "Weather Arbitrage • FRED Economics"

Run these 4 checks and report results. If any fail, fix them immediately.
```

---

## PART 4: TROUBLESHOOTING PROMPTS

If Claude encounters errors, use these:

### If Alpaca API fails:
```
The Alpaca API integration is failing. Debug:
1. Check if APCA_API_KEY_ID and APCA_API_SECRET_KEY are being read from .env
2. Verify the base URL is https://paper-api.alpaca.markets (not live API)
3. Add better error handling with try/except
4. Test with a simple call first before full implementation
```

### If AI validator fails:
```
The AI validator is failing. Debug:
1. Check if GEMINI_API_KEY is being read from environment
2. Try a simpler prompt first (just "Is this a good trade? Yes or No")
3. Add error handling: if AI fails, default to approving the trade (trust the math)
4. Test standalone: python -c "from src.ai_validator import AIValidator; v = AIValidator(); print(v.validate_trade({'edge': 10}))"
```

### If GitHub Actions fails:
```
The GitHub Actions workflow is failing. Debug:
1. Check if all secrets are added to GitHub repo settings
2. Verify the env variable names match exactly (case-sensitive)
3. Test locally first: python scripts/background_scanner.py
4. Check GitHub Actions logs for specific error message
```

### If imports break:
```
Imports are broken after file reorganization. Fix:
1. Check all __init__.py files exist in new directories
2. Update sys.path.append() in scripts if needed
3. Use relative imports within packages
4. Test each import: python -c "from scripts.engines.weather_engine import WeatherEngine"
```

---

## PART 5: POST-REBUILD CHECKLIST

After Claude completes everything, manually verify:

```bash
# 1. No yfinance
grep -r "import yfinance" . --exclude-dir=venv --exclude-dir=.git
# Should return: nothing

# 2. Alpaca works
python -c "from src.data_loader import fetch_data; print(fetch_data('SPX', '1d', '1m').shape)"
# Should return: (DataFrame shape, e.g., (390, 5))

# 3. Weather engine works
python -c "from scripts.engines.weather_engine import WeatherEngine; w = WeatherEngine(); print(w.get_nws_forecast('NYC'))"
# Should return: dict with forecast_high, confidence

# 4. Macro engine works  
python -c "from scripts.engines.macro_engine import MacroEngine; m = MacroEngine(); print(m.get_cpi_prediction())"
# Should return: dict with predicted_cpi_yoy

# 5. AI validator works
python -c "from src.ai_validator import AIValidator; v = AIValidator(); print(v.validate_trade({'engine': 'Weather', 'edge': 15, 'reasoning': 'Test'}))"
# Should return: dict with approved, ai_reasoning

# 6. Full scan works
python scripts/background_scanner.py
# Should complete without errors, print opportunities

# 7. UI loads
streamlit run streamlit_app.py
# Open browser, verify:
#   - Tab 1 is Weather
#   - Quant tab has warning
#   - Data loads from Azure

# 8. GitHub Actions ready
cat .github/workflows/scanner.yml | grep "schedule"
# Should show uncommented cron schedule
```

---

## ESTIMATED EXECUTION TIME

With Claude Code CLI (or Gemini proxy):
- Phase 1 (Alpaca): 30-45 min
- Phase 2 (Engines): 60-90 min  
- Phase 3 (AI): 20-30 min
- Phase 4 (Scanner): 30-45 min
- Phase 5 (UI): 15-20 min
- Phase 6 (Actions): 5-10 min
- Phase 7 (Deps): 5-10 min

**Total: 3-4 hours of AI execution time**
**Your involvement: ~30 min (testing between phases)**

---

## CRITICAL NOTES

1. **Do NOT skip phases** - they build on each other
2. **Test after each phase** - easier to debug incrementally
3. **Keep .env updated** - AI needs these to test:
   - APCA_API_KEY_ID
   - APCA_API_SECRET_KEY  
   - FRED_API_KEY
   - GEMINI_API_KEY
   - AZURE_CONNECTION_STRING
4. **Git commit after each phase** - easy rollback if something breaks
5. **Check GitHub secrets** - Actions won't work without them

---

## SUCCESS INDICATORS

You'll know the rebuild succeeded when:
✅ `streamlit run streamlit_app.py` shows Weather tab first
✅ Quant tab has prominent yellow warning
✅ `python scripts/background_scanner.py` prints AI-approved opportunities
✅ No more `import yfinance` anywhere in codebase
✅ GitHub Actions runs every 30 min automatically

At that point, you have a **scientifically sound** prediction market tool focused on arbitraging official data sources (NWS, FRED) rather than competing with HFT on efficient markets.

Good luck! 🚀
