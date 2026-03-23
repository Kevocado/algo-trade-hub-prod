from collections import defaultdict
from typing import Dict, List
import numpy as np

class FPLController:
    """Controller to handle business logic and coordination between DataManager and Optimizer"""
    
    def __init__(self, data_manager, optimizer):
        self.data_manager = data_manager
        self.optimizer = optimizer
        
    def analyze_user_team(self, team_id: str) -> Dict:
        """Enhanced user team analysis"""
        if not team_id:
            return {"error": "Invalid Team ID"}
        
        user_team = self.data_manager.fetch_user_team(team_id)
        if not user_team:
            return {"error": f"Could not fetch team data for ID: {team_id}"}
        
        picks = user_team['picks'].get('picks', [])
        team_info = user_team['team_info']
        
        # Analyze current team
        current_team = []
        total_cost = 0
        total_points = 0
        
        # We need players_df from optimizer or data_manager
        # Assuming optimizer has the latest players_df
        players_df = self.optimizer.players_df
        
        for pick in picks:
            player_row = players_df[players_df['id'] == pick['element']]
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
        # Try 'balanced' first, then fallback to others
        best_strategy = 'balanced'
        if 'all_players' not in optimal_comparisons.get(best_strategy, {}):
            # Find first successful strategy
            for s in strategies:
                if 'all_players' in optimal_comparisons.get(s, {}):
                    best_strategy = s
                    break
        
        best_optimal = optimal_comparisons.get(best_strategy, {})
        transfer_suggestions = {}
        
        if 'all_players' in best_optimal and current_team:
            transfer_suggestions = self.optimizer.suggest_transfers(
                current_team, best_optimal['all_players']
            )
        elif not current_team:
            print("Warning: Current team is empty. Check player data matching.")
        
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
