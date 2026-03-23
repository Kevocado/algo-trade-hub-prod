import os
import pandas as pd
from datetime import datetime
from io import StringIO
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables with explicit path
current_dir = Path(__file__).parent.parent # Go up one level from src to root
env_path = current_dir / '.env'
load_dotenv(dotenv_path=env_path)

CONTAINER_NAME = "sp500-market-data"
CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING", "").strip('"').strip("'")

# Debug: Check if it worked
if not CONNECTION_STRING:
    print(f"❌ Error: Could not load .env file from: {env_path}")
else:
    print("✅ Success: Environment variables loaded.")

def log_prediction(prediction, current_price, rmse, edge_data, ticker="SPX", timestamp=None):
    """
    Logs the prediction details to Azure Blob Storage.
    
    Args:
        prediction (float): The predicted price.
        current_price (float): The current market price.
        rmse (float): The model's RMSE.
        edge_data (list): List of dictionaries containing edge opportunities.
        ticker (str): The ticker symbol.
        timestamp (datetime, optional): Custom timestamp for backfilling. Defaults to UTC now.
    """
    if not CONNECTION_STRING:
        print("Azure Connection String not found. Skipping logging.")
        return

    try:
        # 1. Prepare Data
        # Find the best edge (highest positive edge)
        best_edge = 0
        best_action = "PASS"
        best_strike = ""
        
        for item in edge_data:
            # Parse edge string "5.2%" -> 5.2
            try:
                edge_val = float(item['Edge'].strip('%'))
                if edge_val > best_edge:
                    best_edge = edge_val
                    best_action = item['Action']
                    best_strike = item['Strike']
            except:
                continue

        log_entry = {
            'timestamp_utc': timestamp.isoformat() if timestamp else datetime.utcnow().isoformat(),
            'ticker': ticker,
            'current_price': current_price,
            'predicted_price': prediction,
            'model_rmse': rmse,
            'best_edge_val': best_edge,
            'best_action': best_action,
            'best_strike': best_strike
        }
        
        df_new = pd.DataFrame([log_entry])
        
        # 2. Connect to Azure
        blob_service_client = BlobServiceClient.from_connection_string(CONNECTION_STRING, connection_timeout=10, read_timeout=10)
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        
        # Create container if it doesn't exist
        if not container_client.exists():
            container_client.create_container()
            
        # 3. Generate Filename (Daily Log)
        date_str = datetime.utcnow().strftime('%Y-%m-%d')
        blob_name = f"predictions_{date_str}.csv"
        blob_client = container_client.get_blob_client(blob_name)
        
        # 4. Check/Download Existing
        if blob_client.exists():
            downloaded_blob = blob_client.download_blob()
            csv_data = downloaded_blob.readall().decode('utf-8')
            df_existing = pd.read_csv(StringIO(csv_data))
            df_final = pd.concat([df_existing, df_new], ignore_index=True)
        else:
            df_final = df_new
            
        # 5. Upload
        output = StringIO()
        df_final.to_csv(output, index=False)
        blob_client.upload_blob(output.getvalue(), overwrite=True)
        print(f"Successfully logged prediction to Azure: {blob_name}")
        
    except Exception as e:
        print(f"Failed to log to Azure: {e}")

def fetch_all_logs():
    """
    Fetches all prediction logs from Azure Blob Storage and merges them into a single DataFrame.
    
    Returns:
        pd.DataFrame: Merged DataFrame containing all history.
    """
    if not CONNECTION_STRING:
        return pd.DataFrame()

    try:
        blob_service_client = BlobServiceClient.from_connection_string(CONNECTION_STRING, connection_timeout=10, read_timeout=10)
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        
        if not container_client.exists():
            return pd.DataFrame()
            
        all_dfs = []
        blob_list = container_client.list_blobs()
        
        for blob in blob_list:
            if blob.name.startswith("predictions_") and blob.name.endswith(".csv"):
                blob_client = container_client.get_blob_client(blob.name)
                downloaded_blob = blob_client.download_blob()
                csv_data = downloaded_blob.readall().decode('utf-8')
                df = pd.read_csv(StringIO(csv_data))
                all_dfs.append(df)
                
        if not all_dfs:
            return pd.DataFrame()
            
        full_df = pd.concat(all_dfs, ignore_index=True)
        
        # Convert timestamp to datetime
        if 'timestamp_utc' in full_df.columns:
            full_df['timestamp_utc'] = pd.to_datetime(full_df['timestamp_utc'])
            full_df = full_df.sort_values('timestamp_utc')
            
        return full_df
        
    except Exception as e:
        print(f"Error fetching logs: {e}")
        return pd.DataFrame()
