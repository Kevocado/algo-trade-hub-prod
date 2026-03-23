# Prompt for AI: Integrate Market Scanner with Existing SP500-Predictor

## Context

I have an existing **SP500-Predictor** project with the following architecture:
- `src/data_loader.py` - Fetches OHLCV data from yfinance
- `src/feature_engineering.py` - Generates technical indicators
- `src/model.py` - LightGBM model for predictions
- `src/kalshi_feed.py` - Kalshi market integration (basic)
- `streamlit_app.py` - Dashboard showing S&P 500 predictions

I want to **enhance this system** to:
1. Scan prediction markets (Polymarket/Kalshi) every 10 minutes
2. Use sentiment analysis + technical analysis for fair value estimates
3. Find mispriced markets (edge > 8%)
4. Display live opportunities in Streamlit dashboard
5. Let me manually execute trades on Kalshi/Polymarket

## Files I'm Providing

I have these new modules ready to integrate:

1. **sentiment_loader.py** - Reddit, News, Twitter data collection
2. **sentiment_features.py** - FinBERT sentiment analysis + 15 features
3. **kalshi_integration.py** - Enhanced Kalshi API with opportunity finder
4. **hybrid_predictor.py** - Combines technical + sentiment models
5. **market_scanner_app.py** - New Streamlit dashboard for live signals

## Integration Requirements

### Phase 1: Extend Existing Data Loaders

**Task**: Modify `src/data_loader.py` to support both price data AND sentiment data

```python
# Current structure (keep this):
class DataLoader:
    def load_stock_data(self, ticker, start_date, end_date):
        # Existing yfinance logic
        pass

# Add this:
class SentimentDataLoader:
    """Add sentiment data collection to existing loader"""
    
    def __init__(self, reddit_client, news_client):
        self.reddit = reddit_client
        self.news = news_client
    
    def load_sentiment_for_ticker(self, ticker, lookback_days=7):
        """
        Fetch sentiment data for a ticker
        Returns DataFrame with sentiment scores aligned to price data timestamps
        """
        # Use sentiment_loader.py module
        pass
    
    def merge_with_price_data(self, price_df, sentiment_df):
        """Merge sentiment features with existing technical features"""
        pass

# Integration point:
class EnhancedDataLoader(DataLoader, SentimentDataLoader):
    """Unified loader combining both approaches"""
    pass
```

**Questions for you:**
1. Should sentiment data be optional (flag to enable/disable)?
2. How do we handle missing sentiment data (forward fill, zero, or skip)?
3. What frequency for sentiment updates (1h, 1d)?

---

### Phase 2: Enhance Feature Engineering

**Task**: Extend `src/feature_engineering.py` to include sentiment features alongside technical indicators

```python
# Current structure (keep this):
def generate_technical_features(df):
    # RSI, MACD, Bollinger Bands, etc.
    pass

# Add this:
def generate_sentiment_features(df):
    """
    Add sentiment-based features
    Uses sentiment_features.py module
    """
    from sentiment_features import NarrativeFeatureEngine
    
    engine = NarrativeFeatureEngine(analyzer)
    features = engine.generate_aggregate_features(df)
    
    return {
        'sentiment_mean': features['sentiment_mean'],
        'sentiment_momentum': features['sentiment_momentum'],
        'attention_score': features['attention_score'],
        # ... etc
    }

# Combine both:
def generate_hybrid_features(price_df, sentiment_df):
    """Generate both technical + sentiment features"""
    technical = generate_technical_features(price_df)
    sentiment = generate_sentiment_features(sentiment_df)
    
    # Merge
    combined = pd.concat([technical, sentiment], axis=1)
    return combined
```

**Implementation details needed:**
- Feature normalization strategy (StandardScaler, MinMaxScaler)?
- How to weight technical vs sentiment (60/40 split as suggested)?
- Feature selection criteria (correlation threshold, mutual info)?

---

### Phase 3: Upgrade Model

**Task**: Extend `src/model.py` to support ensemble predictions

```python
# Current structure (keep this):
class LGBMPredictor:
    def train(self, X, y):
        # Existing LightGBM training
        pass
    
    def predict(self, X):
        # Single model prediction
        pass

# Add this:
class HybridPredictor(LGBMPredictor):
    """
    Combines multiple models:
    - Technical-only model (your existing one)
    - Sentiment-only model (new)
    - Ensemble model (combined features)
    
    Uses hybrid_predictor.py module
    """
    
    def __init__(self, sentiment_weight=0.4):
        self.technical_model = LGBMPredictor()  # Your existing model
        self.sentiment_model = None  # New sentiment model
        self.ensemble_model = None  # Combined model
        self.sentiment_weight = sentiment_weight
    
    def train_all(self, X_technical, X_sentiment, X_combined, y):
        """Train all three models"""
        self.technical_model.train(X_technical, y)
        # Train sentiment model
        # Train ensemble model
        pass
    
    def predict_hybrid(self, X_technical, X_sentiment):
        """Weighted prediction from both models"""
        tech_pred = self.technical_model.predict(X_technical)
        sent_pred = self.sentiment_model.predict(X_sentiment)
        
        return (1 - self.sentiment_weight) * tech_pred + self.sentiment_weight * sent_pred
```

**Configuration needed:**
- Model hyperparameters for sentiment model vs technical model
- Ensemble strategy (weighted average, stacking, voting)?
- Retraining schedule (daily, weekly)?

---

### Phase 4: Enhance Kalshi Integration

**Task**: Replace/extend `src/kalshi_feed.py` with enhanced version

```python
# Current kalshi_feed.py (basic):
def get_kalshi_markets():
    # Fetch markets
    pass

# Enhanced version (use kalshi_integration.py):
from kalshi_integration import KalshiClient, MarketScanner, OpportunityFinder

class EnhancedKalshiFeed:
    """
    Extends your existing kalshi_feed.py with:
    - Market scanning across multiple assets
    - Edge detection
    - Position sizing (Kelly criterion)
    """
    
    def __init__(self):
        self.client = KalshiClient()
        self.scanner = MarketScanner(self.client)
        self.finder = OpportunityFinder(min_edge=0.08)
    
    def scan_all_markets(self):
        """Scan SPX, BTC, ETH, QQQ markets"""
        markets = self.scanner.scan_all_markets()
        return markets
    
    def find_opportunities(self, markets, model_predictions):
        """
        Compare model predictions vs market prices
        Returns list of opportunities with edge > 8%
        """
        opportunities = self.finder.find_opportunities(markets, model_predictions)
        return opportunities
```

**Integration points:**
- How to map your S&P 500 predictions to Kalshi market tickers?
- Should we filter by market category (only SPX, or all assets)?
- What's the refresh interval (10min, 30min, 1h)?

---

### Phase 5: Rebuild Streamlit Dashboard

**Task**: Replace `streamlit_app.py` with enhanced version that shows:
- Your existing S&P 500 predictions (keep this)
- NEW: Live market opportunities from scanner
- NEW: Edge calculations and Kelly sizing
- Manual "Open on Kalshi" buttons

```python
# New dashboard structure:
import streamlit as st
from your_existing_modules import load_data, predict_price
from market_scanner_app import Dashboard  # New module

# Tab 1: Your Existing S&P 500 Predictor (KEEP THIS)
def render_sp500_tab():
    st.header("S&P 500 Price Prediction")
    # Your existing visualization
    # Your existing model predictions
    pass

# Tab 2: NEW Market Opportunities
def render_opportunities_tab():
    st.header("Live Market Opportunities")
    # Use market_scanner_app.py
    scanner = Dashboard()
    scanner.render_signals()

# Tab 3: Performance Tracking
def render_performance_tab():
    st.header("Trading Performance")
    # Track manual trades you've executed
    pass

# Main app:
def main():
    st.set_page_config(layout="wide")
    
    tabs = st.tabs(["📈 S&P 500 Predictor", "🎯 Market Scanner", "📊 Performance"])
    
    with tabs[0]:
        render_sp500_tab()
    
    with tabs[1]:
        render_opportunities_tab()
    
    with tabs[2]:
        render_performance_tab()

if __name__ == "__main__":
    main()
```

**Design decisions:**
- Should S&P 500 predictor be separate tab or merged with opportunities?
- How to track manual trades (CSV file, SQLite, or just session state)?
- Auto-refresh interval for opportunities tab?

---

## Specific Integration Steps

### Step 1: Update Directory Structure

```
SP500-Predictor/
├── src/
│   ├── data/
│   │   ├── stock_loader.py         # Renamed from data_loader.py
│   │   ├── sentiment_loader.py     # NEW - from provided files
│   │   └── unified_loader.py       # NEW - combines both
│   ├── features/
│   │   ├── technical.py            # Renamed from feature_engineering.py
│   │   ├── sentiment.py            # NEW - from sentiment_features.py
│   │   └── hybrid.py               # NEW - combines both
│   ├── models/
│   │   ├── lgbm_predictor.py       # Renamed from model.py
│   │   ├── hybrid_predictor.py     # NEW - from provided files
│   │   └── ensemble.py             # NEW - combines models
│   ├── trading/
│   │   ├── kalshi_basic.py         # Renamed from kalshi_feed.py
│   │   ├── kalshi_enhanced.py      # NEW - from kalshi_integration.py
│   │   └── signal_generator.py     # NEW - generates trading signals
│   └── utils/
│       ├── config.py
│       └── logging.py
├── streamlit_app.py                # REPLACE with enhanced version
├── market_scanner_app.py           # NEW - standalone scanner
└── config/
    └── settings.yaml               # NEW - centralized config
```

### Step 2: Configuration File

Create `config/settings.yaml`:

```yaml
# Data Sources
data:
  price_data:
    source: yfinance
    assets: [SPY, QQQ, BTC-USD, ETH-USD]
  
  sentiment_data:
    enabled: true
    sources:
      reddit:
        enabled: true
        subreddits: [wallstreetbets, stocks, investing]
      news:
        enabled: true
        sources: [bloomberg, reuters, cnbc]
      twitter:
        enabled: false

# Models
models:
  sp500_predictor:
    type: lightgbm
    technical_only: true
    params:
      num_leaves: 31
      learning_rate: 0.05
  
  hybrid_predictor:
    enabled: true
    sentiment_weight: 0.4
    technical_weight: 0.6

# Trading
trading:
  platforms:
    kalshi:
      enabled: true
      demo_mode: true
    polymarket:
      enabled: true
  
  signal_settings:
    min_edge: 0.08  # 8%
    max_kelly: 0.06  # 6%
    min_volume: 1000
  
  scan_interval: 600  # 10 minutes

# Dashboard
dashboard:
  auto_refresh: false
  refresh_interval: 300  # 5 minutes
  show_sp500_predictions: true
  show_market_scanner: true
```

### Step 3: Migration Script

Create `migrate_to_enhanced.py`:

```python
"""
Migration script to integrate new modules with existing codebase
"""

import os
import shutil
from pathlib import Path

def migrate():
    """Migrate existing project to enhanced structure"""
    
    # 1. Backup existing files
    print("📦 Creating backup...")
    shutil.copytree('src', 'src_backup')
    
    # 2. Rename existing files
    print("📝 Renaming files...")
    os.rename('src/data_loader.py', 'src/data/stock_loader.py')
    os.rename('src/feature_engineering.py', 'src/features/technical.py')
    os.rename('src/model.py', 'src/models/lgbm_predictor.py')
    os.rename('src/kalshi_feed.py', 'src/trading/kalshi_basic.py')
    
    # 3. Copy new files
    print("📂 Adding new modules...")
    shutil.copy('sentiment_loader.py', 'src/data/')
    shutil.copy('sentiment_features.py', 'src/features/sentiment.py')
    shutil.copy('hybrid_predictor.py', 'src/models/')
    shutil.copy('kalshi_integration.py', 'src/trading/kalshi_enhanced.py')
    
    # 4. Create unified loader
    print("🔧 Creating unified loader...")
    # Generate unified_loader.py that imports from both
    
    # 5. Update imports in existing files
    print("🔄 Updating imports...")
    # Update references to old file names
    
    print("✅ Migration complete!")
    print("⚠️  Review changes and test before committing")

if __name__ == "__main__":
    migrate()
```

---

## Questions to Answer

Before I start integrating, please provide:

1. **Data Strategy**:
   - Should sentiment be required or optional?
   - How to handle missing sentiment data?
   - Preferred update frequency?

2. **Model Strategy**:
   - Keep separate technical-only model for S&P 500?
   - Use hybrid model for everything?
   - What weight for sentiment vs technical? (suggest 40/60)

3. **Dashboard Strategy**:
   - Replace entire dashboard or add tabs?
   - Show both S&P 500 predictions AND market opportunities?
   - Track manual trades or just show signals?

4. **Trading Strategy**:
   - Scan only SPX markets or all markets?
   - Minimum edge threshold (8%, 10%, 12%)?
   - Maximum position size (6%, 10%)?

5. **Deployment**:
   - Run locally or deploy to cloud?
   - Automated scanning (cron job) or manual refresh?
   - Store signals in database or CSV?

---

## Integration Checklist

After I integrate, you should be able to:

- [ ] Run existing S&P 500 predictor unchanged
- [ ] Optionally enable sentiment analysis
- [ ] Scan prediction markets every 10 minutes
- [ ] See live opportunities in dashboard
- [ ] Click "Open on Kalshi" to trade manually
- [ ] Track performance over time
- [ ] Export signals to CSV
- [ ] Switch between technical-only and hybrid models

---

## Expected Outcome

Final system will:
1. ✅ Keep your existing S&P 500 predictor working
2. ✅ Add sentiment analysis as optional enhancement
3. ✅ Scan 500-1000 prediction markets automatically
4. ✅ Find mispriced markets (edge > 8%)
5. ✅ Calculate Kelly position sizes
6. ✅ Show live opportunities in Streamlit
7. ✅ Let you manually execute on Kalshi/Polymarket

**Backward Compatible**: Everything you have now keeps working. New features are additive, not disruptive.

---

Please answer the questions above, and I'll generate the complete integration code!
