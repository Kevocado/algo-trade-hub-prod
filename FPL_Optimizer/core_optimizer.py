"""
core_optimizer.py — Framework-agnostic FPL mathematical functions
=================================================================
Wraps the existing AdvancedFPLDataManager and AdvancedFPLOptimizer classes
to provide pure, single-call functions for API servers and scripts.
"""

from typing import Dict, List
import pandas as pd

# We use relative imports or rely on PYTHONPATH=.
from FPL_Optimizer.data_manager import AdvancedFPLDataManager
from FPL_Optimizer.optimizer import AdvancedFPLOptimizer


def fetch_and_process_players() -> pd.DataFrame:
    """
    Fetches the latest FPL bootstrap data, fixtures, and processes
    the comprehensive player metrics. Returns the full players DataFrame.
    """
    manager = AdvancedFPLDataManager()
    
    bootstrap_data = manager.fetch_bootstrap_data()
    if not bootstrap_data:
        raise RuntimeError("Failed to fetch FPL bootstrap data")
        
    manager.fetch_fixtures()  # required for fixture_difficulty
    players_df = manager.process_enhanced_player_data(bootstrap_data)
    
    return players_df


def run_optimization(players_df: pd.DataFrame, strategy: str = 'balanced', **kwargs) -> Dict:
    """
    Runs the PuLP optimization solver to find the optimal 15-man squad.
    """
    optimizer = AdvancedFPLOptimizer(players_df)
    return optimizer.optimize_team(strategy=strategy, **kwargs)


def run_transfer_analysis(current_team: List[Dict], optimal_team: List[Dict], 
                          free_transfers: int = 1, current_bank: float = 0.0) -> Dict:
    """
    Analyzes and suggests the optimal transfers between a user's current team
    and the mathematically optimal team.
    """
    # Create a dummy optimizer just for the helper functions
    # (Since suggest_transfers only needs the dictionaries, we can pass an empty DF)
    optimizer = AdvancedFPLOptimizer(pd.DataFrame())
    return optimizer.suggest_transfers(
        current_team=current_team, 
        optimal_team=optimal_team, 
        free_transfers=free_transfers,
        current_bank=current_bank
    )


def run_team_analysis(players: List[Dict]) -> Dict:
    """
    Analyzes the composition and metric balance of a given 15-man squad.
    """
    optimizer = AdvancedFPLOptimizer(pd.DataFrame())
    return optimizer.analyze_team_composition(players)
