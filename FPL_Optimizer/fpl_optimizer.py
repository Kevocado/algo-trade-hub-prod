import requests
import pandas as pd
import numpy as np
from dataclasses import dataclass
import pulp
from collections import defaultdict
import warnings
import re
warnings.filterwarnings('ignore')

@dataclass
class PlayerData:
    """Data structure for FPL player information"""
    id: int
    name: str
    team: str
    position: str
    price: float
    total_points: int
    form: float
    minutes: int
    selected_by_percent: float
    points_per_game: float
    goals_scored: int
    assists: int
    clean_sheets: int
    goals_conceded: int
    saves: int
    bonus: int
    expected_goals: float
    expected_assists: float
    influence: float
    creativity: float
    threat: float
    ict_index: float

class FPLDataManager:
    """Enhanced data manager with team analysis"""
    
    def __init__(self):
        self.base_url = "https://fantasy.premierleague.com/api"
        self.session = requests.Session()
        self.current_gameweek = 1
        
    def extract_team_id(self, url_or_id):
        """Extract team ID from URL or return ID if already numeric"""
        if url_or_id.isdigit():
            return url_or_id
        
        # Extract from various FPL URL formats
        patterns = [
            r'/entry/(\d+)/',
            r'team/(\d+)/',
            r'entry=(\d+)',
            r'team=(\d+)',
            r'/(\d+)$'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url_or_id)
            if match:
                return match.group(1)
        
        return None
        
    def fetch_bootstrap_data(self):
        """Fetch main FPL data"""
        try:
            print("📊 Fetching FPL data...")
            response = self.session.get(f"{self.base_url}/bootstrap-static/")
            response.raise_for_status()
            data = response.json()
            
            # Get current gameweek
            events = data.get('events', [])
            for event in events:
                if event['is_current']:
                    self.current_gameweek = event['id']
                    break
                    
            print(f"📅 Current Gameweek: {self.current_gameweek}")
            return data
        except requests.RequestException as e:
            print(f"❌ Error fetching data: {e}")
            return None
    
    def fetch_user_team(self, team_id):
        """Fetch user's current FPL team"""
        try:
            print(f"🔍 Analyzing team {team_id}...")
            
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
            
            # Get transfers info
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
        except requests.RequestException as e:
            print(f"❌ Error fetching team data: {e}")
            return None
    
    def process_player_data(self, bootstrap_data):
        """Convert raw player data into structured DataFrame"""
        players = bootstrap_data.get('elements', [])
        teams = {team['id']: team['name'] for team in bootstrap_data.get('teams', [])}
        positions = {pos['id']: pos['singular_name'] for pos in bootstrap_data.get('element_types', [])}
        
        processed_players = []
        
        for player in players:
            if player.get('status') != 'a':  # Skip unavailable players
                continue
                
            player_data = PlayerData(
                id=player['id'],
                name=f"{player['first_name']} {player['second_name']}",
                team=teams.get(player['team'], 'Unknown'),
                position=positions.get(player['element_type'], 'Unknown'),
                price=player['now_cost'] / 10.0,
                total_points=player['total_points'],
                form=float(player['form']) if player['form'] else 0.0,
                minutes=player['minutes'],
                selected_by_percent=float(player['selected_by_percent']),
                points_per_game=float(player['points_per_game']) if player['points_per_game'] else 0.0,
                goals_scored=player['goals_scored'],
                assists=player['assists'],
                clean_sheets=player['clean_sheets'],
                goals_conceded=player['goals_conceded'],
                saves=player['saves'],
                bonus=player['bonus'],
                expected_goals=float(player['expected_goals']) if player['expected_goals'] else 0.0,
                expected_assists=float(player['expected_assists']) if player['expected_assists'] else 0.0,
                influence=float(player['influence']) if player['influence'] else 0.0,
                creativity=float(player['creativity']) if player['creativity'] else 0.0,
                threat=float(player['threat']) if player['threat'] else 0.0,
                ict_index=float(player['ict_index']) if player['ict_index'] else 0.0
            )
            processed_players.append(player_data)
        
        df = pd.DataFrame([vars(p) for p in processed_players])
        return self.calculate_advanced_metrics(df)
    
    def calculate_advanced_metrics(self, df):
        """Calculate additional performance metrics"""
        df = df.copy()
        
        # Points and form per million
        df['points_per_million'] = np.where(df['price'] > 0, df['total_points'] / df['price'], 0)
        df['form_per_million'] = np.where(df['price'] > 0, df['form'] / df['price'], 0)
        
        # Expected points calculation
        df['expected_points'] = (
            df['expected_goals'] * 4 +
            df['expected_assists'] * 3 +
            (df['minutes'] / 90) * 2 +
            df['clean_sheets'] * 4
        )
        
        # Overall value score
        df['value_score'] = (
            df['points_per_million'] * 0.4 +
            df['form_per_million'] * 0.3 +
            (df['selected_by_percent'] / 100) * 0.1 +
            (df['ict_index'] / 1000) * 0.2
        )
        
        return df

class FPLTeamAnalyzer:
    """Analyze current team and suggest transfers"""
    
    def __init__(self, players_df, data_manager):
        self.players_df = players_df
        self.data_manager = data_manager
        self.max_players_per_team = 3
        
    def analyze_current_team(self, team_id):
        """Analyze user's current team"""
        team_data = self.data_manager.fetch_user_team(team_id)
        if not team_data:
            return None
        
        picks = team_data['picks']['picks']
        team_info = team_data['team_info']
        
        # Get player details for current team
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
        
        # Group by position
        team_by_position = defaultdict(list)
        for player in current_team:
            team_by_position[player['position']].append(player)
        
        return {
            'team_info': team_info,
            'current_team': current_team,
            'team_by_position': dict(team_by_position),
            'total_cost': round(total_cost, 1),
            'total_points': total_points,
            'bank': team_data['picks']['entry_history']['bank'] / 10.0,
            'free_transfers': team_data['picks']['entry_history']['event_transfers_cost'] == 0,
            'gameweek': team_data['gameweek']
        }
    
    def suggest_transfers(self, current_team_data, num_transfers=1, min_minutes=500):
        """Suggest best transfers for current team"""
        current_team = current_team_data['current_team']
        bank = current_team_data['bank']
        
        print(f"\n🔄 Finding best {num_transfers} transfer{'s' if num_transfers > 1 else ''}...")
        print(f"💰 Available funds: £{bank}M")
        
        # Group current players by position
        current_by_position = defaultdict(list)
        for player in current_team:
            current_by_position[player['position']].append(player)
        
        transfer_suggestions = []
        
        # For each position, find potential upgrades
        for position in current_by_position:
            current_position_players = current_by_position[position]
            
            # Get all available players in this position (excluding current team)
            current_team_ids = [p['id'] for p in current_team]
            available_players = self.players_df[
                (self.players_df['position'] == position) & 
                (~self.players_df['id'].isin(current_team_ids)) &
                (self.players_df['minutes'] >= min_minutes)
            ].copy()
            
            # For each current player in position, find potential replacements
            for current_player in current_position_players:
                # Calculate available budget for this transfer
                max_price = current_player['price'] + bank
                
                # Find players within budget
                affordable_replacements = available_players[
                    available_players['price'] <= max_price
                ].copy()
                
                if affordable_replacements.empty:
                    continue
                
                # Calculate transfer value (improvement in value_score per cost difference)
                affordable_replacements['cost_diff'] = (
                    affordable_replacements['price'] - current_player['price']
                )
                affordable_replacements['value_improvement'] = (
                    affordable_replacements['value_score'] - current_player['value_score']
                )
                affordable_replacements['transfer_efficiency'] = np.where(
                    affordable_replacements['cost_diff'] != 0,
                    affordable_replacements['value_improvement'] / abs(affordable_replacements['cost_diff']),
                    affordable_replacements['value_improvement'] * 10  # Free transfers get bonus
                )
                
                # Get top suggestions for this player
                top_replacements = affordable_replacements.nlargest(3, 'transfer_efficiency')
                
                for _, replacement in top_replacements.iterrows():
                    if replacement['value_improvement'] > 0:  # Only suggest improvements
                        transfer_suggestions.append({
                            'out_player': current_player,
                            'in_player': replacement.to_dict(),
                            'cost_change': replacement['cost_diff'],
                            'value_improvement': replacement['value_improvement'],
                            'transfer_efficiency': replacement['transfer_efficiency'],
                            'position': position
                        })
        
        # Sort by transfer efficiency
        transfer_suggestions.sort(key=lambda x: x['transfer_efficiency'], reverse=True)
        
        return transfer_suggestions[:10]  # Return top 10 suggestions
    
    def display_team_analysis(self, team_data):
        """Display current team analysis"""
        if not team_data:
            return
        
        print("\n" + "="*80)
        print(f"👤 {team_data['team_info']['player_first_name']} {team_data['team_info']['player_last_name']}'s TEAM ANALYSIS")
        print("="*80)
        
        print(f"\n💰 TEAM SUMMARY")
        print(f"Total Team Value: £{team_data['total_cost']}M")
        print(f"Money in Bank: £{team_data['bank']}M") 
        print(f"Total Points: {team_data['total_points']}")
        print(f"Overall Rank: {team_data['team_info']['summary_overall_rank']:,}")
        print(f"Gameweek Rank: {team_data['team_info']['summary_event_rank']:,}")
        
        # Display team by position
        position_order = ['Goalkeeper', 'Defender', 'Midfielder', 'Forward']
        
        for position in position_order:
            if position in team_data['team_by_position']:
                players = team_data['team_by_position'][position]
                
                print(f"\n🔹 {position.upper()}S ({len(players)})")
                print("-" * 80)
                
                for player in players:
                    captain_marker = " (C)" if player['is_captain'] else " (VC)" if player['is_vice_captain'] else ""
                    print(f"  {player['name']:<25}{captain_marker:<4} {player['team']:<15} "
                          f"£{player['price']:<4}M  {player['total_points']:<3}pts  "
                          f"Form:{player['form']:<4}  Value:{player['value_score']:.2f}")
    
    def display_transfer_suggestions(self, suggestions):
        """Display transfer suggestions"""
        if not suggestions:
            print("\n😔 No beneficial transfers found with current budget")
            return
        
        print("\n" + "="*80)
        print("🔄 TRANSFER SUGGESTIONS")
        print("="*80)
        
        for i, transfer in enumerate(suggestions[:5], 1):  # Show top 5
            out_player = transfer['out_player']
            in_player = transfer['in_player']
            
            print(f"\n#{i} TRANSFER - {transfer['position']}")
            print(f"OUT: {out_player['name']:<25} {out_player['team']:<15} £{out_player['price']}M")
            print(f"IN:  {in_player['name']:<25} {in_player['team']:<15} £{in_player['price']}M")
            print(f"Cost: {'+' if transfer['cost_change'] >= 0 else ''}£{transfer['cost_change']:.1f}M")
            print(f"Value Improvement: +{transfer['value_improvement']:.2f}")
            print(f"Efficiency Score: {transfer['transfer_efficiency']:.2f}")
            
            # Show key stats comparison
            print(f"Stats Comparison:")
            print(f"  Points:     {out_player['total_points']:>3} → {in_player['total_points']:<3} "
                  f"({'+'if in_player['total_points'] > out_player['total_points'] else ''}"
                  f"{in_player['total_points'] - out_player['total_points']})")
            print(f"  Form:       {out_player['form']:>3} → {in_player['form']:<3} "
                  f"({'+'if in_player['form'] > out_player['form'] else ''}"
                  f"{in_player['form'] - out_player['form']:.1f})")
            print("-" * 60)

def get_team_input():
    """Get team ID or URL from user"""
    print("\n🎯 FPL TEAM ANALYZER")
    print("Enter your FPL team details:")
    
    team_input = input("Team ID or FPL URL: ").strip()
    return team_input

def get_transfer_preferences():
    """Get transfer preferences"""
    print("\nTransfer Options:")
    print("1. Single Transfer (recommended)")
    print("2. Multiple Transfers")
    
    choice = input("Choose option (1-2) [1]: ").strip()
    
    if choice == '2':
        num_transfers = input("How many transfers? (2-5) [2]: ").strip()
        num_transfers = int(num_transfers) if num_transfers.isdigit() and int(num_transfers) <= 5 else 2
    else:
        num_transfers = 1
    
    min_minutes = input("Minimum minutes played [500]: ").strip()
    min_minutes = int(min_minutes) if min_minutes.isdigit() else 500
    
    return num_transfers, min_minutes

def main():
    """Main function"""
    print("🚀 Starting FPL Team Analyzer...")
    
    # Initialize data manager
    data_manager = FPLDataManager()
    
    # Fetch and process data
    bootstrap_data = data_manager.fetch_bootstrap_data()
    if not bootstrap_data:
        print("❌ Failed to fetch FPL data. Exiting.")
        return
    
    print("📈 Processing player data...")
    players_df = data_manager.process_player_data(bootstrap_data)
    
    print(f"✅ Loaded {len(players_df)} players")
    
    # Get team input
    team_input = get_team_input()
    team_id = data_manager.extract_team_id(team_input)
    
    if not team_id:
        print("❌ Invalid team ID or URL format")
        return
    
    # Initialize analyzer
    analyzer = FPLTeamAnalyzer(players_df, data_manager)
    
    # Analyze current team
    team_data = analyzer.analyze_current_team(team_id)
    if not team_data:
        print("❌ Could not fetch team data")
        return
    
    # Display team analysis
    analyzer.display_team_analysis(team_data)
    
    # Get transfer preferences and suggest transfers
    num_transfers, min_minutes = get_transfer_preferences()
    suggestions = analyzer.suggest_transfers(team_data, num_transfers, min_minutes)
    analyzer.display_transfer_suggestions(suggestions)
    
    # Option to analyze again
    while True:
        again = input("\n🔄 Analyze different team or settings? (y/n): ").strip().lower()
        if again == 'y':
            team_input = get_team_input()
            team_id = data_manager.extract_team_id(team_input)
            
            if team_id:
                team_data = analyzer.analyze_current_team(team_id)
                if team_data:
                    analyzer.display_team_analysis(team_data)
                    num_transfers, min_minutes = get_transfer_preferences()
                    suggestions = analyzer.suggest_transfers(team_data, num_transfers, min_minutes)
                    analyzer.display_transfer_suggestions(suggestions)
        else:
            break
    
    print("\n👋 Thanks for using FPL Team Analyzer!")

if __name__ == "__main__":
    main()