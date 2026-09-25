import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error
from .feature_engineering import create_features
from .model_daily import prepare_daily_data

def evaluate_model(model, df, ticker="SPY"):
    """
    Evaluates the model on the provided historical data.
    Supports both Hourly (target_next_hour) and Daily (Target_Close).
    """
    # Determine if Daily or Hourly based on interval or columns?
    # We can try to detect based on the dataframe index frequency or just try both.
    # But prepare_daily_data needs to be called if it's daily.
    
    # Heuristic: If interval is 1h (Daily Model data), use prepare_daily_data.
    # If interval is 1m (Hourly Model data), use create_features.
    # We can check the time difference between rows.
    
    time_diff = df.index.to_series().diff().median()
    is_daily_data = time_diff >= pd.Timedelta(hours=1)
    
    if is_daily_data:
        df_features, _ = prepare_daily_data(df)
        target_col = 'Target_Close'
        # Drop rows without target
        df_eval = df_features.dropna(subset=[target_col])
    else:
        df_features = create_features(df)
        target_col = 'target_next_hour'
        df_eval = df_features.dropna(subset=[target_col])
    
    if df_eval.empty:
        return pd.DataFrame(), {}, pd.DataFrame() # Return 3 empty items
    
    # Feature Selection
    drop_cols = [target_col, 'cum_vol', 'cum_vol_price', 'Daily_Open', 'Target_Close', 'target_next_hour']
    feature_cols = [c for c in df_eval.columns if c not in drop_cols and pd.api.types.is_numeric_dtype(df_eval[c])]
    
    X = df_eval[feature_cols]
    y_actual = df_eval[target_col]
    
    # Ensure features match the model's expected features
    # Try to load the saved feature list for this ticker
    import joblib
    import os
    feature_names_path = os.path.join("model", f"features_{ticker}.pkl")
    if os.path.exists(feature_names_path):
        expected_features = joblib.load(feature_names_path)
        # Reindex to match expected features, fill missing with 0
        X = X.reindex(columns=expected_features, fill_value=0)
    
    # Predict (use .values to pass numpy array to LightGBM Booster)
    y_pred = model.predict(X.values)
    
    # Create result DataFrame
    results = pd.DataFrame(index=df_eval.index)
    results['Actual'] = y_actual
    results['Predicted'] = y_pred
    results['Error'] = results['Actual'] - results['Predicted']
    results['Abs_Error'] = results['Error'].abs()
    
    # Calculate Rolling Accuracy (e.g., 60-minute rolling MAE)
    results['Rolling_MAE'] = results['Abs_Error'].rolling(window=60).mean()
    
    # Calculate Directional Accuracy
    # Did the model correctly predict if price would go up or down relative to the price at prediction time?
    # We need the price at time T (when prediction was made).
    # Since we shifted target by -60, the price at index T is the "current" price at time T.
    results['Price_At_Pred'] = df_eval['Close']
    results['Actual_Dir'] = np.sign(results['Actual'] - results['Price_At_Pred'])
    results['Pred_Dir'] = np.sign(results['Predicted'] - results['Price_At_Pred'])
    results['Correct_Dir'] = (results['Actual_Dir'] == results['Pred_Dir']).astype(int)
    
    # Overall Metrics
    mae = mean_absolute_error(y_actual, y_pred)
    rmse = np.sqrt(mean_squared_error(y_actual, y_pred))
    accuracy = results['Correct_Dir'].mean()
    
    # --- Trust Metrics (Brier, Calibration, PnL) ---
    from sklearn.metrics import brier_score_loss
    from sklearn.calibration import calibration_curve
    
    # 1. Brier Score (Probabilistic Error)
    # We need probabilities for Direction (Up).
    # Simple proxy: If Pred > Current, Prob(Up) = 1.0 (Binary). 
    # For a regressor, we don't have native probs unless we use the Z-score method.
    # Let's use the Z-score method we use in the app.
    # Z = (Pred - Current) / RMSE
    # Prob(Up) = CDF(Z)
    import scipy.stats as stats
    
    # Calculate RMSE dynamically or use the overall RMSE
    # Using overall RMSE for simplicity
    z_scores = (results['Predicted'] - results['Price_At_Pred']) / rmse
    probs_up = stats.norm.cdf(z_scores)
    
    # Actual Outcome (1 if Up, 0 if Down)
    actual_outcomes = (results['Actual'] > results['Price_At_Pred']).astype(int)
    
    brier = brier_score_loss(actual_outcomes, probs_up)
    
    # 2. Calibration Curve
    prob_true, prob_pred = calibration_curve(actual_outcomes, probs_up, n_bins=10)
    
    # 3. PnL Backtest (Simple Strategy)
    # Strategy: Bet $100 on "Yes" if Prob > 60%, Bet $100 on "No" if Prob < 40%.
    # Payout: $100 profit if correct, -$100 loss if wrong. (Simplified binary option)
    results['Bet'] = 0
    results['Bet'] = np.where(probs_up > 0.60, 1, results['Bet']) # Bet Up
    results['Bet'] = np.where(probs_up < 0.40, -1, results['Bet']) # Bet Down
    
    results['Outcome'] = 0
    # If Bet Up (1) and Actual Up (1) -> Win
    # If Bet Down (-1) and Actual Down (0) -> Win
    # Else Loss
    
    # Map Actual Down to -1 for comparison
    actual_signed = np.where(actual_outcomes == 1, 1, -1)
    
    results['PnL'] = np.where(results['Bet'] == 0, 0, 
                              np.where(results['Bet'] == actual_signed, 100, -100))
    
    results['Cum_PnL'] = results['PnL'].cumsum()
    
    metrics = {
        'MAE': mae, 
        'RMSE': rmse, 
        'Directional_Accuracy': accuracy, 
        'Correct_Count': results['Correct_Dir'].sum(), 
        'Total_Count': len(results),
        'Brier_Score': brier,
        'Calibration_Data': {'prob_true': prob_true, 'prob_pred': prob_pred},
        'Total_PnL': results['PnL'].sum()
    }
    
    # Calculate Daily Metrics
    daily_metrics = results.groupby(results.index.date).apply(
        lambda x: pd.Series({
            'MAE': x['Abs_Error'].mean(),
            'Accuracy': (x['Actual_Dir'] == x['Pred_Dir']).mean(),
            'Correct': (x['Actual_Dir'] == x['Pred_Dir']).sum(),
            'Total': len(x),
            'Daily_PnL': x['PnL'].sum()
        })
    )
    
    return results, metrics, daily_metrics
