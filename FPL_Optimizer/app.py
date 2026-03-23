from flask import Flask, render_template, request, jsonify
from data_manager import AdvancedFPLDataManager
from optimizer import AdvancedFPLOptimizer
from collections import defaultdict
from typing import Dict
import os
import json
import numpy as np
from chatbot import FPLChatbot  # Add this import at the top
##this is a test
class EnhancedFPLWebApp:
    """Enhanced web application with advanced features"""
    
    def __init__(self):
        self.app = Flask(__name__)
        self.data_manager = AdvancedFPLDataManager()
        self.optimizer = None
        self.players_df = None
        self.chatbot = None  # Add this line
        
        # Helper function to clean data for JSON serialization
        def clean_for_json(obj):
            if isinstance(obj, dict):
                return {k: clean_for_json(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_for_json(item) for item in obj]
            elif isinstance(obj, float) and np.isnan(obj):
                return None
            elif isinstance(obj, (np.integer, np.floating)):
                return obj.item()
            else:
                return obj
        
        self.clean_for_json = clean_for_json
        self.setup_routes()
    
    def initialize_data(self):
        """Initialize enhanced FPL data"""
        try:
            print("🔄 Fetching bootstrap data...")
            bootstrap_data = self.data_manager.fetch_bootstrap_data()
            if not bootstrap_data:
                return False
            
            print("📊 Processing enhanced player data...")
            self.players_df = self.data_manager.process_enhanced_player_data(bootstrap_data)
            
            print("🏟️ Fetching fixture data...")
            self.data_manager.fetch_fixtures()
            
            print("🧠 Initializing advanced optimizer...")
            self.optimizer = AdvancedFPLOptimizer(self.players_df)
            
            print("🤖 Initializing chatbot...")  # Add this
            self.chatbot = FPLChatbot(self.optimizer, self.players_df, self.data_manager)
            
            return True
        except Exception as e:
            print(f"Error initializing data: {e}")
            return False
    
    def extract_team_id_from_url(self, url_or_id: str) -> str:
        """Extract team ID from FPL URL or return if already an ID"""
        import re
        
        if url_or_id.isdigit():
            return url_or_id
        
        patterns = [
            r'fantasy\.premierleague\.com/entry/(\d+)',
            r'/entry/(\d+)/',
            r'/entry/(\d+)',
            r'team/(\d+)',
            r'(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url_or_id)
            if match:
                return match.group(1)
        
        numbers = re.findall(r'\d+', url_or_id)
        if numbers:
            return max(numbers, key=len)
        
        return None
    
    def analyze_user_team(self, url_or_id: str) -> Dict:
        """Enhanced user team analysis"""
        team_id = self.extract_team_id_from_url(url_or_id)
        
        if not team_id:
            return {"error": "Could not extract team ID from the provided URL/ID"}
        
        user_team = self.data_manager.fetch_user_team(team_id)
        if not user_team:
            return {"error": f"Could not fetch team data for ID: {team_id}"}
        
        picks = user_team['picks']['picks']
        team_info = user_team['team_info']
        
        # Analyze current team
        current_team = []
        total_cost = 0
        total_points = 0
        
        for pick in picks:
            player_row = self.players_df[self.players_df['id'] == pick['element']]
            if not player_row.empty:
                player = player_row.iloc[0].to_dict()
                player['is_captain'] = pick['is_captain']
                player['is_vice_captain'] = pick['is_vice_captain']
                player['multiplier'] = pick['multiplier']
                current_team.append(player)
                total_cost += player['price']
                total_points += player['total_points']
        
        team_by_position = defaultdict(list)
        for player in current_team:
            team_by_position[player['position']].append(player)
        
        # Run multiple optimization strategies
        strategies = ['balanced', 'form', 'expected', 'fixture', 'differential']
        optimal_comparisons = {}
        
        for strategy in strategies:
            optimal_result = self.optimizer.optimize_team(strategy=strategy)
            if 'error' not in optimal_result:
                optimal_comparisons[strategy] = optimal_result
        
        # Generate transfer suggestions
        best_optimal = optimal_comparisons.get('balanced', {})
        transfer_suggestions = {}
        if 'all_players' in best_optimal:
            transfer_suggestions = self.optimizer.suggest_transfers(
                current_team, best_optimal['all_players']
            )
        
        return {
            'team_info': team_info,
            'current_team': current_team,
            'team_by_position': dict(team_by_position),
            'total_cost': round(total_cost, 1),
            'total_points': total_points,
            'gameweek': user_team['gameweek'],
            'optimal_comparisons': optimal_comparisons,
            'transfer_suggestions': transfer_suggestions,
            'extracted_team_id': team_id,
            'team_analysis': self.optimizer.analyze_team_composition(current_team) if current_team else {}
        }
    
    def setup_routes(self):
        """Setup enhanced Flask routes"""
        
        @self.app.route('/')
        def index():
            return render_template('modern_index.html')
        
        @self.app.route('/api/initialize')
        def initialize():
            success = self.initialize_data()
            player_count = len(self.players_df) if self.players_df is not None else 0
            return jsonify({
                'success': success,
                'player_count': player_count,
                'current_gameweek': self.data_manager.current_gameweek
            })
        
        @self.app.route('/api/optimize')
        def optimize():
            strategy = request.args.get('strategy', 'balanced')
            min_minutes = int(request.args.get('min_minutes', 300))
            
            if not self.optimizer:
                return jsonify({'error': 'Data not initialized'})
            
            result = self.optimizer.optimize_team(
                strategy=strategy,
                min_minutes=min_minutes
            )
            return jsonify(self.clean_for_json(result))
        
        @self.app.route('/api/analyze_team')
        def analyze_team():
            url_or_id = request.args.get('team_url_or_id')
            if not url_or_id:
                return jsonify({'error': 'Team URL or ID required'})
            
            if not self.optimizer:
                return jsonify({'error': 'Data not initialized'})
            
            result = self.analyze_user_team(url_or_id)
            return jsonify(self.clean_for_json(result))
        
        @self.app.route('/api/players')
        def get_players():
            position = request.args.get('position')
            limit = int(request.args.get('limit', 20))
            sort_by = request.args.get('sort_by', 'comprehensive_value')
            
            if self.players_df is None:
                return jsonify({'error': 'Data not initialized'})
            
            df = self.players_df.copy()
            if position:
                df = df[df['position'] == position]
            
            # Sort by the specified metric
            if sort_by in df.columns:
                top_players = df.nlargest(limit, sort_by)
            else:
                top_players = df.nlargest(limit, 'comprehensive_value')
            
            return jsonify(self.clean_for_json(top_players.to_dict('records')))
        
        @self.app.route('/api/compare_strategies')
        def compare_strategies():
            if not self.optimizer:
                return jsonify({'error': 'Data not initialized'})
            
            strategies = ['balanced', 'form', 'expected', 'fixture', 'differential', 'defensive']
            results = {}
            
            for strategy in strategies:
                result = self.optimizer.optimize_team(strategy=strategy)
                if 'error' not in result:
                    results[strategy] = {
                        'total_cost': result['total_cost'],
                        'total_score': result['total_score'],
                        'captaincy': result['captaincy'],
                        'team_analysis': result['team_analysis']
                    }
            
            return jsonify(self.clean_for_json(results))
        
        @self.app.route('/api/fixture_analysis')
        def fixture_analysis():
            if not self.data_manager.fixture_difficulty:
                return jsonify({'error': 'Fixture data not available'})
            
            return jsonify(self.data_manager.fixture_difficulty)
        
        @self.app.route('/api/transfer_suggestions')
        def transfer_suggestions():
            current_team_ids = request.args.get('current_team_ids', '').split(',')
            strategy = request.args.get('strategy', 'balanced')