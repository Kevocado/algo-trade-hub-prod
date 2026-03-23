from dataclasses import dataclass

@dataclass
class EnhancedPlayerData:
    """Enhanced data structure with all FPL metrics including new defensive stats"""
    # Basic info
    id: int
    name: str
    team: str
    team_id: int
    position: str
    price: float
    
    # Performance metrics
    total_points: int
    form: float
    minutes: int
    points_per_game: float
    selected_by_percent: float
    
    # Attacking metrics
    goals_scored: int
    assists: int
    expected_goals: float
    expected_assists: float
    expected_goal_involvements: float
    
    # Defensive metrics (enhanced for 24/25)
    clean_sheets: int
    goals_conceded: int
    saves: int
    penalties_saved: int
    yellow_cards: int
    red_cards: int
    own_goals: int
    
    # Advanced metrics
    bonus: int
    bps: int  # Bonus Points System score
    influence: float
    creativity: float
    threat: float
    ict_index: float
    
    # Availability
    chance_of_playing_this_round: int = None
    chance_of_playing_next_round: int = None
    news: str = ""

    # New defensive contributions (24/25 season)
    tackles: int = 0
    interceptions: int = 0
    clearances: int = 0
    blocks: int = 0
    aerial_duels_won: int = 0
    recoveries: int = 0
    duels_won: int = 0

    # Transfer metrics
    transfers_in: int = 0
    transfers_out: int = 0
    transfers_in_event: int = 0
    transfers_out_event: int = 0