"""
NCAA March Madness Engine - Keyless API Integration
"""
import requests
import time
from datetime import datetime, timezone, timedelta

NCAA_BASE_URL = "https://ncaa-api.vercel.app"

class NCAAEngine:
    def __init__(self):
        pass
        
    def fetch_upcoming_march_madness(self) -> list:
        upcoming = []
        now = datetime.now(timezone.utc)
        
        for i in range(4):
            target_date = now + timedelta(days=i)
            # format YYYY/MM/DD
            date_str = target_date.strftime("%Y/%m/%d")
            
            url = f"{NCAA_BASE_URL}/scoreboard/basketball-men/d1/{date_str}"
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    games = data.get("games", [])
                    for game in games:
                        try:
                            # INSTANTIATE NEW DICTIONARY PER GAME
                            game_obj = game.get("game", {})
                            game_id = game_obj.get("gameID", "")
                            if not game_id: continue
                            
                            away_team = game_obj.get("away", {})
                            home_team = game_obj.get("home", {})
                            
                            away_name = away_team.get("names", {}).get("short", away_team.get("nameSEO", "Away"))
                            home_name = home_team.get("names", {}).get("short", home_team.get("nameSEO", "Home"))
                            
                            away_slug = away_team.get("nameSEO", "")
                            home_slug = home_team.get("nameSEO", "")
                            
                            game_time = game_obj.get("startTime", "")
                            
                            away_logo = f"{NCAA_BASE_URL}/logo/{away_slug}.svg" if away_slug else ""
                            home_logo = f"{NCAA_BASE_URL}/logo/{home_slug}.svg" if home_slug else ""
                            
                            opportunity = {
                                "engine": "NCAA",
                                "asset": f"{away_name} vs {home_name}",
                                "market_title": f"NCAA Basketball: {away_name} vs {home_name}",
                                "market_id": f"ncaa_bb_{game_id}",
                                "action": "STAY", # Schedule only for now
                                "edge": 0.0,
                                "confidence": 50,
                                "reasoning": f"March Madness Matchup: {away_name} vs {home_name} scheduled for {game_time}.",
                                "data_source": "NCAA Official API",
                                "ui_reasoning": False,
                                "raw_payload": {
                                    "away_logo": away_logo,
                                    "home_logo": home_logo,
                                    "date": game_time
                                }
                            }
                            upcoming.append(opportunity)
                        except Exception as game_err:
                            print(f"    ⚠️ Skipping individual NCAA game: {game_err}")
                            continue
                time.sleep(0.5)
            except Exception as e:
                print(f"  ⚠️ NCAA API Error on {date_str}: {e}")
                
        return upcoming
