import google.generativeai as genai
import pandas as pd
import os
from typing import Dict, List, Optional

class FPLAIContextManager:
    """
    Manages the context construction for the AI Analyst.
    Converts structured FPL data into a token-efficient text summary.
    """
    
    def __init__(self, players_df: pd.DataFrame, user_team_data: Dict):
        self.players_df = players_df
        self.user_team_data = user_team_data
        
    def get_system_prompt(self) -> str:
        """Generates the system prompt defining the AI's persona and context."""
        
        # 1. User Team Context
        team_summary = "User's Current Team:\n"
        
        # Check for processed 'current_team' list first (from Controller)
        if self.user_team_data and 'current_team' in self.user_team_data:
            current_team = self.user_team_data['current_team']
            for player in current_team:
                name = player.get('name', 'Unknown')
                pos = player.get('position', 'Unknown')
                cost = player.get('price', 0)
                form = player.get('form', 0)
                team_summary += f"- {name} ({pos}, £{cost}m, Form: {form})\n"
                
        # Fallback to raw picks if available
        elif self.user_team_data and 'picks' in self.user_team_data:
            picks = self.user_team_data['picks'].get('picks', [])
            for pick in picks:
                # Find player name in df
                player_id = pick['element']
                player_row = self.players_df[self.players_df['id'] == player_id]
                if not player_row.empty:
                    name = player_row.iloc[0]['name']
                    pos = player_row.iloc[0]['position']
                    cost = player_row.iloc[0]['price']
                    form = player_row.iloc[0]['form']
                    team_summary += f"- {name} ({pos}, £{cost}m, Form: {form})\n"
        else:
            team_summary += "No team data loaded.\n"
            
        # 2. Market Context (Top Players by Form)
        market_summary = "\nTop Players by Form:\n"
        top_form = self.players_df.nlargest(10, 'form')[['name', 'team', 'position', 'price', 'form', 'xgi_per_game']]
        for _, row in top_form.iterrows():
            market_summary += f"- {row['name']} ({row['team']}, {row['position']}): £{row['price']}m, Form: {row['form']}, xGI/90: {row['xgi_per_game']:.2f}\n"

        # 3. System Instruction
        system_prompt = f"""
You are an expert FPL (Fantasy Premier League) Assistant. 
Your goal is to help the user optimize their team using data-driven insights.

CONTEXT:
{team_summary}

{market_summary}

INSTRUCTIONS:
- Be concise and direct.
- Use bolding for player names and key metrics.
- Always justify your suggestions with data (Form, xG, Fixtures).
- If asked about a player not in the context, say you don't have their live stats but can give general advice.
- You are talking to a dedicated FPL manager.
"""
        return system_prompt

def get_ai_response(messages: List[Dict], api_key: str, context_manager: FPLAIContextManager) -> str:
    """
    Sends the conversation history to Google Gemini and returns the response.
    Tries multiple model versions to ensure compatibility.
    """
    if not api_key:
        return "Please provide a valid Google Gemini API Key in the .env file (FPL_API_KEY) to use the AI Analyst."
        
    try:
        genai.configure(api_key=api_key)
        
        # List of models to try in order of preference
        # User explicitly requested 2.5 versions
        candidate_models = [
            'gemini-2.5-flash',
            'gemini-2.5-pro'
        ]
        
        # Construct full prompt with system context
        system_prompt = context_manager.get_system_prompt()
        full_prompt = system_prompt + "\n\nConversation History:\n"
        for msg in messages:
            role = "User" if msg["role"] == "user" else "AI"
            full_prompt += f"{role}: {msg['content']}\n"
        full_prompt += "\nAI:"
        
        last_error = None
        
        for model_name in candidate_models:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(full_prompt)
                return response.text
            except Exception as e:
                last_error = e
                continue
                
        # If we get here, all models failed
        return f"Error communicating with AI. Tried models {candidate_models}. Last error: {str(last_error)}"
        
    except Exception as e:
        return f"Error initializing AI: {str(e)}"
