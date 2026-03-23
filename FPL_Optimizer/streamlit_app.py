import streamlit as st
import pandas as pd
import plotly.express as px
from data_manager import AdvancedFPLDataManager
from optimizer import AdvancedFPLOptimizer
from controller import FPLController
from utils import extract_team_id_from_url
from ml_engine import FPLEngine
import time

# Page Config
st.set_page_config(
    page_title="FPL Optimizer Pro",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Data Manager (Cached)
@st.cache_resource
def get_data_manager():
    dm = AdvancedFPLDataManager()
    dm.fetch_bootstrap_data()
    dm.fetch_fixtures()
    return dm

@st.cache_resource
def get_ml_engine():
    return FPLEngine()

@st.cache_data
def get_processed_data(_dm):
    bootstrap_data = _dm.fetch_bootstrap_data()
    return _dm.process_enhanced_player_data(bootstrap_data)

def main():
    # --- Header ---
    st.title("⚽ FPL Optimizer Pro")
    st.markdown(f"**Last Updated:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # --- Initialization ---
    with st.spinner("Loading FPL Data..."):
        dm = get_data_manager()
        ml_engine = get_ml_engine()
        players_df = get_processed_data(dm)
        
        # Try to get ML predictions
        try:
            # We need to format players_df to match what the ML engine expects for lag features
            # In a real scenario, we'd need historical data for the current season to calculate lags
            # For this demo, we'll assume the engine handles it or returns the dataframe as is if it fails
            predictions = ml_engine.predict_next_gw(players_df)
            if 'predicted_points' in predictions.columns:
                 players_df = players_df.merge(predictions, on='name', how='left')
                 st.toast("🤖 AI Predictions Loaded from Azure!", icon="✅")
        except Exception as e:
            print(f"ML Prediction failed: {e}")
            
        optimizer = AdvancedFPLOptimizer(players_df)
        controller = FPLController(dm, optimizer)
        
    # --- Sidebar & Optimization ---
    st.sidebar.header("🛠️ Team Optimization")
    
    # AI API Key (Backend)
    from dotenv import load_dotenv
    import os
    load_dotenv()
    
    api_key = os.getenv("FPL_API_KEY")
    if not api_key:
        st.sidebar.warning("⚠️ FPL_API_KEY not found in .env")
    
    team_input = st.sidebar.text_input("Enter FPL Team ID or URL", placeholder="e.g. 123456")
    
    with st.sidebar.expander("❓ How to find your Team ID"):
        st.write("""
        1. Go to the **[FPL Website](https://fantasy.premierleague.com/)** and log in.
        2. Click on the **'Points'** tab (not 'Pick Team').
        3. Look at the URL in your browser address bar.
        4. It will look like: `.../entry/123456/event/...`
        5. The number between `entry/` and `/event` is your **Team ID** (e.g., `123456`).
        """)
    strategy = st.sidebar.selectbox(
        "Optimization Strategy",
        options=["balanced", "form", "value", "expected", "differential", "fixture"],
        index=0,
        help="Balanced: Mix of form & value. Form: Recent performance. Value: Points per million."
    )
    
    run_btn = st.sidebar.button("🚀 Optimize Team", type="primary")
    
    # --- Main Layout (Split View) ---
    # Create two columns: Main Dashboard (Left) and AI Analyst (Right)
    main_col, ai_col = st.columns([0.65, 0.35], gap="medium")
    
    with main_col:
        # --- Landing Page Metrics (The "Ticker") ---
        st.subheader("🔥 Market Movers & Value Picks")
        
        col1, col2, col3 = st.columns(3)
        
        # Top Form Players
        top_form = players_df.nlargest(3, 'form')
        with col1:
            st.markdown("### 📈 Top Form")
            for _, player in top_form.iterrows():
                st.metric(
                    label=f"{player['name']} ({player['team']})",
                    value=f"{player['form']} pts",
                    delta=f"£{player['price']}m"
                )
                
        # Top Value Picks (Points per Million)
        top_value = players_df.nlargest(3, 'points_per_million')
        with col2:
            st.markdown("### 💰 Best Value")
            for _, player in top_value.iterrows():
                st.metric(
                    label=f"{player['name']} ({player['position']})",
                    value=f"{player['points_per_million']:.1f} PPM",
                    delta=f"{player['total_points']} pts"
                )

        # Dynamic Fixture Difficulty (Hardest/Easiest)
        # We need to aggregate difficulty by team
        team_difficulty = []
        for team_id, data in dm.fixture_difficulty.items():
            team_difficulty.append({
                'team': data['team_name'],
                'difficulty': data['average_difficulty']
            })
        difficulty_df = pd.DataFrame(team_difficulty)
        
        with col3:
            st.markdown("### 🗓️ Fixture Watch")
            easiest = difficulty_df.nsmallest(1, 'difficulty').iloc[0]
            hardest = difficulty_df.nlargest(1, 'difficulty').iloc[0]
            
            st.info(f"🟢 **Easiest Run:** {easiest['team']} (Avg Diff: {easiest['difficulty']:.2f})")
            st.error(f"🔴 **Hardest Run:** {hardest['team']} (Avg Diff: {hardest['difficulty']:.2f})")

        st.divider()

        # --- Visuals (Scatter Plot) ---
        st.subheader("📊 Player Performance Analysis")
        
        # Filters for Scatter Plot
        col_filter1, col_filter2 = st.columns(2)
        with col_filter1:
            pos_filter = st.multiselect(
                "Filter by Position",
                options=players_df['position'].unique(),
                default=players_df['position'].unique()
            )
        with col_filter2:
            price_range = st.slider(
                "Price Range (£m)",
                min_value=float(players_df['price'].min()),
                max_value=float(players_df['price'].max()),
                value=(4.0, 15.0)
            )
            
        filtered_df = players_df[
            (players_df['position'].isin(pos_filter)) &
            (players_df['price'] >= price_range[0]) &
            (players_df['price'] <= price_range[1])
        ]
        
        fig = px.scatter(
            filtered_df,
            x="price",
            y="total_points",
            color="position",
            hover_name="name",
            hover_data=["team", "form", "selected_by_percent"],
            title="Price vs Total Points (Value Identification)",
            labels={"price": "Price (£m)", "total_points": "Total Points"},
            template="plotly_dark",
            size="selected_by_percent",
            size_max=15
        )
        st.plotly_chart(fig, use_container_width=True)
        
        if run_btn and team_input:
            team_id = extract_team_id_from_url(team_input)
            if not team_id:
                st.sidebar.error("Invalid Team ID or URL")
            else:
                with st.spinner("Analyzing Team & Calculating Optimal Transfers..."):
                    result = controller.analyze_user_team(team_id)
                    
                    if "error" in result:
                        st.error(result['error'])
                    else:
                        display_results(result, strategy)
                        # Store result in session state for AI context
                        st.session_state['user_team_data'] = result

    with ai_col:
        st.markdown("### 🤖 AI Analyst")
        st.caption("Your personal FPL assistant")
        
        # Import here to avoid circular imports or load issues
        from ai_utils import FPLAIContextManager, get_ai_response
        
        # Container for chat history to keep it scrollable/contained
        chat_container = st.container(height=600)
        
        if "messages" not in st.session_state:
            st.session_state.messages = []

        # Display chat messages
        with chat_container:
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

        # Quick Prompts (Compact)
        st.markdown("###### Quick Actions")
        col_q1, col_q2 = st.columns(2)
        prompt = None
        if col_q1.button("📊 Rate Team", use_container_width=True):
            prompt = "Rate my current team based on form and fixtures."
        if col_q2.button("🔄 Transfers", use_container_width=True):
            prompt = "Who should I transfer out and who should I bring in?"

        # Chat Input
        if user_input := st.chat_input("Ask about players, fixtures...") or prompt:
            # If it was a button click, use that prompt
            if prompt and not user_input:
                user_input = prompt
                
            # Add user message to chat history
            st.session_state.messages.append({"role": "user", "content": user_input})
            with chat_container:
                with st.chat_message("user"):
                    st.markdown(user_input)

            # Generate AI response
            with chat_container:
                with st.chat_message("assistant"):
                    with st.spinner("Thinking..."):
                        # Get context
                        user_team_data = st.session_state.get('user_team_data', {})
                        context_manager = FPLAIContextManager(players_df, user_team_data)
                        
                        response = get_ai_response(st.session_state.messages, api_key, context_manager)
                        st.markdown(response)
                    
            # Add assistant response to chat history
            st.session_state.messages.append({"role": "assistant", "content": response})

def display_results(result, strategy):
    st.header(f"🏆 Optimization Results ({strategy.title()} Strategy)")
    
    # Team Info
    info = result['team_info']
    st.success(f"Analyzed Team: **{info['name']}** (Manager: {info['player_first_name']} {info['player_last_name']})")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Current GW", result['gameweek'])
    col2.metric("Team Value", f"£{result['total_cost']}m")
    col3.metric("Total Points", result['total_points'])
    
    # Transfer Suggestions
    st.subheader("🔄 Transfer Suggestions")
    
    suggestions = result['transfer_suggestions'].get('transfers', [])
    summary = result['transfer_suggestions'].get('summary', {})
    
    if not suggestions:
        st.info("No transfers recommended based on this strategy.")
    else:
        # Display Recommendation
        rec_text = summary.get('recommendation', '')
        if "Strong" in rec_text:
            st.success(f"💡 {rec_text}")
        elif "Good" in rec_text:
            st.info(f"💡 {rec_text}")
        else:
            st.warning(f"💡 {rec_text}")
            
        # Display Transfers
        for transfer in suggestions:
            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 0.2, 1])
                
                with c1:
                    st.markdown(f"**OUT** ❌")
                    out_p = transfer['transfer_out']
                    st.write(f"{out_p['name']} ({out_p['team']}) - £{out_p['price']}m")
                    st.caption(f"Form: {out_p['value']:.2f}")
                    
                with c2:
                    st.markdown("➡️")
                    
                with c3:
                    st.markdown(f"**IN** ✅")
                    in_p = transfer['transfer_in']
                    st.write(f"{in_p['name']} ({in_p['team']}) - £{in_p['price']}m")
                    st.caption(f"Form: {in_p['value']:.2f}")
                
                st.markdown(f"**Net Benefit:** {transfer['net_benefit']} pts | **Cost:** {transfer['transfer_cost']} pts")

    # Optimal Team Display (Optional - could be a table or pitch view)
    st.subheader("🌟 Optimal Squad (Wildcard)")
    optimal_data = result['optimal_comparisons'].get(strategy, {})
    if optimal_data:
        st.dataframe(
            pd.DataFrame(optimal_data['starting_11'])[['name', 'team', 'position', 'price', 'form', 'expected_goal_involvements']],
            use_container_width=True
        )

if __name__ == "__main__":
    main()
