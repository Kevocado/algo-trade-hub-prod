import requests
import pandas as pd
import numpy as np
from collections import defaultdict
from typing import Dict, List
from models import EnhancedPlayerData
from functools import lru_cache
import time 

class AdvancedFPLDataManager:
    """Enhanced data manager with advanced metrics and fixture analysis"""
    
    def __init__(self):
        self.base_url = "https://fantasy.premierleague.com/api"
        self.session = requests.Session()
        self.current_gameweek = 1
        self.teams_data = {}
        self.fixtures_data = []
        self.fixture_difficulty = {}
        
    def fetch_bootstrap_data(self) -> Dict:
        """Fetch main FPL data with enhanced error handling"""
        try:
            response = self.session.get(f"{self.base_url}/bootstrap-static/", timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Store team data for fixture analysis
            self.teams_data = {team['id']: team for team in data.get('teams', [])}
            
            # Get current gameweek
            events = data.get('events', [])
            for event in events:
                if event.get('is_current', False):
                    self.current_gameweek = event['id']
                    break
                elif event.get('is_next', False) and self.current_gameweek == 1:
                    self.current_gameweek = event['id']
            
            return data
        except Exception as e:
            print(f"Error fetching bootstrap data: {e}")
            return {}
    
    def fetch_fixtures(self) -> List[Dict]:
        """Fetch fixture data for difficulty analysis"""
        try:
            response = self.session.get(f"{self.base_url}/fixtures/")
            response.raise_for_status()
            fixtures = response.json()
            self.fixtures_data = fixtures
            self.calculate_fixture_difficulty()
            return fixtures
        except Exception as e:
            print(f"Error fetching fixtures: {e}")
            return []
    
    def calculate_team_form(self) -> Dict:
        """Calculate team form based on last 5 matches (Attack & Defense)"""
        if not self.fixtures_data:
            return {}
            
        # Filter finished fixtures
        finished_fixtures = [f for f in self.fixtures_data if f.get('finished')]
        # Sort by event (most recent first)
        finished_fixtures.sort(key=lambda x: x['event'] if x['event'] else 0, reverse=True)
        
        team_matches = defaultdict(list)
        
        # Get last 5 matches for each team
        for f in finished_fixtures:
            h = f['team_h']
            a = f['team_a']
            h_score = f['team_h_score']
            a_score = f['team_a_score']
            
            if len(team_matches[h]) < 5:
                team_matches[h].append({'scored': h_score, 'conceded': a_score})
            if len(team_matches[a]) < 5:
                team_matches[a].append({'scored': a_score, 'conceded': h_score})
        
        # Calculate strength metrics
        team_form = {}
        for team_id, matches in team_matches.items():
            if not matches:
                continue
            
            # Average goals scored (Attack Strength)
            avg_scored = sum(m['scored'] for m in matches) / len(matches)
            # Average goals conceded (Defensive Weakness)
            avg_conceded = sum(m['conceded'] for m in matches) / len(matches)
            
            team_form[team_id] = {
                'attack_strength': avg_scored,
                'defensive_weakness': avg_conceded
            }
            
        return team_form

    def calculate_fixture_difficulty(self):
        """Calculate dynamic fixture difficulty ratings for next 5 gameweeks"""
        if not self.fixtures_data or not self.teams_data:
            return
        
        # Get dynamic team form
        team_form = self.calculate_team_form()
        
        # Calculate League Averages for normalization
        if team_form:
            avg_attack = np.mean([t['attack_strength'] for t in team_form.values()])
            avg_defense = np.mean([t['defensive_weakness'] for t in team_form.values()])
        else:
            avg_attack = 1.5
            avg_defense = 1.5

        # Initialize difficulty tracker
        team_difficulties = defaultdict(lambda: defaultdict(list))
        
        current_gw = self.current_gameweek
        
        for fixture in self.fixtures_data:
            if not fixture.get('finished', False) and fixture.get('event'):
                gw = fixture['event']
                if current_gw <= gw <= current_gw + 4:  # Next 5 gameweeks
                    home_team = fixture['team_h']
                    away_team = fixture['team_a']
                    
                    # Dynamic FDR Calculation
                    # Difficulty for Home Team = Away Team's Strength
                    # Difficulty for Away Team = Home Team's Strength
                    
                    if away_team in team_form:
                        # Opponent Strength = (Attack + (Inverse of Defense Weakness? No, Low Conceded is Strong))
                        # Actually, if I am Home, my difficulty depends on:
                        # 1. Opponent Attack (Threat to my CS)
                        # 2. Opponent Defense (Threat to my Goals)
                        
                        # Let's simplify: Strength = Attack + (3 - Conceded)
                        # Higher is Stronger Team (Harder Fixture)
                        opp_attack = team_form[away_team]['attack_strength']
                        opp_defense_quality = 3.0 - team_form[away_team]['defensive_weakness'] # Assuming max 3 goals conceded avg
                        opp_strength = (opp_attack + opp_defense_quality) / 2
                        
                        # Normalize to 1-5 scale roughly
                        # Avg strength ~ (1.5 + 1.5)/2 = 1.5
                        # Max strength ~ (3.0 + 3.0)/2 = 3.0
                        # Min strength ~ (0.5 + 0.0)/2 = 0.25
                        
                        # Map 0.5 -> 3.0 to 2 -> 5
                        home_difficulty = 2 + (opp_strength / 3.0) * 3
                        home_difficulty = min(5, max(2, home_difficulty))
                    else:
                        home_difficulty = fixture.get('team_h_difficulty', 3)

                    if home_team in team_form:
                        opp_attack = team_form[home_team]['attack_strength']
                        opp_defense_quality = 3.0 - team_form[home_team]['defensive_weakness']
                        opp_strength = (opp_attack + opp_defense_quality) / 2
                        
                        away_difficulty = 2 + (opp_strength / 3.0) * 3
                        away_difficulty = min(5, max(2, away_difficulty))
                    else:
                        away_difficulty = fixture.get('team_a_difficulty', 3)
                    
                    team_difficulties[home_team][gw].append(home_difficulty)
                    team_difficulties[away_team][gw].append(away_difficulty)
        
        # Calculate average difficulties
        for team_id in team_difficulties:
            team_name = self.teams_data.get(team_id, {}).get('name', 'Unknown')
            self.fixture_difficulty[team_id] = {
                'team_name': team_name,
                'gameweeks': {},
                'average_difficulty': 0
            }
            
            total_difficulty = 0
            total_games = 0
            
            for gw in range(current_gw, current_gw + 5):
                if gw in team_difficulties[team_id]:
                    gw_difficulty = sum(team_difficulties[team_id][gw]) / len(team_difficulties[team_id][gw])
                    self.fixture_difficulty[team_id]['gameweeks'][gw] = gw_difficulty
                    total_difficulty += gw_difficulty
                    total_games += 1
                else:
                    self.fixture_difficulty[team_id]['gameweeks'][gw] = None
            
            if total_games > 0:
                self.fixture_difficulty[team_id]['average_difficulty'] = total_difficulty / total_games
    
    def fetch_user_team(self, team_id: str) -> Dict:
        """Fetch user's current FPL team with enhanced data"""
        try:
            # Get current picks
            picks_url = f"{self.base_url}/entry/{team_id}/event/{self.current_gameweek}/picks/"
            response = self.session.get(picks_url)
            response.raise_for_status()
            picks_data = response.json()
            
            # Get team info
            team_url = f"{self.base_url}/entry/{team_id}/"
            response = self.session.get(team_url)
            response.raise_for_status()
            team_data = response.json()
            
            # Get transfer history
            transfers_url = f"{self.base_url}/entry/{team_id}/transfers/"
            try:
                response = self.session.get(transfers_url)
                transfers_data = response.json() if response.status_code == 200 else []
            except:
                transfers_data = []
            

            return {
                'picks': picks_data,
                'team_info': team_data,
                'transfers': transfers_data,
                'gameweek': self.current_gameweek
            }
        except Exception as e:
            print(f"Error fetching user team: {e}")
            return {}
    
    def process_enhanced_player_data(self, bootstrap_data: Dict) -> pd.DataFrame:
        """Process player data with all enhanced metrics"""
        players = bootstrap_data.get('elements', [])
        teams = {team['id']: team['name'] for team in bootstrap_data.get('teams', [])}
        positions = {pos['id']: pos['singular_name'] for pos in bootstrap_data.get('element_types', [])}
        
        processed_players = []
        
        for player in players:
            if player.get('status') != 'a':
                continue
            
            # Calculate expected goal involvements
            xg = float(player.get('expected_goals', 0) or 0)
            xa = float(player.get('expected_assists', 0) or 0)
            xgi = xg + xa
            
            player_data = EnhancedPlayerData(
                # Basic info
                id=player['id'],
                name=f"{player['first_name']} {player['second_name']}",
                team=teams.get(player['team'], 'Unknown'),
                team_id=player['team'],
                position=positions.get(player['element_type'], 'Unknown'),
                price=player['now_cost'] / 10.0,
                
                # Performance
                total_points=player['total_points'],
                form=float(player.get('form', 0) or 0),
                minutes=player['minutes'],
                points_per_game=float(player.get('points_per_game', 0) or 0),
                selected_by_percent=float(player.get('selected_by_percent', 0)),
                
                # Attacking
                goals_scored=player['goals_scored'],
                assists=player['assists'],
                expected_goals=xg,
                expected_assists=xa,
                expected_goal_involvements=xgi,
                
                # Defensive
                clean_sheets=player['clean_sheets'],
                goals_conceded=player['goals_conceded'],
                saves=player['saves'],
                penalties_saved=player['penalties_saved'],
                yellow_cards=player['yellow_cards'],
                red_cards=player['red_cards'],
                own_goals=player['own_goals'],
                
                # Enhanced defensive metrics (some may not be in API yet)
                tackles=player.get('tackles', 0) or 0,
                interceptions=player.get('interceptions', 0) or 0,
                clearances=player.get('clearances', 0) or 0,
                blocks=player.get('blocks', 0) or 0,
                aerial_duels_won=player.get('aerial_duels_won', 0) or 0,
                recoveries=player.get('recoveries', 0) or 0,
                duels_won=player.get('duels_won', 0) or 0,
                
                # Advanced
                bonus=player['bonus'],
                bps=player['bps'],
                influence=float(player.get('influence', 0) or 0),
                creativity=float(player.get('creativity', 0) or 0),
                threat=float(player.get('threat', 0) or 0),
                ict_index=float(player.get('ict_index', 0) or 0),
                
                # Availability
                chance_of_playing_this_round=player.get('chance_of_playing_this_round'),
                chance_of_playing_next_round=player.get('chance_of_playing_next_round'),
                news=player.get('news', ''),
                
                # Transfers
                transfers_in=player.get('transfers_in', 0),
                transfers_out=player.get('transfers_out', 0),
                transfers_in_event=player.get('transfers_in_event', 0),
                transfers_out_event=player.get('transfers_out_event', 0)
            )
            processed_players.append(player_data)
        
        df = pd.DataFrame([vars(p) for p in processed_players])
        return self.calculate_comprehensive_metrics(df)
    
    def calculate_defense_score(self, row):
        """Calculate defensive score based on FPL 2024/25 rules"""
        if row['position'] == 'Goalkeeper':
            # GK: Clean sheets (4pts), Saves (1pt per 3), Penalties saved (5pts)
            clean_sheet_points = (row['clean_sheets'] / max(row['minutes'] / 90, 1)) * 4
            save_points = (row['saves'] / max(row['minutes'] / 90, 1)) / 3  # 1pt per 3 saves
            penalty_points = row['penalties_saved'] * 5
            return clean_sheet_points + save_points + penalty_points
            
        elif row['position'] == 'Defender':
            # DEF: Clean sheets (4pts), Goals (6pts), Assists (3pts), Tackles/Interceptions (1pt each)
            clean_sheet_points = (row['clean_sheets'] / max(row['minutes'] / 90, 1)) * 4
            goal_points = row['goals_scored'] * 6
            assist_points = row['assists'] * 3
            defensive_action_points = (row['tackles'] + row['interceptions']) / max(row['minutes'] / 90, 1)
            return clean_sheet_points + goal_points + assist_points + defensive_action_points
            
        elif row['position'] == 'Midfielder':
            # MID: Clean sheets (1pt), Goals (5pts), Assists (3pts), Tackles/Interceptions (1pt each)
            clean_sheet_points = (row['clean_sheets'] / max(row['minutes'] / 90, 1)) * 1
            goal_points = row['goals_scored'] * 5
            assist_points = row['assists'] * 3
            defensive_action_points = (row['tackles'] + row['interceptions']) / max(row['minutes'] / 90, 1)
            return clean_sheet_points + goal_points + assist_points + defensive_action_points
            
        elif row['position'] == 'Forward':
            # FWD: Goals (4pts), Assists (3pts), No clean sheet points
            goal_points = row['goals_scored'] * 4
            assist_points = row['assists'] * 3
            return goal_points + assist_points
            
        else:
            return 0 
    
    def calculate_comprehensive_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate comprehensive performance metrics"""
        df = df.copy()
        
        # Basic value metrics
        df['points_per_million'] = np.where(df['price'] > 0, df['total_points'] / df['price'], 0)
        df['form_per_million'] = np.where(df['price'] > 0, df['form'] / df['price'], 0)
        
        # Expected metrics
        df['xg_per_game'] = np.where(df['minutes'] > 0, (df['expected_goals'] / (df['minutes'] / 90)), 0)
        df['xa_per_game'] = np.where(df['minutes'] > 0, (df['expected_assists'] / (df['minutes'] / 90)), 0)
        df['xgi_per_game'] = df['xg_per_game'] + df['xa_per_game']
        
        # Performance vs expectation
        df['goals_vs_xg'] = df['goals_scored'] - df['expected_goals']
        df['assists_vs_xa'] = df['assists'] - df['expected_assists']
        df['over_performance'] = df['goals_vs_xg'] + df['assists_vs_xa']
        
        # Defensive metrics per game
        df['tackles_per_game'] = np.where(df['minutes'] > 0, (df['tackles'] / (df['minutes'] / 90)), 0)
        df['interceptions_per_game'] = np.where(df['minutes'] > 0, (df['interceptions'] / (df['minutes'] / 90)), 0)
        df['clearances_per_game'] = np.where(df['minutes'] > 0, (df['clearances'] / (df['minutes'] / 90)), 0)
        
        # Comprehensive defensive score
        df['defensive_score'] = df.apply(self.calculate_defense_score,axis=1)
        
        # Fixture difficulty adjustment
        for idx, row in df.iterrows():
            team_id = row['team_id']
            if team_id in self.fixture_difficulty:
                df.at[idx, 'fixture_difficulty_5gw'] = self.fixture_difficulty[team_id]['average_difficulty']
            else:
                df.at[idx, 'fixture_difficulty_5gw'] = 3.0  # Neutral
        
        # Fixture-adjusted scores
        df['fixture_adjusted_score'] = df['form'] * (4 - df['fixture_difficulty_5gw']) / 2
        
        # Transfer momentum
        df['transfer_momentum'] = (df['transfers_in_event'] - df['transfers_out_event']) / 1000
        
        # Comprehensive value score based on FPL 2024/25 rules
        df['comprehensive_value'] = (
            df['points_per_million'] * 0.30 +  # Primary metric - actual points per million
            df['form_per_million'] * 0.25 +   # Current form is crucial
            df['xgi_per_game'] * 4 * 0.20 +   # Expected goal involvements (goals worth 4-6pts, assists 3pts)
            df['fixture_adjusted_score'] * 0.15 +  # Fixture difficulty
            df['defensive_score'] * 0.10 +    # Defensive contributions (clean sheets, tackles, etc.)
            (df['ict_index'] / 1000) * 0.05 + # ICT index as tiebreaker
            (df['selected_by_percent'] / 100) * 0.05  # Ownership (template vs differential)
        )
        
        # Position-specific bonuses
        position_bonuses = {
            'Goalkeeper': df['saves'] / 100 + df['penalties_saved'] * 0.1,
            'Defender': df['defensive_score'] + df['clean_sheets'] * 0.1,
            'Midfielder': df['xgi_per_game'] + df['defensive_score'] * 0.5,
            'Forward': df['xg_per_game'] * 2 + df['xa_per_game']
        }
        
        for position, bonus in position_bonuses.items():
            mask = df['position'] == position
            df.loc[mask, 'position_adjusted_value'] = df.loc[mask, 'comprehensive_value'] + bonus
        
        df['position_adjusted_value'] = df.get('position_adjusted_value', df['comprehensive_value'])
        
        # Captain potential score
        df['captain_score'] = (
            df['form'] * 0.3 +
            df['points_per_game'] * 0.3 +
            df['fixture_adjusted_score'] * 0.2 +
            df['xgi_per_game'] * 2 * 0.2
        )
        
        return df