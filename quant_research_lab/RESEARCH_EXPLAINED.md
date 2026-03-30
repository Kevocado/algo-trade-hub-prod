# 🧬 Research Lab: Technical Documentation

This document provides a deep dive into the logic, mathematics, and quantitative workflow behind the `lightgbm_backtest.ipynb` research environment.

## 🏗️ The Quant Pipeline Overview

The notebook follows a standard professional quant research loop:
`Data Ingestion` → `Feature Engineering` → `Model Training` → `Interpretability` → `Vectorized Backtesting`.

---

## 📊 1. Feature Engineering (The Indicators)
We use four primary technical indicators to represent different market dimensions:

### RSI (Relative Strength Index)
*   **What it is:** A momentum oscillator that measures the speed and change of price movements.
*   **The Math:** $RSI = 100 - [100 / (1 + RS)]$, where $RS$ is the average of $u$ days' up closes divided by the average of $d$ days' down closes.
*   **In Research:** We use it to identify overbought (>70) or oversold (<30) conditions.

### MACD (Moving Average Convergence Divergence)
*   **What it is:** A trend-following momentum indicator that shows the relationship between two moving averages.
*   **The Math:** 12-period EMA minus 26-period EMA.
*   **In Research:** We use the `MACD_Diff` (Histogram), which represents the distance between the MACD line and its signal line. A positive diff indicates increasing bullish momentum.

### ATR (Average True Range)
*   **What it is:** A volatility indicator that shows how much an asset moves, on average, during a given time frame.
*   **In Research:** Essential for risk management. It helps the model understand if a 1% move is "normal" or "extreme" given the current market regime.

### Bollinger Bands (BB)
*   **What it is:** A volatility envelope set at 2 standard deviations above and below a moving average.
*   **In Research:** We specifically use:
    -   **%B (Percent Bandwidth):** Where price is relative to the bands (1.0 = top, 0.0 = bottom).
    -   **Bandwidth:** The total width of the bands, indicating market compression vs. expansion.

---

## 🤖 2. The LightGBM Engine
LightGBM is a **Gradient Boosting Decision Tree (GBDT)** framework.

*   **Leaf-wise Growth:** Unlike other boosting trees that grow level-by-level, LightGBM grows "leaf-wise," choosing the leaf that reduces loss the most. This makes it significantly faster and more accurate for large financial datasets.
*   **Classification:** We treat the problem as binary classification: "Will the price be higher 1 hour from now?" (1 = Yes, 0 = No).

---

## 🔍 3. SHAP (Model Interpretability)
Traditional "Feature Importance" in trees can be misleading. We use **SHAP (SHapley Additive exPlanations)**.

*   **The Logic:** Based on Cooperative Game Theory. It treats each feature as a "player" in a game and calculates how much each player contributes to the "payout" (the prediction).
*   **Why it matters:** It tells us not just *if* RSI is important, but *how* it affects the price. E.g., "High RSI values currently contribute +0.05 to the probability of a price increase."

---

## 📈 4. Signal Generation Logic
We don't just trade every "1" or "0". We use a **Probability Buffer**:

-   **Buy Signal:** Model probability > 55% (Confidence is high).
-   **Sell/Short Signal:** Model probability < 45% (High confidence in a drop).
-   **Neutral:** 45% to 55% (Market noise; stay out).

---

## 🏎️ 5. VectorBT (Backtesting)
Most backtesters loop through data row-by-row (slow). **VectorBT** treats the entire dataset as a massive matrix (vector).

*   **Performance:** It can simulate millions of trades in milliseconds using NumPy/Pandas.
*   **Professional Metrics:** It gives us the **Sharpe Ratio** (risk-adjusted return) and **Max Drawdown** (the largest peak-to-trough drop), which are the "Gold Standards" for evaluating any trading strategy.

---

## 🛠️ How to use this Lab
1.  **Modify Features:** Add new columns in Cell 2 to see if they improve the SHAP values.
2.  **Tweak Thresholds:** Change the `0.55/0.45` thresholds in Cell 5 to find the "Sweet Spot" for your strategy.
3.  **Check SHAP:** If a feature has low SHAP values, it's "noise"—remove it to prevent the model from overfitting.

---

## 📈 6. Binary Options Math (Kalshi Logic)
Trading on Kalshi is fundamentally different from trading stocks because the payout is **fixed**.

*   **Fixed Settlement:** $1.00 (Success) or $0.00 (Failure).
*   **The Math of Edge:** $Expected Value (EV) = (P_{model} \times \$1.00) - Price_{market}$.
*   **The Rule:** If $EV > 0.10$, the trade is mathematically "Cheap." In a large enough sample (Law of Large Numbers), consistently buying contracts with positive EV leads to a profitable equity curve.

## 🌦️ 7. Weather Arbitrage Features
Weather markets don't care about "momentum" or "RSI". They care about **Ground Truth vs. Market Consensus**.

*   **NWS Forecasts:** These are the "Settlement Sources." If the NWS says 90% chance of rain and Kalshi is trading "Will it Rain?" at 50¢, that 40¢ gap is your **Edge**.
*   **Station Data:** We use `meteostat` to pull historical high/low temps by city coordinates. This allows the model to learn the specific "climatology" of a location.

## 🏗️ 8. Synthetic Market Simulation
Because historical intraday Kalshi order books are restricted, we use **Market Approximation**:

1.  **Base Prob:** Calculated using a Sigmoid function based on distance to strike.
2.  **Noise Injection:** We add Gaussian noise to simulate the "irrationality" of retail traders.
3.  **Backtesting:** We compare a "Clean" model (your strategy) against this "Noisy" market. If the Equity Curve stays positive, your strategy is robust enough to overcome market noise.
