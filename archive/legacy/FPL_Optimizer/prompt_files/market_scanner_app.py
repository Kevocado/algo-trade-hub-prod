"""
Live Market Signal Dashboard - Streamlined
Real-time prediction market scanner with manual execution
Shows opportunities, you trade on Kalshi/Polymarket yourself
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import time
import requests
import json
from typing import List, Dict, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page config
st.set_page_config(
    page_title="Market Scanner 🎯",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS - Clean, minimal design
st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
    }
    .signal-card {
        background: rgba(26, 31, 58, 0.6);
        backdrop-filter: blur(10px);
        padding: 25px;
        border-radius: 15px;
        border: 1px solid rgba(42, 63, 95, 0.5);
        margin: 15px 0;
        transition: all 0.3s ease;
    }
    .signal-card:hover {
        border-color: #00ff88;
        box-shadow: 0 0 20px rgba(0, 255, 136, 0.2);
        transform: translateY(-3px);
    }
    .edge-badge {
        background: linear-gradient(135deg, #00ff88 0%, #00cc6a 100%);
        color: #000;
        padding: 8px 16px;
        border-radius: 20px;
        font-weight: bold;
        font-size: 1.2em;
        display: inline-block;
    }
    .confidence-high { border-left: 5px solid #00ff88; }
    .confidence-medium { border-left: 5px solid #ffaa00; }
    .confidence-low { border-left: 5px solid #00aaff; }
    
    h1, h2, h3 { color: #00ff88; }
    .metric-value { font-size: 2em; font-weight: bold; color: #00ff88; }
</style>
""", unsafe_allow_html=True)


class PolymarketScanner:
    """Scan Polymarket for trading opportunities"""
    
    def __init__(self):
        self.base_url = "https://gamma-api.polymarket.com"
        
    def get_active_markets(self, limit: int = 1000) -> List[Dict]:
        """Fetch active markets"""
        try:
            response = requests.get(
                f"{self.base_url}/markets",
                params={'closed': False, 'limit': limit},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            return []
    
    def get_market_orderbook(self, condition_id: str) -> Dict:
        """Get orderbook for a specific market"""
        try:
            response = requests.get(
                f"{self.base_url}/book",
                params={'token_id': condition_id}
            )
            response.raise_for_status()
            return response.json()
        except:
            return {}


class MarketAnalyzer:
    """Analyze markets and calculate fair value"""
    
    def analyze_weather_market(self, question: str) -> Dict:
        """Analyze weather-related markets using NOAA"""
        # TODO: Integrate NOAA API
        # For now, return placeholder
        return {
            'fair_value': 0.65,
            'confidence': 'MEDIUM',
            'reasoning': 'Based on NOAA forecast data (placeholder)',
            'sources': ['NOAA', 'Weather.com']
        }
    
    def analyze_sports_market(self, question: str) -> Dict:
        """Analyze sports markets"""
        # TODO: Integrate ESPN/injury reports
        return {
            'fair_value': 0.55,
            'confidence': 'MEDIUM',
            'reasoning': 'Based on team stats and injury reports (placeholder)',
            'sources': ['ESPN', 'Team Stats']
        }
    
    def analyze_crypto_market(self, question: str) -> Dict:
        """Analyze crypto markets"""
        # TODO: Integrate on-chain data
        return {
            'fair_value': 0.60,
            'confidence': 'MEDIUM',
            'reasoning': 'Based on on-chain metrics and sentiment (placeholder)',
            'sources': ['CoinGecko', 'Sentiment']
        }
    
    def calculate_fair_value(self, market: Dict) -> Dict:
        """Calculate fair value for any market"""
        question = market.get('question', '').lower()
        
        # Route to appropriate analyzer
        if any(w in question for w in ['rain', 'snow', 'temperature', 'weather']):
            return self.analyze_weather_market(question)
        elif any(w in question for w in ['win', 'game', 'match', 'score']):
            return self.analyze_sports_market(question)
        elif any(w in question for w in ['btc', 'eth', 'bitcoin', 'ethereum', 'crypto']):
            return self.analyze_crypto_market(question)
        else:
            # Default analysis
            return {
                'fair_value': 0.5,
                'confidence': 'LOW',
                'reasoning': 'Insufficient data sources',
                'sources': ['Market Price']
            }


class SignalGenerator:
    """Generate trading signals from market analysis"""
    
    def __init__(self, min_edge: float = 0.08, max_kelly: float = 0.06):
        self.min_edge = min_edge
        self.max_kelly = max_kelly
        self.analyzer = MarketAnalyzer()
    
    def generate_signals(self, markets: List[Dict], bankroll: float = 1000) -> List[Dict]:
        """Scan markets and generate signals"""
        signals = []
        
        for market in markets:
            try:
                # Get market price
                market_price = float(market.get('outcomePrices', [0.5])[0])
                
                # Skip if low volume
                volume = float(market.get('volume', 0))
                if volume < 1000:
                    continue
                
                # Calculate fair value
                analysis = self.analyzer.calculate_fair_value(market)
                fair_value = analysis['fair_value']
                
                # Calculate edge
                edge = fair_value - market_price
                edge_pct = (edge / market_price * 100) if market_price > 0 else 0
                
                # Skip if below minimum edge
                if abs(edge) < self.min_edge:
                    continue
                
                # Skip low confidence
                if analysis['confidence'] == 'LOW':
                    continue
                
                # Determine direction
                direction = 'BUY YES' if edge > 0 else 'BUY NO'
                
                # Calculate position size (Kelly)
                cost = market_price if edge > 0 else (1 - market_price)
                kelly = abs(edge) / (1 - cost) if cost < 1 else 0
                kelly = min(kelly, self.max_kelly)
                position_size = bankroll * kelly
                
                # Skip if position too small
                if position_size < 5:
                    continue
                
                # Calculate expires time
                end_date = market.get('endDateIso', datetime.now().isoformat())
                expires_at = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                time_left = expires_at - datetime.now()
                
                if time_left.total_seconds() < 0:
                    continue
                
                hours_left = time_left.total_seconds() / 3600
                if hours_left < 1:
                    expires_str = f"{int(time_left.total_seconds() / 60)}m"
                elif hours_left < 24:
                    expires_str = f"{int(hours_left)}h"
                else:
                    expires_str = f"{int(hours_left / 24)}d"
                
                # Build signal
                signal = {
                    'market_id': market.get('id', 'unknown'),
                    'condition_id': market.get('conditionId', ''),
                    'title': market.get('question', 'Unknown'),
                    'platform': 'Polymarket',
                    'direction': direction,
                    'market_price': market_price,
                    'fair_value': fair_value,
                    'edge': edge,
                    'edge_pct': edge_pct,
                    'confidence': analysis['confidence'],
                    'reasoning': analysis['reasoning'],
                    'sources': analysis['sources'],
                    'kelly_pct': kelly * 100,
                    'position_size': position_size,
                    'volume': volume,
                    'expires_in': expires_str,
                    'expires_at': expires_at,
                    'url': f"https://polymarket.com/event/{market.get('slug', '')}",
                    'created_at': datetime.now()
                }
                
                signals.append(signal)
                
            except Exception as e:
                logger.error(f"Error analyzing market: {e}")
                continue
        
        # Sort by edge (highest first)
        signals.sort(key=lambda x: abs(x['edge_pct']), reverse=True)
        
        return signals


class Dashboard:
    """Main dashboard class"""
    
    def __init__(self):
        self.init_session_state()
        self.scanner = PolymarketScanner()
        self.signal_gen = SignalGenerator()
    
    def init_session_state(self):
        """Initialize session state"""
        if 'signals' not in st.session_state:
            st.session_state.signals = []
        if 'bankroll' not in st.session_state:
            st.session_state.bankroll = 1000
        if 'last_scan' not in st.session_state:
            st.session_state.last_scan = None
        if 'scan_count' not in st.session_state:
            st.session_state.scan_count = 0
        if 'auto_refresh' not in st.session_state:
            st.session_state.auto_refresh = False
    
    def render_header(self):
        """Render header"""
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col1:
            st.markdown("# 🎯 LIVE MARKET SCANNER")
            st.caption("Find mispriced prediction markets • Trade manually on Kalshi/Polymarket")
        
        with col2:
            if st.button("🔄 Scan Markets", use_container_width=True, type="primary"):
                self.scan_markets()
                st.rerun()
        
        with col3:
            st.session_state.auto_refresh = st.checkbox("Auto-refresh", value=st.session_state.auto_refresh)
    
    def render_stats(self):
        """Render key stats"""
        col1, col2, col3, col4, col5 = st.columns(5)
        
        signals = st.session_state.signals
        active = len(signals)
        avg_edge = np.mean([s['edge_pct'] for s in signals[:10]]) if signals else 0
        
        with col1:
            st.metric("💰 Bankroll", f"${st.session_state.bankroll:,.0f}")
        
        with col2:
            st.metric("🎯 Signals Found", active)
        
        with col3:
            st.metric("📊 Avg Edge", f"{avg_edge:.1f}%")
        
        with col4:
            st.metric("🔍 Scans", st.session_state.scan_count)
        
        with col5:
            if st.session_state.last_scan:
                elapsed = (datetime.now() - st.session_state.last_scan).seconds
                st.metric("⏱️ Last Scan", f"{elapsed}s ago")
            else:
                st.metric("⏱️ Last Scan", "Never")
    
    def render_signal_card(self, signal: Dict, index: int):
        """Render individual signal"""
        conf_class = f"confidence-{signal['confidence'].lower()}"
        edge_color = "#00ff88" if signal['edge_pct'] > 15 else "#ffaa00"
        
        # Card container
        with st.container():
            st.markdown(f"""
            <div class="signal-card {conf_class}">
                <div style="display: flex; justify-content: space-between; align-items: start;">
                    <div style="flex: 1;">
                        <h3>#{index} {signal['title'][:100]}</h3>
                        <p style="color: #888; margin: 5px 0;">
                            {signal['platform']} • Expires in {signal['expires_in']}
                        </p>
                    </div>
                    <div style="text-align: right;">
                        <span class="edge-badge">+{signal['edge_pct']:.1f}%</span>
                    </div>
                </div>
                
                <hr style="border-color: rgba(42, 63, 95, 0.5); margin: 15px 0;">
                
                <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 15px 0;">
                    <div>
                        <small style="color: #888;">Your Model</small><br>
                        <strong style="color: #00ff88; font-size: 1.3em;">{signal['fair_value']:.0%}</strong>
                    </div>
                    <div>
                        <small style="color: #888;">Market Price</small><br>
                        <strong style="color: #fff; font-size: 1.3em;">{signal['market_price']:.0%}</strong>
                    </div>
                    <div>
                        <small style="color: #888;">Direction</small><br>
                        <strong style="color: {'#00ff88' if 'YES' in signal['direction'] else '#ff5555'}; font-size: 1.3em;">
                            {signal['direction']}
                        </strong>
                    </div>
                    <div>
                        <small style="color: #888;">Confidence</small><br>
                        <strong style="font-size: 1.3em;">{signal['confidence']}</strong>
                    </div>
                </div>
                
                <div style="background: rgba(0,0,0,0.3); padding: 15px; border-radius: 10px; margin: 15px 0;">
                    <strong style="color: #00ff88;">💡 Reasoning:</strong><br>
                    <span style="color: #ccc;">{signal['reasoning']}</span>
                </div>
                
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 15px;">
                    <div>
                        <small style="color: #888;">Position Size (Kelly): </small>
                        <strong style="color: #00ff88; font-size: 1.2em;">${signal['position_size']:.0f}</strong>
                        <small style="color: #888;"> ({signal['kelly_pct']:.1f}%)</small>
                    </div>
                    <div>
                        <small style="color: #888;">Volume: ${signal['volume']:,.0f}</small>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Action buttons
            col1, col2, col3 = st.columns([2, 1, 1])
            
            with col1:
                if st.button(f"🔗 Open on {signal['platform']}", key=f"open_{index}", use_container_width=True):
                    st.link_button("Go to Market", signal['url'])
            
            with col2:
                if st.button("📋 Copy Details", key=f"copy_{index}", use_container_width=True):
                    details = f"{signal['title']}\n{signal['direction']} at {signal['market_price']:.0%}\nEdge: +{signal['edge_pct']:.1f}%"
                    st.code(details)
            
            with col3:
                if st.button("✅ Mark Traded", key=f"traded_{index}", use_container_width=True):
                    st.success("Marked as traded!")
    
    def render_signals(self):
        """Render all signals"""
        signals = st.session_state.signals
        
        if not signals:
            st.info("👆 Click 'Scan Markets' to find opportunities")
            return
        
        # Filters
        col1, col2, col3 = st.columns(3)
        
        with col1:
            min_edge = st.slider("Min Edge %", 0, 30, 8, key="min_edge_filter")
        
        with col2:
            confidence = st.multiselect(
                "Confidence",
                ['HIGH', 'MEDIUM', 'LOW'],
                default=['HIGH', 'MEDIUM'],
                key="confidence_filter"
            )
        
        with col3:
            sort_by = st.selectbox("Sort By", ['Edge', 'Volume', 'Time'], key="sort_filter")
        
        # Filter signals
        filtered = [
            s for s in signals
            if s['edge_pct'] >= min_edge and s['confidence'] in confidence
        ]
        
        if not filtered:
            st.warning("No signals match your filters")
            return
        
        # Sort
        if sort_by == 'Volume':
            filtered.sort(key=lambda x: x['volume'], reverse=True)
        elif sort_by == 'Time':
            filtered.sort(key=lambda x: x['expires_at'])
        
        st.markdown(f"## 🔥 {len(filtered)} Opportunities Found")
        st.markdown("---")
        
        # Render cards
        for i, signal in enumerate(filtered, 1):
            self.render_signal_card(signal, i)
            if i < len(filtered):
                st.markdown("<br>", unsafe_allow_html=True)
    
    def render_sidebar(self):
        """Render sidebar"""
        with st.sidebar:
            st.markdown("## ⚙️ Settings")
            
            # Bankroll
            new_bankroll = st.number_input(
                "💰 Your Bankroll",
                min_value=100,
                max_value=100000,
                value=st.session_state.bankroll,
                step=100,
                help="Used to calculate Kelly position sizes"
            )
            st.session_state.bankroll = new_bankroll
            
            st.markdown("---")
            
            st.markdown("## 🎯 Signal Settings")
            
            min_edge = st.slider(
                "Minimum Edge %",
                0, 50, 8,
                help="Only show opportunities above this edge"
            )
            
            max_kelly = st.slider(
                "Max Kelly %",
                1, 20, 6,
                help="Maximum position size as % of bankroll"
            )
            
            # Update signal generator
            self.signal_gen.min_edge = min_edge / 100
            self.signal_gen.max_kelly = max_kelly / 100
            
            st.markdown("---")
            
            st.markdown("## 📊 Stats")
            
            if st.session_state.signals:
                total_signals = len(st.session_state.signals)
                high_conf = len([s for s in st.session_state.signals if s['confidence'] == 'HIGH'])
                
                st.metric("Total Signals", total_signals)
                st.metric("High Confidence", high_conf)
                
                if total_signals > 0:
                    st.metric("High Conf %", f"{high_conf/total_signals*100:.0f}%")
            
            st.markdown("---")
            
            if st.button("📥 Export Signals", use_container_width=True):
                if st.session_state.signals:
                    df = pd.DataFrame(st.session_state.signals)
                    csv = df.to_csv(index=False)
                    st.download_button(
                        "Download CSV",
                        csv,
                        f"signals_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        "text/csv",
                        use_container_width=True
                    )
    
    def scan_markets(self):
        """Scan markets for signals"""
        with st.spinner("🔍 Scanning markets..."):
            # Fetch markets
            markets = self.scanner.get_active_markets(limit=1000)
            
            if not markets:
                st.error("Failed to fetch markets")
                return
            
            # Generate signals
            signals = self.signal_gen.generate_signals(
                markets,
                bankroll=st.session_state.bankroll
            )
            
            # Update state
            st.session_state.signals = signals
            st.session_state.last_scan = datetime.now()
            st.session_state.scan_count += 1
            
            st.success(f"✅ Found {len(signals)} opportunities from {len(markets)} markets")
    
    def run(self):
        """Run dashboard"""
        self.render_sidebar()
        self.render_header()
        
        st.markdown("---")
        self.render_stats()
        st.markdown("---")
        
        self.render_signals()
        
        # Auto-refresh
        if st.session_state.auto_refresh:
            time.sleep(300)  # 5 minutes
            st.rerun()


if __name__ == "__main__":
    dashboard = Dashboard()
    dashboard.run()
