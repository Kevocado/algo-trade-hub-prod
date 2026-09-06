"""
app.py — FPL Scout dashboard.

Run with:
    streamlit run app.py
"""

import pandas as pd
import plotly.express as px
import streamlit as st

import model as model_lib
import train as train_pipeline
from scout import build_gameweek_scout_table

st.set_page_config(page_title="FPL Scout", page_icon="⚽", layout="wide")

POSITION_ORDER = ["GK", "DEF", "MID", "FWD"]


@st.cache_data(ttl=1800, show_spinner="Fetching live FPL data and scoring players...")
def get_scout_table() -> pd.DataFrame:
    return build_gameweek_scout_table()


@st.cache_data(ttl=1800)
def get_manifest():
    return model_lib.load_manifest()


def models_available() -> bool:
    return model_lib.MANIFEST_PATH.exists()


def render_sidebar():
    st.sidebar.title("⚽ FPL Scout")
    st.sidebar.caption("Predicted points + feature importance, per position.")

    if st.sidebar.button("\U0001f504 Refresh live data"):
        get_scout_table.clear()
        st.rerun()

    if st.sidebar.button("\U0001f3cb️ Retrain models"):
        with st.status("Training models on historical seasons...", expanded=True) as status:
            seasons = train_pipeline.default_completed_seasons()
            st.write(f"Seasons: {seasons}")
            df = train_pipeline.load_training_data(seasons)
            st.write(f"Loaded {len(df)} rows")
            df, lag_cols = train_pipeline.build_lag_features(
                df, group_cols=["season", "element"], sort_cols=["season", "GW"]
            )
            feature_cols = train_pipeline.full_feature_list(lag_cols)
            df = df.dropna(subset=[lag_cols[0]]) if lag_cols else df
            train_pipeline.train_all_positions(df, feature_cols)
            status.update(label="Done", state="complete")
        get_manifest.clear()
        get_scout_table.clear()
        st.rerun()

    if models_available():
        manifest = get_manifest()
        st.sidebar.caption(f"Models trained: {manifest['trained_at'][:19]} UTC")


def render_scout_tab():
    table = get_scout_table()
    playable = table[table["predicted_points"].notna()].copy()

    low_data_share = playable["low_data"].mean() if len(playable) else 0
    if low_data_share > 0.3:
        n_prior = int((playable["data_confidence"] == "prior_season").sum())
        n_pos = int((playable["data_confidence"] == "position_avg").sum())
        st.info(
            f"{int(playable['low_data'].sum())}/{len(playable)} players have played fewer "
            "than 5 games so far this season, so their prediction blends in **last season's "
            f"form** ({n_prior} players) or a **position-average prior** for players with no "
            f"FPL history at all ({n_pos} players) — marked **low data** below. This fades out "
            "automatically as more current-season games are played."
        )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        positions = st.multiselect("Position", POSITION_ORDER, default=POSITION_ORDER)
    with col2:
        max_price = st.slider("Max price (£m)", 4.0, 15.0, 15.0, 0.5)
    with col3:
        search = st.text_input("Search player/team")
    with col4:
        hide_low_data = st.checkbox("Hide low-data players", value=False)

    filtered = playable[playable["position"].isin(positions) & (playable["price"] <= max_price)]
    if hide_low_data:
        filtered = filtered[~filtered["low_data"]]
    if search:
        s = search.lower()
        filtered = filtered[
            filtered["web_name"].str.lower().str.contains(s)
            | filtered["team"].str.lower().str.contains(s)
        ]

    filtered = filtered.sort_values("predicted_points", ascending=False)

    st.dataframe(
        filtered[
            [
                "web_name", "team", "position", "price", "predicted_points",
                "predicted_points_per_million", "next_opponent", "was_home",
                "opponent_difficulty", "status", "news", "selected_by_percent", "data_confidence",
            ]
        ].rename(
            columns={
                "web_name": "Player", "team": "Team", "position": "Pos", "price": "£m",
                "predicted_points": "Pred pts", "predicted_points_per_million": "Pred pts / £m",
                "next_opponent": "Opponent", "was_home": "Home", "opponent_difficulty": "FDR",
                "status": "Status", "news": "News", "selected_by_percent": "Selected %",
                "data_confidence": "Data source",
            }
        ),
        use_container_width=True,
        hide_index=True,
        height=600,
    )


def render_importance_tab():
    manifest = get_manifest()
    metric = st.radio("Importance metric", ["permutation", "gain"], horizontal=True,
                       help="Permutation importance = how much validation accuracy drops when a "
                            "feature is shuffled (more trustworthy). Gain = XGBoost's internal split-gain score.")

    cols = st.columns(2)
    for i, position in enumerate(POSITION_ORDER):
        pos_data = manifest["positions"].get(position)
        if not pos_data:
            continue
        importance = pos_data["importance"][metric]
        top = sorted(importance.items(), key=lambda x: -x[1])[:12]
        imp_df = pd.DataFrame(top, columns=["feature", "importance"]).sort_values("importance")

        m = pos_data["metrics"]
        with cols[i % 2]:
            st.subheader(position)
            st.caption(f"MAE {m['mae']:.2f} · R² {m['r2']:.2f} · trained on {m['n_train']} rows")
            fig = px.bar(imp_df, x="importance", y="feature", orientation="h", height=400)
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)


def main():
    render_sidebar()

    if not models_available():
        st.title("⚽ FPL Scout")
        st.warning("No trained models yet. Click **Retrain models** in the sidebar (or run `python train.py`) to get started.")
        return

    tab1, tab2 = st.tabs(["\U0001f50d Gameweek Scout", "\U0001f4ca Feature Importance by Position"])
    with tab1:
        render_scout_tab()
    with tab2:
        render_importance_tab()


if __name__ == "__main__":
    main()
