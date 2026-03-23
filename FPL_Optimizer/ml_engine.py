import os
import pandas as pd
import numpy as np
import requests
import json
import pickle
from io import StringIO, BytesIO
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
import xgboost as xgb
from typing import Dict, List, Optional

load_dotenv()

class FPLEngine:
    """
    ML Engine for FPL Optimizer.
    Handles data fetching, feature engineering, and Azure interaction.
    """
    
    def __init__(self):
        self.connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
        self.container_name = "fplblob"
        self.blob_service_client = None
        if self.connection_string:
            try:
                self.blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
            except Exception as e:
                print(f"Warning: Could not connect to Azure Blob Storage. {e}")
                
        self.base_repo_url = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"

    def fetch_historical_data(self, seasons: List[str] = ['2021-22', '2022-23', '2023-24']) -> Dict[str, pd.DataFrame]:
        """
        Fetch historical FPL data from Vaastav's repo.
        Returns a dictionary of DataFrames keyed by season.
        """
        data = {}
        print(f"--- Fetching Data from {self.base_repo_url} ---")
        for season in seasons:
            print(f"  > Downloading season {season}...")
            try:
                # We typically want the 'gws/merged_gw.csv' which contains player performance per gameweek
                url = f"{self.base_repo_url}/{season}/gws/merged_gw.csv"
                response = requests.get(url)
                response.raise_for_status()
                
                df = pd.read_csv(StringIO(response.text))
                df['season'] = season
                data[season] = df
                print(f"    ✅ Success! Loaded {len(df)} rows.")
            except Exception as e:
                print(f"    ❌ Failed to fetch {season}: {e}")
        
        return data

    def upload_to_azure(self, data: pd.DataFrame, blob_name: str):
        """Upload a DataFrame to Azure Blob Storage as CSV"""
        if not self.blob_service_client:
            print("Azure client not initialized. Skipping upload.")
            return

        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            if not container_client.exists():
                container_client.create_container()
                
            blob_client = container_client.get_blob_client(blob_name)
            csv_data = data.to_csv(index=False)
            blob_client.upload_blob(csv_data, overwrite=True)
            print(f"Uploaded {blob_name} to Azure.")
        except Exception as e:
            print(f"Error uploading to Azure: {e}")

    def calculate_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate rolling averages (Lag Features) for predictive modeling.
        Crucial for the XGBoost model.
        """
        df = df.copy()
        
        # Ensure data is sorted by player and gameweek
        # Note: 'kickoff_time' is usually best for sorting, or 'round'
        if 'kickoff_time' in df.columns:
            df['kickoff_time'] = pd.to_datetime(df['kickoff_time'])
            df = df.sort_values(['name', 'kickoff_time'])
        else:
            df = df.sort_values(['name', 'GW'])

        # Features to calculate lags for
        features = ['minutes', 'goals_scored', 'assists', 'xG', 'xA', 'ict_index', 'total_points']
        
        # Normalize column names if needed (Vaastav's repo sometimes changes case)
        # For now, assuming standard names or mapping them
        col_map = {
            'expected_goals': 'xG',
            'expected_assists': 'xA'
        }
        df = df.rename(columns=col_map)
        
        # Check which features exist
        available_features = [f for f in features if f in df.columns]
        
        print("Calculating lag features...")
        for feature in available_features:
            # Rolling average for last 3 and 5 gameweeks
            # We group by player name (or ID if available and consistent)
            # shift(1) ensures we don't use current GW data to predict current GW
            df[f'last_3_{feature}'] = df.groupby('name')[feature].transform(lambda x: x.shift(1).rolling(window=3, min_periods=1).mean())
            df[f'last_5_{feature}'] = df.groupby('name')[feature].transform(lambda x: x.shift(1).rolling(window=5, min_periods=1).mean())
        
        # Next Opponent Difficulty
        # This requires a mapping of opponent strength. 
        # In the merged_gw.csv, 'opponent_team' is usually an ID. We need to map it to difficulty.
        # For simplicity here, we'll assume a 'was_home' feature and maybe just use raw opponent ID as categorical for now,
        # or if 'difficulty' is in the dataset (it often is in 'fixtures.csv' but maybe not merged_gw).
        # Let's create a placeholder or simple logic if 'opponent_team' exists.
        
        return df

    def prepare_training_data(self, historical_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Merge seasons and prepare final training set"""
        full_df = pd.concat(historical_data.values(), ignore_index=True)
        
        # Clean and Feature Engineer
        full_df = self.calculate_lag_features(full_df)
        
        # Drop rows where we don't have lag features (first few GWs)
        full_df = full_df.dropna(subset=[f'last_3_total_points'])
        
        return full_df

    def train_model(self, df: pd.DataFrame):
        """Train XGBoost Regressor"""
        # Define features and target
        features = [col for col in df.columns if 'last_' in col]
        target = 'total_points'
        
        # Simple Train/Test split (e.g., last season as test)
        # For production, use TimeSeriesSplit
        
        X = df[features]
        y = df[target]
        
        model = xgb.XGBRegressor(
            objective='reg:squarederror',
            n_estimators=100,
            learning_rate=0.1,
            max_depth=5
        )
        
        print(f"Training XGBoost model on {len(X)} samples...")
        model.fit(X, y)
        
        return model, features

    def save_model_to_azure(self, model, features: List[str], model_name: str = "fpl_xgboost_model.json"):
        """Save trained model and feature list to Azure"""
        if not self.blob_service_client:
            print("Azure client not initialized. Saving locally.")
            model.save_model(model_name)
            with open(f"{model_name}_features.pkl", "wb") as f:
                pickle.dump(features, f)
            return

        try:
            # Save model to JSON
            model.save_model("temp_model.json")
            
            # Upload model
            container_client = self.blob_service_client.get_container_client(self.container_name)
            with open("temp_model.json", "rb") as data:
                container_client.upload_blob(name=model_name, data=data, overwrite=True)
            
            # Upload feature list
            feature_blob = model_name.replace(".json", "_features.pkl")
            
            # Pickle features to bytes
            feat_bytes = pickle.dumps(features)
            container_client.upload_blob(name=feature_blob, data=feat_bytes, overwrite=True)
            
            print(f"✅ SUCCESS: Model saved to Azure Blob Storage")
            print(f"   Container: {self.container_name}")
            print(f"   Model Blob: {model_name}")
            print(f"   Features Blob: {feature_blob}")
            
            # Cleanup
            if os.path.exists("temp_model.json"):
                os.remove("temp_model.json")
                
        except Exception as e:
            print(f"❌ Error saving model to Azure: {e}")
            # Fallback to local save if Azure fails
            print("   Falling back to local save...")
            model.save_model(model_name)
            with open(f"{model_name}_features.pkl", "wb") as f:
                pickle.dump(features, f)
            print(f"   Saved locally as {model_name}")

    def load_model_from_azure(self, model_name: str = "fpl_xgboost_model.json"):
        """Load model and features from Azure"""
        if not self.blob_service_client:
            print("Azure client not initialized.")
            return None, None

        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            
            # Download model
            with open("temp_model.json", "wb") as f:
                download_stream = container_client.download_blob(model_name)
                f.write(download_stream.readall())
            
            model = xgb.XGBRegressor()
            model.load_model("temp_model.json")
            
            # Download features
            feature_blob = model_name.replace(".json", "_features.pkl")
            download_stream = container_client.download_blob(feature_blob)
            features = pickle.loads(download_stream.readall())
            
            # Cleanup
            if os.path.exists("temp_model.json"):
                os.remove("temp_model.json")
                
            return model, features
            
        except Exception as e:
            print(f"Error loading model from Azure: {e}")
            return None, None

    def predict_next_gw(self, current_data: pd.DataFrame) -> pd.DataFrame:
        """
        Predict points for the next gameweek using the loaded model.
        current_data must have the raw stats to calculate lag features.
        """
        # Load model
        model, features = self.load_model_from_azure()
        if not model:
            print("Could not load model. Returning empty predictions.")
            return current_data
        
        # Calculate features for current data
        # Note: This is tricky. 'current_data' needs to be the recent history of the current season
        # so we can calculate the rolling averages for the *next* GW.
        
        df_prepared = self.calculate_lag_features(current_data)
        
        # We only want to predict for the latest/upcoming gameweek rows
        # Assuming current_data has a row for the next GW (or we create it)
        # For now, let's assume we predict on the last available row for each player
        # effectively predicting "next" performance based on "past"
        
        # Filter to just the rows we want to predict (e.g. the most recent entry per player)
        # This logic depends heavily on how current_data is structured.
        # If current_data is the full history of this season:
        latest_gw = df_prepared.sort_values('GW').groupby('name').tail(1)
        
        # Ensure columns match
        X = latest_gw[features]
        
        preds = model.predict(X)
        latest_gw['predicted_points'] = preds
        
        return latest_gw[['name', 'predicted_points']]

if __name__ == "__main__":
    # Example usage for training
    engine = FPLEngine()
    # data = engine.fetch_historical_data()
    # full_df = engine.prepare_training_data(data)
    # model, features = engine.train_model(full_df)
    # engine.save_model_to_azure(model, features)
