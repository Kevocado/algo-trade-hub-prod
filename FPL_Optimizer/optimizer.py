import pulp
import pandas as pd
import numpy as np
from collections import defaultdict
from typing import Dict, List
from models import EnhancedPlayerData 


class AdvancedFPLOptimizer:
    """Enhanced optimizer with multiple strategies and transfer analysis"""
    
    def __init__(self, players_df: pd.DataFrame):
        self.players_df = players_df
        self.position_limits = {
            'Goalkeeper': {'min': 2, 'max': 2},
            'Defender': {'min': 5, 'max': 5},
            'Midfielder': {'min': 5, 'max': 5},
            'Forward': {'min': 3, 'max': 3}
        }
        self.playing_position_limits = {
            'Goalkeeper': {'min': 1, 'max': 1},
            'Defender': {'min': 3, 'max': 5},
            'Midfielder': {'min': 2, 'max': 5},
            'Forward': {'min': 1, 'max': 3}
        }
        self.budget = 100.0
        self.max_players_per_team = 3
        self.playing_team_max = 11
        
    def optimize_team(self, strategy: str = 'balanced', **kwargs) -> Dict:
        """Optimize team with different strategies"""
        
        strategies = {
            'balanced': 'comprehensive_value',
            'form': 'form',
            'value': 'points_per_million',
            'expected': 'xgi_per_game',
            'differential': 'transfer_momentum',
            'fixture': 'fixture_adjusted_score',
            'captain_focus': 'captain_score',
            'defensive': 'defensive_score'
        }
        
        objective_column = strategies.get(strategy, 'comprehensive_value')
        return self._optimize_with_constraints(objective_column, **kwargs)
    
    def _optimize_with_constraints(self, objective_column: str, 
                                 must_include: List[str] = None,
                                 exclude_players: List[str] = None,
                                 min_minutes: int = 300,
                                 max_price_per_position: Dict = None,
                                 min_fixtures_remaining: int = 0) -> Dict:
        """Core optimization with enhanced constraints"""
        
        df = self.players_df.copy()
        
        # Apply filters
        df = df[df['minutes'] >= min_minutes]
        
        if exclude_players:
            df = df[~df['name'].isin(exclude_players)]
        
        # Filter by availability
        df = df[(df['chance_of_playing_this_round'].isna()) | 
                (df['chance_of_playing_this_round'] >= 75)]
        
        df = df.reset_index(drop=True)
        
        if df.empty:
            return {"error": "No players meet the specified criteria"}
        
        # Create optimization problem
        prob = pulp.LpProblem("Enhanced_FPL_Selection", pulp.LpMaximize)
        
        # Decision variables
        player_vars = {idx: pulp.LpVariable(f"player_{idx}", cat='Binary') 
                      for idx in range(len(df))}
        
        # Objective function
        prob += pulp.lpSum([player_vars[idx] * df.loc[idx, objective_column] 
                           for idx in range(len(df))])
        
        # Standard constraints
        prob += pulp.lpSum([player_vars[idx] * df.loc[idx, 'price'] 
                           for idx in range(len(df))]) <= self.budget
        
        prob += pulp.lpSum([player_vars[idx] for idx in range(len(df))]) == 15
        
        # Position constraints
        for position, limits in self.position_limits.items():
            position_players = df[df['position'] == position].index
            prob += pulp.lpSum([player_vars[idx] for idx in position_players]) == limits['max']
        
        # Team constraints
        for team in df['team'].unique():
            team_players = df[df['team'] == team].index
            prob += pulp.lpSum([player_vars[idx] for idx in team_players]) <= self.max_players_per_team
        
        # Must include constraints
        if must_include:
            for player_name in must_include:
                player_indices = df[df['name'] == player_name].index
                if len(player_indices) > 0:
                    prob += player_vars[player_indices[0]] == 1
        
        # Price per position constraints
        if max_price_per_position:
            for position, max_price in max_price_per_position.items():
                position_players = df[df['position'] == position].index
                for idx in position_players:
                    prob += player_vars[idx] * df.loc[idx, 'price'] <= max_price
        
        # Solve
        prob.solve(pulp.PULP_CBC_CMD(msg=0))
        
        if prob.status == pulp.LpStatusOptimal:
            # Extract the full squad of 15 players
            full_squad = self._extract_solution(df, player_vars, objective_column)
            
            if 'error' in full_squad:
                return full_squad
            
            # Extract the best starting 11
            starting_11 = self._extract_starting_11(full_squad['selected_players'], df)
            
            # Organize by position for frontend
            team_by_position = defaultdict(list)
            for player in full_squad['selected_players']:
                team_by_position[player['position']].append(player)
            
            # Generate captaincy suggestions
            captaincy = self.suggest_captaincy(full_squad['selected_players'])
            
            # Analyze team composition
            team_analysis = self.analyze_team_composition(full_squad['selected_players'])
            
            return {
                "all_players": full_squad['selected_players'],
                "starting_11": starting_11,
                "substitutes": full_squad['substitutes'],
                "team_by_position": dict(team_by_position),
                "total_cost": full_squad['summary']['total_cost'],
                "total_score": full_squad['summary']['total_score'],
                "captaincy": captaincy,
                "team_analysis": team_analysis
            }
        else:
            return {"error": f"Optimization failed: {pulp.LpStatus[prob.status]}"}
    
    def _extract_solution(self, df: pd.DataFrame, player_vars: Dict, objective_column: str) -> Dict:
        """Extract and format optimization solution into starting 11 and substitutes"""
        selected_players = []
        total_cost = 0
        total_score = 0

        # Extract selected players
        for idx in range(len(df)):
            if player_vars[idx].value() == 1:
                player_info = df.loc[idx].to_dict()
                # Normalize all numeric values that might be None or NaN
                numeric_fields = [
                    'expected_goals', 'expected_assists', 'comprehensive_value',
                    'points_per_game', 'fixture_adjusted_score', 'captain_score',
                    'selected_by_percent', 'chance_of_playing_this_round', 'chance_of_playing_next_round',
                    'form', 'influence', 'creativity', 'threat', 'ict_index', 'price', 'total_points',
                    'goals_scored', 'assists', 'clean_sheets', 'saves', 'bonus', 'bps',
                    'xg_per_game', 'xa_per_game', 'xgi_per_game', 'defensive_score',
                    'tackles_per_game', 'interceptions_per_game', 'clearances_per_game',
                    'fixture_difficulty_5gw', 'transfer_momentum', 'position_adjusted_value'
                ]
                for field in numeric_fields:
                    value = player_info.get(field)
                    if value is None or (isinstance(value, float) and np.isnan(value)):
                        player_info[field] = 0.0
                    elif isinstance(value, float):
                        player_info[field] = float(value)

                selected_players.append(player_info)
                total_cost += player_info['price']
                total_score += player_info[objective_column]

        if not selected_players:
            return {"error": "No players were selected in the optimization process"}

        # Organize by position
        team_by_position = defaultdict(list)
        for player in selected_players:
            team_by_position[player['position']].append(player)

        # Sort players within each position by the objective column (descending order)
        for position in team_by_position:
            team_by_position[position].sort(
                key=lambda x: x.get(objective_column, 0), reverse=True
            )

        # Build the starting 11 and substitutes
        starting_11 = []
        substitutes = []
        position_counts = {position: 0 for position in self.playing_position_limits.keys()}
        total_starting_players = 0

        for position, limits in self.playing_position_limits.items():
            for player in team_by_position[position]:
                if position_counts[position] < limits['max'] and total_starting_players < self.playing_team_max:
                    starting_11.append(player)
                    position_counts[position] += 1
                    total_starting_players += 1
                else:
                    substitutes.append(player)

        # Sort substitutes by the objective column (descending order)
        substitutes.sort(key=lambda x: x.get(objective_column, 0), reverse=True)

        #normalize for frontend
        for player in selected_players:
            player['chance_of_playing_this_round'] = player.get('chance_of_playing_this_round') or 100
            player['chance_of_playing_next_round'] = player.get('chance_of_playing_next_round') or 100


        # Return the structured result
        return {
            "selected_players": selected_players,  # Include this key
            "starting_11": starting_11,
            "substitutes": substitutes,
            "summary": {
                "total_cost": total_cost,
                "total_score": total_score,
                "starting_11_cost": sum(player['price'] for player in starting_11),
                "substitutes_cost": sum(player['price'] for player in substitutes),
            }
        }
    def _extract_starting_11(self, selected_players: List[Dict], df: pd.DataFrame) -> List[Dict]:
        """Extract the best starting 11 based on playing position limits and formation"""
        # Create a DataFrame for the selected players
        selected_df = pd.DataFrame(selected_players)
        
        # Sort players by their objective column (e.g., comprehensive_value) in descending order
        selected_df = selected_df.sort_values(by='comprehensive_value', ascending=False)
        
        # Initialize the starting 11
        starting_11 = []
        position_counts = {position: 0 for position in self.playing_position_limits.keys()}
        total_players = 0
    
        # Iterate through the sorted players and select the best starting 11
        for _, player in selected_df.iterrows():
            position = player['position']
            if (position_counts[position] < self.playing_position_limits[position]['max'] and
                total_players < self.playing_team_max):
                starting_11.append(player.to_dict())
                position_counts[position] += 1
                total_players += 1
    
        return starting_11
    
    def get_best_11_with_formation(self, formation: str = "3-4-3", selected_players: List[Dict] = None) -> Dict:
        """Get the best starting 11 with specific formation constraints"""
        if selected_players is None:
            # Get optimal team first
            result = self.optimize_team('balanced')
            if 'error' in result:
                return result
            selected_players = result['all_players']
        
        # Define formation constraints
        formation_constraints = {
            "3-4-3": {"Goalkeeper": 1, "Defender": 3, "Midfielder": 4, "Forward": 3},
            "3-5-2": {"Goalkeeper": 1, "Defender": 3, "Midfielder": 5, "Forward": 2},
            "4-3-3": {"Goalkeeper": 1, "Defender": 4, "Midfielder": 3, "Forward": 3},
            "4-4-2": {"Goalkeeper": 1, "Defender": 4, "Midfielder": 4, "Forward": 2},
            "4-5-1": {"Goalkeeper": 1, "Defender": 4, "Midfielder": 5, "Forward": 1},
            "5-3-2": {"Goalkeeper": 1, "Defender": 5, "Midfielder": 3, "Forward": 2},
            "5-4-1": {"Goalkeeper": 1, "Defender": 5, "Midfielder": 4, "Forward": 1}
        }
        
        if formation not in formation_constraints:
            formation = "3-4-3"  # Default formation
        
        constraints = formation_constraints[formation]
        
        # Group players by position
        players_by_position = defaultdict(list)
        for player in selected_players:
            players_by_position[player['position']].append(player)
        
        # Sort each position by comprehensive_value
        for position in players_by_position:
            players_by_position[position].sort(key=lambda x: x['comprehensive_value'], reverse=True)
        
        # Select starting 11 based on formation
        starting_11 = []
        substitutes = []
        
        for position, max_count in constraints.items():
            if position in players_by_position:
                # Take the required number for starting 11
                starting_11.extend(players_by_position[position][:max_count])
                # Rest go to substitutes
                substitutes.extend(players_by_position[position][max_count:])
        
        # Add remaining players to substitutes
        for position, players in players_by_position.items():
            if position not in constraints:
                substitutes.extend(players)
        
        # Sort substitutes by comprehensive_value
        substitutes.sort(key=lambda x: x['comprehensive_value'], reverse=True)
        
        # Select captain and vice-captain
        captaincy = self.suggest_captaincy(starting_11)
        
        return {
            "formation": formation,
            "starting_11": starting_11,
            "substitutes": substitutes[:4],  # Only 4 substitutes allowed
            "captaincy": captaincy,
            "total_cost": sum(player['price'] for player in starting_11),
            "total_value": sum(player['comprehensive_value'] for player in starting_11)
        }
    
    def suggest_captaincy(self, selected_players: List[Dict]) -> Dict:
        """Enhanced captain suggestion with multiple factors"""
        if not selected_players:
            return {}
        
        captain_candidates = []
        for player in selected_players:
            score = (
                player['captain_score'] * 0.4 +
                player['form'] * 0.2 +
                player['points_per_game'] * 0.2 +
                player['fixture_adjusted_score'] * 0.2
            )
            captain_candidates.append((player, score))
        
        captain_candidates.sort(key=lambda x: x[1], reverse=True)
        
        return {
            "captain": captain_candidates[0][0]['name'],
            "captain_score": round(captain_candidates[0][1], 2),
            "vice_captain": captain_candidates[1][0]['name'] if len(captain_candidates) > 1 else None,
            "reasoning": f"High captaincy score ({captain_candidates[0][1]:.1f}) based on form, fixtures, and expected performance"
        }
    
    def analyze_team_composition(self, selected_players: List[Dict]) -> Dict:
        """Analyze the composition and balance of selected team"""
        if not selected_players:
            return {}
        
        analysis = {
            "total_xg": sum(p['expected_goals'] for p in selected_players),
            "total_xa": sum(p['expected_assists'] for p in selected_players),
            "avg_ownership": np.mean([p['selected_by_percent'] for p in selected_players]),
            "differential_count": sum(1 for p in selected_players if p['selected_by_percent'] < 10),
            "template_count": sum(1 for p in selected_players if p['selected_by_percent'] > 30),
            "avg_fixture_difficulty": np.mean([p.get('fixture_difficulty_5gw', 3) for p in selected_players]),
            "injury_concerns": sum(1 for p in selected_players if p.get('chance_of_playing_this_round', 100) is not None and p.get('chance_of_playing_this_round', 100) < 100)
        }
        
        return analysis
    
    def suggest_transfers(self, current_team: List[Dict], optimal_team: List[Dict], 
                         free_transfers: int = 1, max_hits: int = 1, 
                         current_bank: float = 0.0) -> Dict:
        """Suggest optimal transfers from current to better team with FPL rules"""
        
        current_ids = {p['id'] for p in current_team}
        optimal_ids = {p['id'] for p in optimal_team}
        
        # Players to transfer out
        to_remove = [p for p in current_team if p['id'] not in optimal_ids]
        # Players to transfer in
        to_add = [p for p in optimal_team if p['id'] not in current_ids]
        
        if not to_remove:
            return {"message": "Your team is already optimal!", "transfers": []}
        
        # Sort by priority
        to_remove.sort(key=lambda x: x['comprehensive_value'])
        to_add.sort(key=lambda x: x['comprehensive_value'], reverse=True)
        
        # Calculate transfer suggestions with FPL rules
        transfer_suggestions = []
        total_transfers = min(len(to_remove), len(to_add), free_transfers + max_hits)
        available_bank = current_bank
        
        for i in range(total_transfers):
            if i < len(to_remove) and i < len(to_add):
                out_player = to_remove[i]
                in_player = to_add[i]
                
                # Calculate cost difference
                cost_difference = in_player['price'] - out_player['price']
                
                # Check if we can afford this transfer
                if cost_difference > available_bank:
                    continue  # Skip if we can't afford
                
                # Determine if this is a free transfer or a hit
                is_free_transfer = i < free_transfers
                transfer_cost = 0 if is_free_transfer else -4
                
                # Calculate value gain
                value_gain = in_player['comprehensive_value'] - out_player['comprehensive_value']
                
                # Calculate if the transfer is worth it
                # A hit costs 4 points, so we need at least 4 points of value gain to be worth it
                is_worth_hit = value_gain >= 0.4 if not is_free_transfer else True
                
                # Calculate expected points gain (rough estimate)
                expected_points_gain = (in_player['points_per_game'] - out_player['points_per_game']) * 5  # 5 gameweeks
                
                # Net benefit considering the hit cost
                net_benefit = expected_points_gain + transfer_cost
                
                transfer_suggestions.append({
                    "transfer_out": {
                        "name": out_player['name'],
                        "team": out_player['team'],
                        "position": out_player['position'],
                        "price": out_player['price'],
                        "value": out_player['comprehensive_value'],
                        "points_per_game": out_player['points_per_game']
                    },
                    "transfer_in": {
                        "name": in_player['name'],
                        "team": in_player['team'],
                        "position": in_player['position'],
                        "price": in_player['price'],
                        "value": in_player['comprehensive_value'],
                        "points_per_game": in_player['points_per_game']
                    },
                    "cost_difference": round(cost_difference, 1),
                    "transfer_cost": transfer_cost,
                    "value_gain": round(value_gain, 2),
                    "expected_points_gain": round(expected_points_gain, 1),
                    "net_benefit": round(net_benefit, 1),
                    "is_worth_hit": is_worth_hit,
                    "is_free_transfer": is_free_transfer,
                    "priority": i + 1
                })
                
                # Update available bank
                available_bank -= cost_difference
        
        # Sort by net benefit
        transfer_suggestions.sort(key=lambda x: x['net_benefit'], reverse=True)
        
        # Calculate summary
        total_cost = sum(t["transfer_cost"] for t in transfer_suggestions)
        total_value_gain = sum(t["value_gain"] for t in transfer_suggestions)
        total_expected_gain = sum(t["expected_points_gain"] for t in transfer_suggestions)
        
        return {
            "transfers": transfer_suggestions,
            "summary": {
                "total_transfers": len(transfer_suggestions),
                "free_transfers_used": min(free_transfers, len(transfer_suggestions)),
                "hits_taken": max(0, len(transfer_suggestions) - free_transfers),
                "total_cost": total_cost,
                "total_value_gain": round(total_value_gain, 2),
                "total_expected_gain": round(total_expected_gain, 1),
                "net_benefit": round(total_expected_gain + total_cost, 1),
                "recommendation": self._get_transfer_recommendation(transfer_suggestions, total_cost, total_expected_gain)
            }
        }
    
    def _get_transfer_recommendation(self, transfers: List[Dict], total_cost: int, total_expected_gain: float) -> str:
        """Get a recommendation based on transfer analysis"""
        if not transfers:
            return "No beneficial transfers found."
        
        net_benefit = total_expected_gain + total_cost
        
        if net_benefit > 10:
            return "Strong recommendation: These transfers should significantly improve your team."
        elif net_benefit > 5:
            return "Good recommendation: These transfers should provide a decent improvement."
        elif net_benefit > 0:
            return "Moderate recommendation: Small improvement expected."
        elif net_benefit > -5:
            return "Consider carefully: Marginal benefit, may not be worth the cost."
        else:
            return "Not recommended: The transfer costs outweigh the expected benefits."