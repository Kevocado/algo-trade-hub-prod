import logging
import sys
from ml_engine import FPLEngine

# Configure logging to show in terminal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def main():
    logger.info("🚀 Starting FPL Model Training Pipeline")
    
    engine = FPLEngine()
    
    # 1. Fetch Data
    logger.info("📥 Step 1: Fetching historical data...")
    try:
        historical_data = engine.fetch_historical_data(seasons=['2021-22', '2022-23', '2023-24'])
        if not historical_data:
            logger.error("❌ No data fetched. Exiting.")
            return
        logger.info(f"✅ Fetched {len(historical_data)} seasons of data.")
    except Exception as e:
        logger.error(f"❌ Error fetching data: {e}")
        return

    # 2. Prepare Data
    logger.info("⚙️ Step 2: Preparing training data & engineering features...")
    try:
        full_df = engine.prepare_training_data(historical_data)
        logger.info(f"✅ Training data ready. Shape: {full_df.shape}")
        logger.info(f"   Features included: {[c for c in full_df.columns if 'last_' in c]}")
    except Exception as e:
        logger.error(f"❌ Error preparing data: {e}")
        return

    # 3. Train Model
    logger.info("🧠 Step 3: Training XGBoost model...")
    try:
        model, features = engine.train_model(full_df)
        logger.info(f"✅ Model trained successfully.")
    except Exception as e:
        logger.error(f"❌ Error training model: {e}")
        return

    # 4. Save to Azure
    logger.info("☁️ Step 4: Saving model to Azure Blob Storage...")
    try:
        engine.save_model_to_azure(model, features)
        logger.info("✅ Pipeline completed successfully! 🏁")
        logger.info(f"   Check your Azure Container '{engine.container_name}' for 'fpl_xgboost_model.json'")
    except Exception as e:
        logger.error(f"❌ Error saving to Azure: {e}")

if __name__ == "__main__":
    main()
