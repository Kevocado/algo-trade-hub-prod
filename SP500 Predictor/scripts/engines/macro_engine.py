"""
Macro Economics Engine v2 — Multi-Factor Fed Model + FRED API + Kalshi Series

EDGE SOURCE: FRED data + leading indicators + structural adjustments.
Compare multi-factor predictions against Kalshi market prices.

INTELLIGENCE LAYERS:
  1. Base FRED data (CPI, Fed Rate, GDP, Unemployment)
  2. Powell-Warsh transition penalty (May 2026 handoff)
  3. Leading inflation signals (PPI, oil, import prices)
  4. Tariff/supply shock multiplier (goods vs services CPI divergence)
  5. Taylor Rule reality check (bounds model predictions)

KALSHI SERIES:
  KXLCPIMAXYOY    - Max CPI YoY for the year
  KXFED           - Fed funds rate after each meeting
  KXGDPYEAR       - GDP growth for the year
  KXRECSSNBER     - Recession probability (NBER definition)
  KXU3MAX         - Max unemployment rate
  KXFEDDECISION   - Fed decision (cut/hold/hike)

DATA: FREE - https://fred.stlouisfed.org/docs/api/api_key.html
"""

import fredapi
import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.kalshi_feed import get_economics_markets, get_kalshi_event_url

load_dotenv()


class MacroEngine:
    def __init__(self):
        api_key = os.getenv('FRED_API_KEY')
        if not api_key:
            raise ValueError("FRED_API_KEY not found in environment variables")

        self.fred = fredapi.Fred(api_key=api_key)

        # Cache for FRED data (avoid repeated API calls within one scan)
        self._cache = {}

    # ═══════════════════════════════════════════════════════════════
    # LAYER 1: BASE FRED DATA (existing)
    # ═══════════════════════════════════════════════════════════════

    def get_latest_cpi_yoy(self):
        """Get the latest CPI Year-over-Year percentage from FRED."""
        if 'cpi_yoy' in self._cache:
            return self._cache['cpi_yoy']
        try:
            cpi = self.fred.get_series('CPIAUCSL', observation_start='2024-01-01')
            if len(cpi) >= 13:
                latest = cpi.iloc[-1]
                year_ago = cpi.iloc[-13]
                yoy = ((latest - year_ago) / year_ago) * 100
                self._cache['cpi_yoy'] = round(yoy, 2)
                return self._cache['cpi_yoy']
            return None
        except Exception as e:
            print(f"    ⚠️ CPI fetch error: {e}")
            return None

    def get_fed_rate_prediction(self):
        """Get current Fed Funds Rate upper bound from FRED."""
        if 'fed_rate' in self._cache:
            return self._cache['fed_rate']
        try:
            fed_rate = self.fred.get_series('DFEDTARU', observation_start='2024-01-01')
            if len(fed_rate) > 0:
                self._cache['fed_rate'] = round(fed_rate.iloc[-1], 2)
                return self._cache['fed_rate']
            return None
        except Exception as e:
            print(f"    ⚠️ Fed rate fetch error: {e}")
            return None

    def get_gdp_prediction(self):
        """Get latest GDP growth rate from FRED."""
        if 'gdp' in self._cache:
            return self._cache['gdp']
        try:
            gdp = self.fred.get_series('A191RL1Q225SBEA', observation_start='2024-01-01')
            if len(gdp) > 0:
                self._cache['gdp'] = round(gdp.iloc[-1], 2)
                return self._cache['gdp']
            return None
        except Exception as e:
            print(f"    ⚠️ GDP fetch error: {e}")
            return None

    def get_unemployment_rate(self):
        """Get latest unemployment rate."""
        if 'unemp' in self._cache:
            return self._cache['unemp']
        try:
            u3 = self.fred.get_series('UNRATE', observation_start='2024-01-01')
            if len(u3) > 0:
                self._cache['unemp'] = round(u3.iloc[-1], 2)
                return self._cache['unemp']
            return None
        except Exception as e:
            print(f"    ⚠️ Unemployment fetch error: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════
    # LAYER 2: POWELL-WARSH TRANSITION PENALTY
    # ═══════════════════════════════════════════════════════════════

    def get_transition_penalty(self):
        """
        Returns a probability adjustment for Fed rate markets during
        the final 90 days of Powell's tenure (term expires May 15, 2026).

        Insight: Incoming Chairs rarely face a surprise from predecessors.
        Powell is unlikely to make a major move in his last meetings.
        This penalizes predictions of hikes/cuts near the transition.

        Returns: dict with 'penalty' (0 to -15), 'in_transition' (bool),
                 'days_remaining' (int), 'reasoning' (str)
        """
        # Powell's term as Fed Chair expires May 15, 2026
        powell_expiry = datetime(2026, 5, 15)
        now = datetime.now()
        days_remaining = (powell_expiry - now).days

        if days_remaining <= 0:
            return {
                'penalty': 0,
                'in_transition': False,
                'days_remaining': 0,
                'reasoning': 'Powell term ended. New Chair in place — no transition penalty.'
            }
        elif days_remaining <= 30:
            # Final month: strong penalty against major moves
            return {
                'penalty': -15,
                'in_transition': True,
                'days_remaining': days_remaining,
                'reasoning': f'Powell exits in {days_remaining}d — very unlikely to make major moves. '
                             f'Warsh transition creates strong hold bias.'
            }
        elif days_remaining <= 60:
            return {
                'penalty': -10,
                'in_transition': True,
                'days_remaining': days_remaining,
                'reasoning': f'Powell exits in {days_remaining}d — transition dampens bold action.'
            }
        elif days_remaining <= 90:
            return {
                'penalty': -5,
                'in_transition': True,
                'days_remaining': days_remaining,
                'reasoning': f'Powell exits in {days_remaining}d — mild transition drag on policy shifts.'
            }
        else:
            return {
                'penalty': 0,
                'in_transition': False,
                'days_remaining': days_remaining,
                'reasoning': 'No transition effect.'
            }

    # ═══════════════════════════════════════════════════════════════
    # LAYER 3: LEADING INFLATION SIGNALS
    # ═══════════════════════════════════════════════════════════════

    def get_leading_inflation_signals(self):
        """
        Fetch leading indicators that move BEFORE CPI prints.
        These give us an edge over Kalshi markets pricing lagging CPI data.

        Indicators:
          - PPI (Producer Price Index) — upstream cost pressure
          - Oil Prices (WTI crude) — energy pass-through
          - Core PCE — Fed's preferred inflation gauge

        Returns: dict with 'signal' ("hot"|"neutral"|"cooling"),
                 'ppi_trend', 'oil_trend', 'adjustment' (-10 to +10)
        """
        result = {
            'signal': 'neutral',
            'ppi_trend': 'flat',
            'oil_trend': 'flat',
            'adjustment': 0,
            'reasoning': ''
        }

        signals = []

        # PPI (Producer Price Index) — leads CPI by 1-2 months
        try:
            ppi = self.fred.get_series('PPIACO', observation_start='2024-01-01')
            if len(ppi) >= 4:
                ppi_3m_change = ((ppi.iloc[-1] / ppi.iloc[-4]) - 1) * 100
                if ppi_3m_change > 1.5:
                    result['ppi_trend'] = 'rising'
                    signals.append('hot')
                elif ppi_3m_change < -0.5:
                    result['ppi_trend'] = 'falling'
                    signals.append('cool')
                else:
                    signals.append('neutral')
        except Exception:
            pass

        # Oil Prices (WTI Crude) — energy pass-through
        try:
            oil = self.fred.get_series('DCOILWTICO', observation_start='2024-06-01')
            if len(oil) >= 20:
                oil_recent = oil.dropna()
                if len(oil_recent) >= 20:
                    oil_1m_change = ((oil_recent.iloc[-1] / oil_recent.iloc[-20]) - 1) * 100
                    if oil_1m_change > 10:
                        result['oil_trend'] = 'spiking'
                        signals.append('hot')
                    elif oil_1m_change > 5:
                        result['oil_trend'] = 'rising'
                        signals.append('hot')
                    elif oil_1m_change < -5:
                        result['oil_trend'] = 'falling'
                        signals.append('cool')
                    else:
                        signals.append('neutral')
        except Exception:
            pass

        # Core PCE — Fed's preferred measure
        try:
            pce = self.fred.get_series('PCEPILFE', observation_start='2024-01-01')
            if len(pce) >= 13:
                pce_yoy = ((pce.iloc[-1] / pce.iloc[-13]) - 1) * 100
                if pce_yoy > 3.0:
                    signals.append('hot')
                elif pce_yoy < 2.0:
                    signals.append('cool')
                else:
                    signals.append('neutral')
        except Exception:
            pass

        # Aggregate signal
        hot_count = signals.count('hot')
        cool_count = signals.count('cool')

        if hot_count >= 2:
            result['signal'] = 'hot'
            result['adjustment'] = 8  # Inflation running hotter than CPI shows
            result['reasoning'] = f'Leading indicators hot: PPI {result["ppi_trend"]}, Oil {result["oil_trend"]}. CPI likely to rise.'
        elif cool_count >= 2:
            result['signal'] = 'cooling'
            result['adjustment'] = -8  # Inflation cooling faster than CPI shows
            result['reasoning'] = f'Leading indicators cooling: PPI {result["ppi_trend"]}, Oil {result["oil_trend"]}. CPI likely to fall.'
        else:
            result['reasoning'] = 'Leading indicators mixed — no strong directional signal.'

        return result

    # ═══════════════════════════════════════════════════════════════
    # LAYER 4: TARIFF / SUPPLY SHOCK MULTIPLIER
    # ═══════════════════════════════════════════════════════════════

    def get_tariff_shock_factor(self):
        """
        Detects tariff pass-through by comparing goods inflation vs services inflation.
        If goods CPI is spiking while services is flat → tariff-driven inflation.
        The Fed typically "looks through" tariff inflation (won't hike for it),
        but also won't CUT into tariff-driven price increases.

        Returns: dict with 'multiplier' (0.7 to 1.3), 'shock_detected' (bool),
                 'goods_services_spread', 'reasoning'
        """
        result = {
            'multiplier': 1.0,
            'shock_detected': False,
            'goods_services_spread': 0,
            'reasoning': 'No tariff shock detected.'
        }

        try:
            # Commodities less food & energy (goods inflation proxy)
            goods = self.fred.get_series('CUSR0000SACL1E', observation_start='2024-01-01')
            # Services less energy (services inflation proxy)
            services = self.fred.get_series('CUSR0000SASLE', observation_start='2024-01-01')

            if len(goods) >= 13 and len(services) >= 13:
                goods_yoy = ((goods.iloc[-1] / goods.iloc[-13]) - 1) * 100
                services_yoy = ((services.iloc[-1] / services.iloc[-13]) - 1) * 100
                spread = goods_yoy - services_yoy

                result['goods_services_spread'] = round(spread, 2)

                if spread > 2.0:
                    # Goods inflation >> services → tariff pass-through
                    result['shock_detected'] = True
                    result['multiplier'] = 0.7  # Reduce rate-cut probability
                    result['reasoning'] = (
                        f'Tariff shock: goods inflation ({goods_yoy:.1f}%) >> services ({services_yoy:.1f}%). '
                        f'Fed likely to hold — won\'t cut into tariff-driven prices.'
                    )
                elif spread < -1.0:
                    # Services inflation >> goods → organic/demand-driven
                    result['multiplier'] = 1.2  # Slightly more hawkish
                    result['reasoning'] = (
                        f'Services-driven inflation ({services_yoy:.1f}% vs goods {goods_yoy:.1f}%). '
                        f'Fed MORE likely to act (services = sticky/demand-driven).'
                    )
        except Exception as e:
            print(f"    ⚠️ Tariff shock data error: {e}")

        return result

    # ═══════════════════════════════════════════════════════════════
    # LAYER 5: TAYLOR RULE REALITY CHECK
    # ═══════════════════════════════════════════════════════════════

    def get_taylor_rule_rate(self):
        """
        Calculate the Taylor Rule prescriptive rate.

        Taylor Rule: r = r* + 0.5*(π - π*) + 0.5*(y - y*)
        Where:
          r*  = neutral real rate (estimated 0.5%)
          π   = current inflation (Core PCE YoY)
          π*  = target inflation (2%)
          y   = real GDP growth
          y*  = potential GDP growth (estimated 2%)

        Returns: dict with 'taylor_rate', 'current_rate', 'divergence',
                 'model_risk' (bool), 'reasoning'
        """
        result = {
            'taylor_rate': None,
            'current_rate': None,
            'divergence': 0,
            'model_risk': False,
            'reasoning': ''
        }

        try:
            # Get inputs
            fed_rate = self.get_fed_rate_prediction()
            cpi_yoy = self.get_latest_cpi_yoy()
            gdp = self.get_gdp_prediction()

            if fed_rate is None or cpi_yoy is None:
                result['reasoning'] = 'Insufficient data for Taylor Rule.'
                return result

            # Also try Core PCE for more accurate inflation
            inflation = cpi_yoy
            try:
                pce = self.fred.get_series('PCEPILFE', observation_start='2024-01-01')
                if len(pce) >= 13:
                    inflation = round(((pce.iloc[-1] / pce.iloc[-13]) - 1) * 100, 2)
            except Exception:
                pass  # Fall back to CPI

            # Taylor Rule parameters
            r_star = 0.5        # Neutral real rate
            pi_target = 2.0     # Fed inflation target
            y_star = 2.0        # Potential GDP growth
            gdp_val = gdp if gdp is not None else 2.0  # Default to trend

            # Taylor Rule calculation
            taylor = inflation + r_star + 0.5 * (inflation - pi_target) + 0.5 * (gdp_val - y_star)
            taylor = round(taylor, 2)

            divergence = abs(fed_rate - taylor)

            result['taylor_rate'] = taylor
            result['current_rate'] = fed_rate
            result['divergence'] = round(divergence, 2)

            if divergence > 1.0:
                result['model_risk'] = True
                if fed_rate > taylor:
                    result['reasoning'] = (
                        f'Taylor Rule says {taylor}% but rate is {fed_rate}%. '
                        f'Policy is TIGHT — rate cuts more likely than market thinks.'
                    )
                else:
                    result['reasoning'] = (
                        f'Taylor Rule says {taylor}% but rate is {fed_rate}%. '
                        f'Policy is LOOSE — rate hikes more likely than market thinks.'
                    )
            elif divergence > 0.5:
                result['reasoning'] = (
                    f'Taylor Rule: {taylor}% vs actual {fed_rate}%. '
                    f'Moderate divergence — model predictions near this spread have higher risk.'
                )
            else:
                result['reasoning'] = (
                    f'Taylor Rule: {taylor}% ≈ actual {fed_rate}%. '
                    f'Policy is roughly neutral — model predictions reliable.'
                )

        except Exception as e:
            result['reasoning'] = f'Taylor Rule calc error: {e}'

        return result

    # ═══════════════════════════════════════════════════════════════
    # MAIN OPPORTUNITY FINDER (enhanced with all layers)
    # ═══════════════════════════════════════════════════════════════

    def find_opportunities(self, kalshi_markets=None):
        """
        Compare multi-factor predictions to Kalshi economics markets.
        Enhanced with transition penalties, leading signals, tariff
        shock, and Taylor Rule reality checks.

        Returns list of opportunities with meaningful edge.
        """
        if kalshi_markets is None:
            kalshi_markets = get_economics_markets()

        if not kalshi_markets:
            print("    No Kalshi economics markets found.")
            return []

        opportunities = []

        # ── Layer 1: Base FRED Data ──
        cpi_yoy = self.get_latest_cpi_yoy()
        fed_rate = self.get_fed_rate_prediction()
        gdp = self.get_gdp_prediction()
        unemployment = self.get_unemployment_rate()

        print(f"    📊 FRED Data: CPI={cpi_yoy}%, Fed Rate={fed_rate}%, GDP={gdp}%, Unemp={unemployment}%")

        # ── Layer 2-5: Intelligence Factors ──
        transition = self.get_transition_penalty()
        inflation_signals = self.get_leading_inflation_signals()
        tariff = self.get_tariff_shock_factor()
        taylor = self.get_taylor_rule_rate()

        if transition['in_transition']:
            print(f"    🏛️ Transition: {transition['reasoning']}")
        if inflation_signals['signal'] != 'neutral':
            print(f"    📈 Leading Inflation: {inflation_signals['reasoning']}")
        if tariff['shock_detected']:
            print(f"    🚢 Tariff Shock: {tariff['reasoning']}")
        if taylor['taylor_rate']:
            print(f"    📐 Taylor Rule: {taylor['reasoning']}")

        for market in kalshi_markets:
            econ_type = market.get('_econ_type', '')
            yes_ask = market.get('yes_ask', 0)
            ticker = market.get('ticker', '')
            event_ticker = market.get('event_ticker', '')
            title = market.get('title', '')
            subtitle = market.get('subtitle', '')
            floor = market.get('floor_strike')
            cap = market.get('cap_strike')

            if yes_ask == 0:
                continue

            edge = None
            action = None
            model_prob = None
            reasoning = None
            factors_used = []

            # ── CPI / Inflation Markets ──
            if econ_type == 'CPI' and cpi_yoy is not None:
                if floor is not None:
                    # "At least X%" market
                    if cpi_yoy > floor + 0.5:
                        model_prob = 85
                    elif cpi_yoy > floor:
                        model_prob = 60
                    elif cpi_yoy > floor - 0.3:
                        model_prob = 35
                    else:
                        model_prob = 10

                    # LAYER 3: Leading inflation adjustment
                    if inflation_signals['signal'] == 'hot':
                        model_prob = min(95, model_prob + inflation_signals['adjustment'])
                        factors_used.append(f"Leading indicators hot (+{inflation_signals['adjustment']}%)")
                    elif inflation_signals['signal'] == 'cooling':
                        model_prob = max(5, model_prob + inflation_signals['adjustment'])
                        factors_used.append(f"Leading indicators cooling ({inflation_signals['adjustment']}%)")

                    edge = model_prob - yes_ask
                    action = 'BUY YES' if edge > 0 else 'BUY NO'
                    reasoning = (
                        f"CPI YoY: {cpi_yoy}% | Strike: ≥{floor}% | "
                        f"Model: {model_prob}% (PPI {inflation_signals['ppi_trend']}, Oil {inflation_signals['oil_trend']})"
                    )

            # ── Fed Funds Rate Markets ──
            elif econ_type == 'Fed Rate' and fed_rate is not None:
                if floor is not None:
                    rate_diff = fed_rate - floor
                    if rate_diff > 0.5:
                        model_prob = 85
                    elif rate_diff > 0:
                        model_prob = 60
                    elif rate_diff > -0.25:
                        model_prob = 40
                    else:
                        model_prob = 15

                    # LAYER 2: Transition penalty (dampens major moves)
                    if transition['in_transition'] and abs(rate_diff) < 0.5:
                        # Only apply near decision boundaries
                        model_prob = max(5, min(95, model_prob + transition['penalty']))
                        factors_used.append(f"Transition penalty ({transition['penalty']}%)")

                    # LAYER 4: Tariff shock effect
                    if tariff['shock_detected']:
                        # Tariff shock reduces rate-cut probability
                        if model_prob > 50:  # If predicting rate stays high
                            model_prob = min(95, int(model_prob * tariff['multiplier']))
                        else:  # If predicting rate drops
                            model_prob = max(5, int(model_prob * tariff['multiplier']))
                        factors_used.append(f"Tariff shock (×{tariff['multiplier']})")

                    # LAYER 5: Taylor Rule bounds check
                    if taylor['taylor_rate'] is not None:
                        taylor_rate = taylor['taylor_rate']
                        # If our prediction diverges > 50bp from Taylor, reduce confidence
                        if taylor['divergence'] > 0.5:
                            confidence_penalty = min(10, int(taylor['divergence'] * 5))
                            # Nudge model_prob toward 50% (less confident)
                            if model_prob > 50:
                                model_prob = max(50, model_prob - confidence_penalty)
                            else:
                                model_prob = min(50, model_prob + confidence_penalty)
                            factors_used.append(f"Taylor Rule divergence (-{confidence_penalty}% confidence)")

                    edge = model_prob - yes_ask
                    action = 'BUY YES' if edge > 0 else 'BUY NO'

                    factors_str = ' | '.join(factors_used) if factors_used else 'Base FRED only'
                    reasoning = (
                        f"Fed rate: {fed_rate}% | Strike: {floor}% | "
                        f"Model: {model_prob}% | Factors: {factors_str}"
                    )
                    if taylor['taylor_rate']:
                        reasoning += f" | Taylor Rule: {taylor['taylor_rate']}%"

            # ── GDP Markets ──
            elif econ_type == 'GDP' and gdp is not None:
                if floor is not None and cap is None:
                    if gdp > floor + 1:
                        model_prob = 80
                    elif gdp > floor:
                        model_prob = 55
                    else:
                        model_prob = 20

                    edge = model_prob - yes_ask
                    action = 'BUY YES' if edge > 0 else 'BUY NO'
                    reasoning = f"Latest GDP: {gdp}%. Strike: >{floor}%. FRED suggests {model_prob}% prob."

                elif floor is not None and cap is not None:
                    mid = (floor + cap) / 2
                    if floor <= gdp <= cap:
                        model_prob = 65
                    elif abs(gdp - mid) < 1:
                        model_prob = 30
                    else:
                        model_prob = 10

                    edge = model_prob - yes_ask
                    action = 'BUY YES' if edge > 0 else 'BUY NO'
                    reasoning = f"Latest GDP: {gdp}%. Range: {floor}%-{cap}%. FRED suggests {model_prob}% prob."

            # ── Unemployment Markets ──
            elif econ_type == 'Unemployment' and unemployment is not None:
                if floor is not None and cap is None:
                    # "Unemployment above X%"
                    if unemployment > floor + 0.5:
                        model_prob = 80
                    elif unemployment > floor:
                        model_prob = 55
                    elif unemployment > floor - 0.3:
                        model_prob = 30
                    else:
                        model_prob = 10

                    edge = model_prob - yes_ask
                    action = 'BUY YES' if edge > 0 else 'BUY NO'
                    reasoning = f"Unemployment: {unemployment}%. Strike: >{floor}%. Model: {model_prob}%."

                elif floor is not None and cap is not None:
                    if floor <= unemployment <= cap:
                        model_prob = 60
                    elif abs(unemployment - (floor + cap) / 2) < 0.5:
                        model_prob = 30
                    else:
                        model_prob = 10

                    edge = model_prob - yes_ask
                    action = 'BUY YES' if edge > 0 else 'BUY NO'
                    reasoning = f"Unemployment: {unemployment}%. Range: {floor}%-{cap}%. Model: {model_prob}%."

            # ── Recession Markets ──
            elif econ_type == 'Recession':
                if unemployment is not None and gdp is not None:
                    if unemployment > 5 and gdp < 0:
                        model_prob = 70
                    elif unemployment > 4.5 or gdp < 1:
                        model_prob = 35
                    else:
                        model_prob = 15

                    # Tariff shock increases recession risk slightly
                    if tariff['shock_detected']:
                        model_prob = min(80, model_prob + 10)
                        factors_used.append("Tariff shock (+10% recession risk)")

                    edge = model_prob - yes_ask
                    action = 'BUY YES' if edge > 0 else 'BUY NO'
                    reasoning = f"Unemp: {unemployment}%, GDP: {gdp}%. Recession prob: {model_prob}%."
                    if factors_used:
                        reasoning += f" Factors: {', '.join(factors_used)}"

            # Only flag if edge is meaningful
            if edge is not None and abs(edge) > 8:
                kalshi_url = get_kalshi_event_url(event_ticker)
                expiration = market.get('expiration_time', '')
                market_date_str = ''
                if expiration:
                    try:
                        market_date_str = expiration[:10]
                    except Exception:
                        pass
                opportunities.append({
                    'engine': 'Macro',
                    'asset': econ_type,
                    'market_title': f"{title} — {subtitle}" if subtitle else title,
                    'market_ticker': ticker,
                    'event_ticker': event_ticker,
                    'action': action,
                    'model_probability': model_prob,
                    'market_price': yes_ask,
                    'edge': abs(edge),
                    'confidence': model_prob,
                    'reasoning': reasoning,
                    'data_source': 'FRED API + Multi-Factor Model',
                    'kalshi_url': kalshi_url,
                    'market_date': market_date_str,
                    'expiration': expiration,
                    'factors': factors_used,
                })

        return opportunities


if __name__ == "__main__":
    print("Running Enhanced Macro Engine v2...")
    try:
        engine = MacroEngine()

        # Show intelligence layers
        print("\n── Intelligence Layers ──")
        transition = engine.get_transition_penalty()
        print(f"  Transition: {transition['reasoning']}")

        signals = engine.get_leading_inflation_signals()
        print(f"  Inflation Signals: {signals['signal']} — {signals['reasoning']}")

        tariff = engine.get_tariff_shock_factor()
        print(f"  Tariff Shock: {'DETECTED' if tariff['shock_detected'] else 'None'} — {tariff['reasoning']}")

        taylor = engine.get_taylor_rule_rate()
        print(f"  Taylor Rule: {taylor['reasoning']}")

        # Find opportunities
        print("\n── Scanning Markets ──")
        opps = engine.find_opportunities()
        print(f"\n  Found {len(opps)} macro opportunities")
        for o in opps[:10]:
            factors = o.get('factors', [])
            factor_str = f" [{', '.join(factors)}]" if factors else ""
            print(f"  {o['asset']}: {o['action']} | Edge: {o['edge']:.1f}% | {o['reasoning'][:100]}{factor_str}")
            print(f"    → {o['kalshi_url']}")
    except ValueError as e:
        print(f"  {e}")