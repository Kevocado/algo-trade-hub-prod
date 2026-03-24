import streamlit as st
import json
import threading
import time
import os
from datetime import datetime

# Streamlit Page Config
st.set_page_config(page_title="Algo-Trade-Hub Walk-Forward Quant Factory", page_icon="🏭", layout="wide", initial_sidebar_state="expanded")

# Inject Custom CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@400;600;700&display=swap');
    body, .stApp { font-family: 'Inter', sans-serif; background-color: #0d1117; color: #c9d1d9; }
    h1, h2, h3 { color: #58a6ff !important; font-weight: 700; }
    .metric-box { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; text-align: center; }
    .metric-title { font-size: 0.9rem; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; }
    .metric-value { font-size: 2rem; font-weight: 700; color: #58a6ff; font-family: 'JetBrains Mono', monospace; }
    .status-badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; }
    .status-running { background: rgba(88, 166, 255, 0.1); color: #58a6ff; border: 1px solid rgba(88, 166, 255, 0.4); }
    .status-ready { background: rgba(63, 185, 80, 0.1); color: #3fb950; border: 1px solid rgba(63, 185, 80, 0.4); }
</style>
""", unsafe_allow_html=True)

# ── Background Thread: Trainer ──
def bg_worker():
    import schedule
    import subprocess
    
    def run_trainer():
        print(f"[{datetime.now()}] Triggering trainer.py...")
        subprocess.run(["python", "trainer.py"], check=False)
        
    schedule.every().hour.do(run_trainer)
    
    # Run once at startup
    if not os.path.exists("training_status.json"):
        run_trainer()
        
    while True:
        schedule.run_pending()
        time.sleep(60)

# Check if thread is already running (Streamlit reruns script from top to bottom)
if 'worker_started' not in st.session_state:
    st.session_state.worker_started = True
    t = threading.Thread(target=bg_worker, daemon=True)
    t.start()

# ── Read Status ──
def load_status():
    try:
        with open("training_status.json", "r") as f:
            return json.load(f)
    except Exception:
        return {
            "status": "Initializing...",
            "brier_score": None,
            "accuracy": None,
            "latest_prob": None,
            "current_price": None,
            "last_update": "N/A"
        }

status_data = load_status()

# ── Header ──
st.markdown("<h1>🏭 Quant Factory: Walk-Forward Engine</h1>", unsafe_allow_html=True)
st.markdown("Automated `BTC-USD` hourly rolling window training. Fresh `LGBMClassifier` every hour. No lookahead bias.")

s = status_data.get('status', 'Unknown')
badge_class = "status-ready" if s == "Ready" else "status-running"
st.markdown(f"<div style='margin-bottom: 24px;'><span class='status-badge {badge_class}'>Status: {s}</span></div>", unsafe_allow_html=True)

# ── Metrics ──
m1, m2, m3, m4 = st.columns(4)

acc = status_data.get('accuracy')
acc_str = f"{acc:.1f}%" if acc is not None else "—"

brier = status_data.get('brier_score')
brier_str = f"{brier:.4f}" if brier is not None else "—"

prob = status_data.get('latest_prob')
prob_str = f"{prob:.1f}%" if prob is not None else "—"

price = status_data.get('current_price')
price_str = f"${price:,.2f}" if price is not None else "—"

m1.markdown(f"<div class='metric-box'><div class='metric-title'>OOS Accuracy</div><div class='metric-value' style='color:#3fb950;'>{acc_str}</div></div>", unsafe_allow_html=True)
m2.markdown(f"<div class='metric-box'><div class='metric-title'>Brier Score</div><div class='metric-value' style='color:#d29922;'>{brier_str}</div></div>", unsafe_allow_html=True)
m3.markdown(f"<div class='metric-box'><div class='metric-title'>Live Upward Edge</div><div class='metric-value'>{prob_str}</div></div>", unsafe_allow_html=True)
m4.markdown(f"<div class='metric-box'><div class='metric-title'>Current BTC Price</div><div class='metric-value' style='color:#c9d1d9;'>{price_str}</div></div>", unsafe_allow_html=True)

st.markdown(f"<p style='color: #8b949e; font-size: 0.85rem; margin-top: 12px;'>Last Updated: {status_data.get('last_update', 'N/A')}</p>", unsafe_allow_html=True)

# ── Metric Definitions ──
st.markdown("### 📊 Metric Definitions")
colA, colB = st.columns(2)
with colA:
    st.markdown("**OOS Accuracy**: Percentage of correct directional predictions on the rolling 720h validation window (unseen data).")
    st.markdown("**Brier Score**: Evaluates probability calibration. Lower is better (0 = Perfect certainty, 1 = Max error).")
with colB:
    st.markdown("**Live Upward Edge**: The raw probability (0-100%) that BTC-USD will close higher in the next 60 minutes.")
    st.markdown("**Current BTC Price**: Live hourly close price used as the baseline for the next inference cycle.")

# ── Details ──
st.markdown("### 🧩 Model Configuration")
st.json({
    "Target": "BTC-USD Hourly Direction",
    "Model": "LightGBM Classifier",
    "Validation": "Walk-Forward (Expanding Window: 720h)",
    "Updates": "Every Hour (Background Thread)",
    "Features": ["Price Velocity", "Price Acceleration", "Realized Volatility (30h)", "Lags (1,2,3,5,12,24,48)", "Hour", "DayOfWeek"]
})

# Auto-refresh mechanism (checks JSON file every 15 seconds)
st_autorefresh = """
<script>
    setTimeout(function(){
        window.location.reload(1);
    }, 15000);
</script>
"""
st.components.v1.html(st_autorefresh, height=0)
