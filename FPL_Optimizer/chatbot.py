from typing import Dict, List
import re

class FPLChatbot:
    """Chatbot for answering FPL-related questions"""
    
    def __init__(self, optimizer, players_df, data_manager):
        self.optimizer = optimizer
        self.players_df = players_df
        self.data_manager = data_manager
        
    def process_message(self, message: str, user_context: Dict = None) -> Dict:
        """Process user message and return response"""
        message = message.lower().strip()
        
        # Define question patterns and handlers
        handlers = [
            (r'(transfer|who should i transfer|transfer in|bring in)', self.handle_transfer_question),
            (r'(best 11|starting 11|best team|optimal lineup)', self.handle_best_11_question),
            (r'(captain|who should i captain|captaincy)', self.handle_captain_question),
            (r'(fixture|upcoming fixture|next game)', self.handle_fixture_question),
            (r'(player.*stat|how is|tell me about)', self.handle_player_stats_question),
            (r'(differential|unique player|template)', self.handle_differential_question),
            (r'(budget|money|fund)', self.handle_budget_question),
            (r'(injury|injured|doubtful)', self.handle_injury_question),
        ]
        
        # Check which handler matches
        for pattern, handler in handlers:
            if re.search(pattern, message):
                return handler(message, user_context)
        
        # Default response
        return {
            'response': "I can help you with:\n" +
                       "• Transfer suggestions\n" +
                       "• Best starting 11\n" +
                       "• Captain recommendations\n" +
                       "• Player statistics\n" +
                       "• Fixture analysis\n" +
                       "• Injury updates\n\n" +
                       "Try asking something like: 'Who should I transfer in this week?'",
            'type': 'help'
        }
    
    def handle_transfer_question(self, message: str, context: Dict) -> Dict:
        """Handle transfer-related questions"""
        if not self.optimizer:
            return {'response': 'Please initialize the optimizer first.', 'type': 'error'}
        
        # Get top transfer suggestions
        result = self.optimizer.optimize_team(strategy='balanced')
        
        if 'error' in result:
            return {'response': f"Error: {result['error']}", 'type': 'error'}
        
        # Get top 3 players by value
        top_players = sorted(
            result.get('all_players', []),
            key=lambda x: x.get('comprehensive_value', 0),
            reverse=True
        )[:3]
        
        response = "📈 **Top Transfer Recommendations:**\n\n"
        for i, player in enumerate(top_players, 1):
            response += f"{i}. **{player['name']}** ({player['position']})\n"
            response += f"   • Team: {player['team']}\n"
            response += f"   • Price: £{player['price']}M\n"
            response += f"   • Form: {player.get('form', 0):.1f}\n"
            response += f"   • Value Score: {player.get('comprehensive_value', 0):.2f}\n\n"
        
        return {'response': response, 'type': 'transfer', 'data': top_players}
    
    def handle_best_11_question(self, message: str, context: Dict) -> Dict:
        """Handle best starting 11 questions"""
        if not self.optimizer:
            return {'response': 'Please initialize the optimizer first.', 'type': 'error'}
        
        result = self.optimizer.optimize_team(strategy='balanced')
        
        if 'error' in result:
            return {'response': f"Error: {result['error']}", 'type': 'error'}
        
        starting_11 = result.get('starting_11', [])
        
        response = "⭐ **Your Optimal Starting 11:**\n\n"
        
        # Group by position
        by_position = {}
        for player in starting_11:
            pos = player['position']
            if pos not in by_position:
                by_position[pos] = []
            by_position[pos].append(player)
        
        for position in ['Goalkeeper', 'Defender', 'Midfielder', 'Forward']:
            if position in by_position:
                response += f"**{position}s:**\n"
                for player in by_position[position]:
                    response += f"• {player['name']} ({player['team']}) - £{player['price']}M\n"
                response += "\n"
        
        response += f"**Total Cost:** £{result.get('total_cost', 0):.1f}M\n"
        response += f"**Expected Score:** {result.get('total_score', 0):.2f}"
        
        return {'response': response, 'type': 'starting_11', 'data': starting_11}
    
    def handle_captain_question(self, message: str, context: Dict) -> Dict:
        """Handle captain recommendation questions"""
        if not self.optimizer:
            return {'response': 'Please initialize the optimizer first.', 'type': 'error'}
        
        result = self.optimizer.optimize_team(strategy='balanced')
        captaincy = result.get('captaincy', {})
        
        response = "🔰 **Captain Recommendations:**\n\n"
        response += f"**Top Choice:** {captaincy.get('captain', 'N/A')}\n"
        response += f"**Vice Captain:** {captaincy.get('vice_captain', 'N/A')}\n\n"
        
        if 'alternatives' in captaincy:
            response += "**Alternatives:**\n"
            for alt in captaincy['alternatives'][:3]:
                response += f"• {alt['name']} - Score: {alt.get('captain_score', 0):.2f}\n"
        
        return {'response': response, 'type': 'captain', 'data': captaincy}
    
    def handle_fixture_question(self, message: str, context: Dict) -> Dict:
        """Handle fixture-related questions"""
        # Extract team name if mentioned
        team_name = self._extract_team_name(message)
        
        if team_name and team_name in self.data_manager.fixture_difficulty:
            fixtures = self.data_manager.fixture_difficulty[team_name]
            response = f"📅 **Upcoming Fixtures for {team_name}:**\n\n"
            response += f"Average Difficulty: {fixtures.get('average_difficulty', 'N/A'):.1f}/5\n"
        else:
            response = "📅 **Fixture Analysis:**\n\n"
            response += "Please specify a team name for detailed fixture information."
        
        return {'response': response, 'type': 'fixture'}
    
    def handle_player_stats_question(self, message: str, context: Dict) -> Dict:
        """Handle player statistics questions"""
        player_name = self._extract_player_name(message)
        
        if not player_name:
            return {'response': 'Please specify a player name.', 'type': 'error'}
        
        # Search for player
        player_matches = self.players_df[
            self.players_df['name'].str.contains(player_name, case=False, na=False)
        ]
        
        if player_matches.empty:
            return {'response': f"Player '{player_name}' not found.", 'type': 'error'}
        
        player = player_matches.iloc[0].to_dict()
        
        response = f"📊 **Stats for {player['name']}:**\n\n"
        response += f"• Position: {player['position']}\n"
        response += f"• Team: {player['team']}\n"
        response += f"• Price: £{player['price']}M\n"
        response += f"• Total Points: {player['total_points']}\n"
        response += f"• Form: {player.get('form', 0):.1f}\n"
        response += f"• xG: {player.get('expected_goals', 0):.2f}\n"
        response += f"• xA: {player.get('expected_assists', 0):.2f}\n"
        response += f"• Value Score: {player.get('comprehensive_value', 0):.2f}\n"
        
        return {'response': response, 'type': 'player_stats', 'data': player}
    
    def handle_differential_question(self, message: str, context: Dict) -> Dict:
        """Handle differential player questions"""
        # Find low-owned high-value players
        differentials = self.players_df[
            (self.players_df['selected_by_percent'] < 10) &
            (self.players_df['minutes'] > 500)
        ].nlargest(5, 'comprehensive_value')
        
        response = "🎯 **Top Differential Picks:**\n\n"
        for _, player in differentials.iterrows():
            response += f"• **{player['name']}** ({player['position']})\n"
            response += f"  Price: £{player['price']}M | Owned: {player['selected_by_percent']:.1f}%\n"
            response += f"  Value: {player.get('comprehensive_value', 0):.2f}\n\n"
        
        return {'response': response, 'type': 'differential', 'data': differentials.to_dict('records')}
    
    def handle_budget_question(self, message: str, context: Dict) -> Dict:
        """Handle budget-related questions"""
        # Extract budget if mentioned
        budget_match = re.search(r'(\d+\.?\d*)', message)
        budget = float(budget_match.group(1)) if budget_match else 100.0
        
        response = f"💰 **Players within £{budget}M budget:**\n\n"
        
        affordable = self.players_df[
            (self.players_df['price'] <= budget) &
            (self.players_df['minutes'] > 500)
        ].nlargest(5, 'comprehensive_value')
        
        for _, player in affordable.iterrows():
            response += f"• {player['name']} - £{player['price']}M (Value: {player.get('comprehensive_value', 0):.2f})\n"
        
        return {'response': response, 'type': 'budget'}
    
    def handle_injury_question(self, message: str, context: Dict) -> Dict:
        """Handle injury-related questions"""
        injured = self.players_df[
            (self.players_df['chance_of_playing_this_round'].notna()) &
            (self.players_df['chance_of_playing_this_round'] < 100)
        ][['name', 'team', 'chance_of_playing_this_round', 'news']]
        
        if injured.empty:
            return {'response': 'No injury concerns at the moment! ✅', 'type': 'injury'}
        
        response = "🏥 **Injury Updates:**\n\n"
        for _, player in injured.head(10).iterrows():
            response += f"• **{player['name']}** ({player['team']})\n"
            response += f"  Chance of playing: {player['chance_of_playing_this_round']}%\n"
            if player['news']:
                response += f"  News: {player['news']}\n"
            response += "\n"
        
        return {'response': response, 'type': 'injury', 'data': injured.to_dict('records')}
    
    def _extract_player_name(self, message: str) -> str:
        """Extract player name from message"""
        # Simple extraction - looks for capitalized words
        words = message.split()
        for i, word in enumerate(words):
            if word[0].isupper() and i + 1 < len(words) and words[i + 1][0].isupper():
                return f"{word} {words[i + 1]}"
        return ""
    
    def _extract_team_name(self, message: str) -> str:
        """Extract team name from message"""
        # List of common team names
        teams = ['Arsenal', 'Liverpool', 'Manchester City', 'Chelsea', 'Tottenham', 
                'Manchester United', 'Newcastle', 'Brighton', 'Aston Villa']
        
        for team in teams:
            if team.lower() in message:
                return team
        return ""