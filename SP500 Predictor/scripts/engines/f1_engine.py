"""
F1 Telemetry Engine — FastF1 + OpenF1 Kalshi Signal Generator

Strategy:
  1. Load qualifying and race sessions from the local f1_cache (offline)
  2. Compute sector-time z-scores and tyre-degradation curves per driver
  3. Compare model-derived podium/fastest-lap probabilities to Kalshi F1 markets
  4. During live race weekends: poll OpenF1 API for real-time lap data updates
  5. Signal if |model_prob - kalshi_price| > 10%

Usage:
  engine = F1Engine()
  signals = engine.get_latest_signals()

Paper trading only. Signals logged to Supabase f1_signals table.
"""

import time
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional

# FastF1 (requires f1_cache/)
try:
    import fastf1
    fastf1.Cache.enable_cache('f1_cache')
    FASTF1_AVAILABLE = True
except ImportError:
    FASTF1_AVAILABLE = False
    print("⚠️ fastf1 not installed — F1 Engine will run in degraded mode")

# OpenF1 live API
OPENF1_BASE = "https://api.openf1.org/v1"

# Kalshi F1 market integration
try:
    from src.kalshi_feed import get_all_active_markets
    KALSHI_AVAILABLE = True
except ImportError:
    KALSHI_AVAILABLE = False


class F1Engine:
    """Generates Kalshi F1 prop signals from FastF1 telemetry and OpenF1 live data."""

    def __init__(self, min_edge_pct: float = 10.0, cache_dir: str = "f1_cache"):
        self.min_edge_pct = min_edge_pct
        self.cache_dir    = cache_dir
        self._signal_cache: list = []
        self._last_signal_refresh: Optional[datetime] = None

    # ─── FastF1 Session Loaders ───────────────────────────────────────────────

    def _load_session(self, year: int, round_num: int, session_name: str) -> Optional[object]:
        """Load a FastF1 session from cache. Returns None if data unavailable."""
        if not FASTF1_AVAILABLE:
            return None
        try:
            session = fastf1.get_session(year, round_num, session_name)
            session.load(laps=True, telemetry=False, weather=False)
            return session
        except Exception as e:
            print(f"  ⚠️ F1Engine: Could not load {year} R{round_num} {session_name}: {e}")
            return None

    def _get_current_event(self, year: int = 2026) -> Optional[dict]:
        """
        Returns the most recently completed or ongoing race weekend.
        Uses the FastF1 schedule (cached locally).
        """
        if not FASTF1_AVAILABLE:
            return None
        try:
            schedule = fastf1.get_event_schedule(year)
            now = datetime.now(timezone.utc)
            past = schedule[
                pd.to_datetime(schedule['EventDate'], utc=True) <= pd.Timestamp(now)
            ]
            if past.empty:
                return None
            row = past.iloc[-1]  # Most recent event
            return {
                "round":  int(row["RoundNumber"]),
                "name":   row["EventName"],
                "date":   str(row["EventDate"])[:10],
            }
        except Exception as e:
            print(f"  ⚠️ F1Engine: Schedule load error: {e}")
            return None

    def fetch_upcoming_races(self) -> list:
        """Returns the next upcoming F1 race as a mock Kalshi edge for the frontend calendar."""
        if not FASTF1_AVAILABLE:
            return []
        
        try:
            schedule = fastf1.get_event_schedule(2026)
            now = datetime.now(timezone.utc)
            future = schedule[
                pd.to_datetime(schedule['EventDate'], utc=True) > pd.Timestamp(now)
            ]
            if future.empty:
                return []
                
            future = future.sort_values(by="EventDate").iloc[0] # Next race
            race_name = future["EventName"]
            race_date = str(future["EventDate"])[:10]
            round_num = future["RoundNumber"]
            
            return [{
                "title": f"F1: {race_name}",
                "edge_type": "SPORTS",
                "market_id": f"f1_race_{round_num}",
                "our_prob": 0,
                "market_prob": 0,
                "raw_payload": {"race": race_name, "date": race_date, "round": f"{round_num}"}
            }]
        except Exception as e:
            print(f"  ⚠️ F1Engine schedule error: {e}")
            return []

    # ─── Feature Engineering ─────────────────────────────────────────────────

    def _compute_sector_zscores(self, session) -> pd.DataFrame:
        """
        For each driver, compute z-scores of sector times vs the field.
        Negative z = faster than average (good).
        Returns a DataFrame with columns: Driver, S1_z, S2_z, S3_z, lap_z
        """
        if session is None:
            return pd.DataFrame()

        laps = session.laps.copy()
        laps = laps[laps['IsAccurate'] == True].copy()

        for col in ['Sector1Time', 'Sector2Time', 'Sector3Time', 'LapTime']:
            laps[f'{col}_s'] = laps[col].dt.total_seconds()

        # Group by driver, take fastest lap per driver
        best = laps.groupby('Driver').agg({
            'Sector1Time_s': 'min',
            'Sector2Time_s': 'min',
            'Sector3Time_s': 'min',
            'LapTime_s':     'min',
        }).reset_index()

        # Z-score relative to field
        for col in ['Sector1Time_s', 'Sector2Time_s', 'Sector3Time_s', 'LapTime_s']:
            mu    = best[col].mean()
            sigma = best[col].std() if best[col].std() > 0 else 1.0
            best[f'{col}_z'] = (best[col] - mu) / sigma

        return best

    def _compute_tyre_degradation(self, race_session) -> pd.DataFrame:
        """
        Computes lap-time deterioration per lap on each compound.
        Returns DataFrame: Driver, Compound, deg_rate_sec_per_lap
        """
        if race_session is None:
            return pd.DataFrame()

        laps = race_session.laps.copy()
        laps = laps[laps['IsAccurate'] == True].copy()
        laps['LapTime_s'] = laps['LapTime'].dt.total_seconds()
        laps = laps.dropna(subset=['LapTime_s', 'TyreLife', 'Compound'])

        results = []
        for (driver, compound), g in laps.groupby(['Driver', 'Compound']):
            if len(g) < 4:
                continue
            # Linear regression: LapTime ~ TyreLife
            x = g['TyreLife'].values.astype(float)
            y = g['LapTime_s'].values
            if x.std() < 0.1:
                continue
            deg_rate = np.polyfit(x, y, 1)[0]  # Slope = deg per lap
            results.append({
                "Driver":   driver,
                "Compound": compound,
                "deg_rate": round(deg_rate, 4),
                "laps":     len(g),
            })

        return pd.DataFrame(results)

    # ─── Podium Probability Model ─────────────────────────────────────────────

    def _estimate_podium_prob(self, driver: str, sector_df: pd.DataFrame,
                               deg_df: pd.DataFrame) -> float:
        """
        Estimates P(driver finishes on podium) based on:
        - Qualifying sector-time z-score (pace indicator)
        - Best compound degradation rate (strategy indicator)

        Simple Bayesian approach:
        - Base rate: 3/20 = 15% (3 podiums, 20 drivers)
        - Lap time z-score better than -0.5σ: aggressive upward adjustment
        - Lap time z-score worse than +0.5σ: aggressive downward adjustment
        """
        base_prob = 15.0  # Base: 3 podiums / 20 drivers

        # Sector-time adjustment
        driver_row = sector_df[sector_df['Driver'] == driver]
        if not driver_row.empty:
            lap_z = driver_row['LapTime_s_z'].values[0]
            # Each sigma below average → +7% podium probability
            prob = base_prob - lap_z * 7.0
        else:
            prob = base_prob

        # Tyre degradation adjustment
        driver_deg = deg_df[deg_df['Driver'] == driver] if not deg_df.empty else pd.DataFrame()
        if not driver_deg.empty:
            best_deg = driver_deg['deg_rate'].min()  # Lower = less degradation = better
            # If deg_rate < 0.05 s/lap (very low), boost; if > 0.2 (high), penalise
            if best_deg < 0.05:
                prob += 5.0
            elif best_deg > 0.20:
                prob -= 5.0

        return round(min(max(prob, 2.0), 90.0), 1)

    # ─── Kalshi F1 Market Lookup ─────────────────────────────────────────────

    def _find_kalshi_f1_market(self, driver: str, signal_type: str,
                                kalshi_markets: list) -> Optional[dict]:
        """
        Fuzzy-matches driver + signal type to a Kalshi F1 market.
        Kalshi F1 tickers: F1PODIUM-VER, F1WIN-HAM, F1-FASTEST-NOR, etc.
        """
        driver_map = {
            "VER": ["VER", "VERSTAPPEN"],
            "HAM": ["HAM", "HAMILTON"],
            "NOR": ["NOR", "NORRIS"],
            "LEC": ["LEC", "LECLERC"],
            "PIA": ["PIA", "PIASTRI"],
            "SAI": ["SAI", "SAINZ"],
            "RUS": ["RUS", "RUSSELL"],
            "ALO": ["ALO", "ALONSO"],
            "GAS": ["GAS", "GASLY"],
            "STR": ["STR", "STROLL"],
        }
        type_keywords = {
            "podium":      ["PODIUM", "TOP3"],
            "win":         ["WIN", "WINNER"],
            "fastest_lap": ["FASTEST", "FL"],
        }

        search_terms = driver_map.get(driver, [driver])
        type_terms   = type_keywords.get(signal_type, [signal_type.upper()])

        for m in kalshi_markets:
            ticker = m.get("ticker", "").upper()
            title  = m.get("title", "").upper()
            if any(t in ticker or t in title for t in search_terms):
                if any(tt in ticker or tt in title for tt in type_terms):
                    return m
        return None

    # ─── OpenF1 Live Data ─────────────────────────────────────────────────────

    def get_live_lap_data(self, session_key: str = "latest") -> pd.DataFrame:
        """
        Fetches live lap data from OpenF1 during race weekend.
        session_key = 'latest' returns data from the current session.
        """
        try:
            r = requests.get(
                f"{OPENF1_BASE}/laps",
                params={"session_key": session_key},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                if data:
                    return pd.DataFrame(data)
        except Exception as e:
            print(f"  ⚠️ OpenF1 live lap fetch error: {e}")
        return pd.DataFrame()

    def get_live_race_control(self, session_key: str = "latest") -> list:
        """Fetches race control messages (VSC, SC, flags) from OpenF1."""
        try:
            r = requests.get(
                f"{OPENF1_BASE}/race_control",
                params={"session_key": session_key},
                timeout=10,
            )
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"  ⚠️ OpenF1 race control fetch error: {e}")
        return []

    # ─── Main Signal Generator ───────────────────────────────────────────────

    def get_latest_signals(self, year: int = 2026, force_refresh: bool = False) -> list:
        """
        Returns cached F1 signals, refreshing if >10 min old or force_refresh=True.
        """
        if (
            not force_refresh
            and self._signal_cache
            and self._last_signal_refresh
            and (datetime.now(timezone.utc) - self._last_signal_refresh).total_seconds() < 600
        ):
            return self._signal_cache

        return self._generate_signals(year)

    def _generate_signals(self, year: int = 2026) -> list:
        """Core signal generation logic."""
        event = self._get_current_event(year)
        if not event:
            print("  ⚠️ F1Engine: No completed events found in cache.")
            return []

        print(f"  🏎️ F1Engine: Analysing R{event['round']} {event['name']}")

        # Load sessions
        quali = self._load_session(year, event["round"], "Qualifying")
        race  = self._load_session(year, event["round"], "Race")

        # Feature computation
        sector_df = self._compute_sector_zscores(quali)
        deg_df    = self._compute_tyre_degradation(race)

        if sector_df.empty:
            print("  ⚠️ F1Engine: No qualifying data available.")
            return []

        # Fetch Kalshi F1 markets
        kalshi_markets = []
        if KALSHI_AVAILABLE:
            try:
                all_markets = get_all_active_markets(limit_pages=3)
                kalshi_markets = [
                    m for m in all_markets
                    if "F1" in m.get("ticker", "").upper() or
                    "FORMULA" in m.get("title", "").upper() or
                    "GRAND PRIX" in m.get("title", "").upper()
                ]
                print(f"  🏎️ {len(kalshi_markets)} Kalshi F1 markets found")
            except Exception as e:
                print(f"  ⚠️ Kalshi fetch error: {e}")

        signals = []
        drivers = sector_df['Driver'].unique()

        for driver in drivers:
            for signal_type in ["podium", "win"]:
                # Estimate probability
                if signal_type == "podium":
                    model_prob = self._estimate_podium_prob(driver, sector_df, deg_df)
                else:  # win
                    model_prob = self._estimate_podium_prob(driver, sector_df, deg_df) / 3.0

                # Get key metric for the signal
                driver_row    = sector_df[sector_df['Driver'] == driver]
                lap_z_display = ""
                if not driver_row.empty:
                    z = driver_row['LapTime_s_z'].values[0]
                    lap_z_display = f"Quali pace z={z:+.2f}σ vs field"

                # Cross-reference Kalshi
                kalshi_mkt   = self._find_kalshi_f1_market(driver, signal_type, kalshi_markets)
                kalshi_price = kalshi_mkt["price"] if kalshi_mkt else None
                edge_pct     = round(model_prob - kalshi_price, 1) if kalshi_price else None

                action = None
                if edge_pct is not None:
                    if edge_pct > self.min_edge_pct:
                        action = "BUY YES"
                    elif edge_pct < -self.min_edge_pct:
                        action = "BUY NO"

                if (edge_pct is not None and abs(edge_pct) >= self.min_edge_pct):
                    signals.append({
                        "driver":       driver,
                        "team":         "N/A",   # Would need team lookup
                        "event":        event["name"],
                        "session":      "Qualifying → Race projection",
                        "signal_type":  signal_type,
                        "model_prob":   model_prob,
                        "kalshi_ticker": kalshi_mkt.get("ticker") if kalshi_mkt else None,
                        "kalshi_yes_ask": kalshi_price,
                        "edge_pct":     edge_pct,
                        "action":       action,
                        "key_metric":   lap_z_display,
                        "detected_at":  datetime.now(timezone.utc).isoformat(),
                    })

        signals.sort(key=lambda x: abs(x.get("edge_pct") or 0), reverse=True)
        self._signal_cache = signals
        self._last_signal_refresh = datetime.now(timezone.utc)

        print(f"  🏎️ F1Engine: {len(signals)} signals generated")
        return signals


# ── Dev entrypoint ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🏎️ F1 Engine — Running signal scan...\n")
    engine = F1Engine(min_edge_pct=8.0)
    signals = engine.get_latest_signals()
    print(f"\n✅ Signals found: {len(signals)}")
    for s in signals[:5]:
        edge_val = s.get('edge_pct')
        edge_str = f"+{edge_val:.1f}%" if edge_val else "no mkt"
        print(
            f"  {s['driver']} {s['signal_type']} | "
            f"Model: {s['model_prob']:.1f}% | "
            f"Kalshi: {s.get('kalshi_yes_ask', 'N/A')}¢ | "
            f"Edge: {edge_str} | "
            f"{s.get('key_metric', '')}"
        )
