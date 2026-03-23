import os
import requests
import json
from datetime import datetime

class DiscordNotifier:
    """
    Sends Kalshi Edge alerts to a Discord Webhook.
    Format: Rich Embed with green/red coloring based on edge.
    """
    def __init__(self):
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    def is_enabled(self):
        return bool(self.webhook_url)

    def send_alert(self, opportunities, min_edge=30.0):
        """
        Filters opportunities for high edge and sends a Discord alert.
        Returns the number of alerts sent.
        """
        if not self.is_enabled() or not opportunities:
            return 0

        # Filter for high-conviction trades
        high_edge_opps = [o for o in opportunities if float(o.get('Edge', 0)) >= min_edge]
        
        if not high_edge_opps:
            return 0

        # Sort highest edge first
        high_edge_opps.sort(key=lambda x: float(x.get('Edge', 0)), reverse=True)
        
        # Discord limit is 10 embeds per message, we'll cap at 5 to not spam
        opps_to_send = high_edge_opps[:5]
        
        embeds = []
        for opp in opps_to_send:
            edge = float(opp.get('edge', 0))
            action = opp.get('action', 'UNKNOWN')
            
            # Green UI for high edge
            color = 0x3FB950
            
            # Build fields
            fields = [
                {"name": "Action", "value": f"**{action}**", "inline": True},
                {"name": "Edge", "value": f"**+{edge:.1f}%**", "inline": True},
                {"name": "Current Price", "value": f"{opp.get('market_price', 0)}¢", "inline": True},
                {"name": "Reasoning", "value": opp.get('reasoning', 'No reasoning provided')[:1024], "inline": False}
            ]
            
            factors = opp.get('factors', [])
            if factors:
                fields.append({
                    "name": "Factors",
                    "value": "\n".join([f"• {f}" for f in factors])[:1024],
                    "inline": False
                })

            embeds.append({
                "title": f"🚨 {opp.get('engine', 'Scanner')} Edge: {opp.get('market_title', 'Kalshi Market')}",
                "url": opp.get('kalshi_url', 'https://kalshi.com'),
                "color": color,
                "fields": fields,
                "footer": {"text": f"Asset: {opp.get('asset', 'Unknown')} | Date: {opp.get('market_date', 'N/A')}"}
            })

        payload = {
            "content": f"🤖 **Kalshi Edge Scanner** found {len(high_edge_opps)} high-conviction trades (>{min_edge}% edge)!",
            "embeds": embeds
        }

        try:
            response = requests.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            response.raise_for_status()
            print(f"    🔔 Sent Discord alert for {len(opps_to_send)} opportunities.")
            return len(opps_to_send)
        except Exception as e:
            print(f"    ⚠️ Failed to send Discord alert: {e}")
            return 0
