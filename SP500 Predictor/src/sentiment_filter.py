"""
Hugging Face Sentiment Pre-Filter

PURPOSE: Use free, local transformer models to analyze macro/Fed events BEFORE calling Gemini API.

MODELS USED:
1. FinBERT (ProsusAI/finbert) - Fed speech sentiment (dovish vs hawkish)
2. BART Zero-Shot (facebook/bart-large-mnli) - News headline classification
3. DistilBERT NER (dslim/bert-base-NER) - Extract entities from Fed statements

SAVES: ~70% of Gemini API calls (only escalate uncertain cases)
"""

from transformers import pipeline
import warnings
warnings.filterwarnings('ignore')


class SentimentFilter:
    def __init__(self):
        """Initialize all models on first use (lazy loading)"""
        self._finbert = None
        self._zero_shot = None
        self._ner = None

    @property
    def finbert(self):
        """FinBERT for Fed/macro sentiment analysis"""
        if self._finbert is None:
            print("Loading FinBERT model (first time only)...")
            self._finbert = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert"
            )
        return self._finbert

    @property
    def zero_shot(self):
        """Zero-shot classifier for news headlines"""
        if self._zero_shot is None:
            print("Loading Zero-Shot model (first time only)...")
            self._zero_shot = pipeline(
                "zero-shot-classification",
                model="facebook/bart-large-mnli"
            )
        return self._zero_shot

    @property
    def ner(self):
        """Named Entity Recognition for parsing statements"""
        if self._ner is None:
            print("Loading NER model (first time only)...")
            self._ner = pipeline(
                "ner",
                model="dslim/bert-base-NER",
                aggregation_strategy="simple"
            )
        return self._ner

    def analyze_fed_statement(self, text):
        """
        Analyze Fed/macro text for dovish (rate cuts) vs hawkish (rate hikes) sentiment.

        Returns:
            dict: {
                'sentiment': 'positive'|'negative'|'neutral',
                'confidence': float (0-1),
                'interpretation': 'dovish'|'hawkish'|'neutral',
                'should_escalate': bool (True if uncertain)
            }
        """
        try:
            result = self.finbert(text[:512])[0]  # FinBERT max 512 tokens

            sentiment = result['label'].lower()
            confidence = result['score']

            # Map FinBERT output to Fed policy interpretation
            interpretation_map = {
                'positive': 'dovish',   # Positive sentiment = dovish = rate cuts likely
                'negative': 'hawkish',  # Negative sentiment = hawkish = rate hikes
                'neutral': 'neutral'
            }

            interpretation = interpretation_map.get(sentiment, 'neutral')

            # Escalate to Gemini if confidence < 80%
            should_escalate = confidence < 0.80

            return {
                'sentiment': sentiment,
                'confidence': confidence,
                'interpretation': interpretation,
                'should_escalate': should_escalate,
                'reasoning': f"FinBERT classified as {sentiment} ({interpretation}) with {confidence:.1%} confidence"
            }

        except Exception as e:
            print(f"FinBERT error: {e}")
            return {
                'sentiment': 'neutral',
                'confidence': 0.0,
                'interpretation': 'neutral',
                'should_escalate': True,  # On error, escalate to Gemini
                'reasoning': f"FinBERT failed: {str(e)}"
            }

    def classify_news_headline(self, headline, labels=["bullish", "bearish", "neutral"]):
        """
        Classify news headline sentiment.

        Args:
            headline: News headline text
            labels: Possible classifications

        Returns:
            dict: {
                'label': str (top prediction),
                'confidence': float,
                'all_scores': dict
            }
        """
        try:
            result = self.zero_shot(headline, labels)

            return {
                'label': result['labels'][0],
                'confidence': result['scores'][0],
                'all_scores': dict(zip(result['labels'], result['scores'])),
                'should_escalate': result['scores'][0] < 0.70
            }

        except Exception as e:
            print(f"Zero-shot error: {e}")
            return {
                'label': 'neutral',
                'confidence': 0.0,
                'all_scores': {},
                'should_escalate': True
            }

    def extract_entities(self, text):
        """
        Extract named entities (people, organizations, numbers) from text.

        Useful for parsing Fed statements like:
        "Jerome Powell announced rates will hold at 5.25%"
        → {'PER': ['Jerome Powell']}
        """
        try:
            entities = self.ner(text)

            # Group by entity type
            grouped = {}
            for entity in entities:
                entity_type = entity['entity_group']
                if entity_type not in grouped:
                    grouped[entity_type] = []
                grouped[entity_type].append(entity['word'])

            return grouped

        except Exception as e:
            print(f"NER error: {e}")
            return {}

    def pre_filter_macro_trade(self, opportunity, recent_news=None):
        """
        Pre-filter a macro trade opportunity before sending to Gemini.

        Args:
            opportunity: Trade dict (from macro_engine.py)
            recent_news: Optional list of recent headlines

        Returns:
            dict: {
                'auto_approve': bool,
                'auto_reject': bool,
                'escalate_to_gemini': bool,
                'reasoning': str
            }
        """

        # If no recent news provided, escalate to Gemini
        if not recent_news:
            return {
                'auto_approve': False,
                'auto_reject': False,
                'escalate_to_gemini': True,
                'reasoning': 'No recent news to analyze, defaulting to AI validation'
            }

        # Analyze most recent Fed-related news
        fed_keywords = ['fed', 'federal reserve', 'powell', 'fomc', 'interest rate']
        fed_news = [
            headline for headline in recent_news
            if any(keyword in headline.lower() for keyword in fed_keywords)
        ]

        if not fed_news:
            # No Fed news = trust the math model
            return {
                'auto_approve': True,
                'auto_reject': False,
                'escalate_to_gemini': False,
                'reasoning': 'No recent Fed news detected, trusting mathematical model'
            }

        # Analyze the most recent Fed headline
        latest_headline = fed_news[0]
        sentiment = self.analyze_fed_statement(latest_headline)

        # Check if sentiment aligns with trade direction
        trade_expects_cut = 'cut' in opportunity.get('action', '').lower()
        sentiment_suggests_cut = sentiment['interpretation'] == 'dovish'

        alignment = trade_expects_cut == sentiment_suggests_cut

        if alignment and sentiment['confidence'] > 0.85:
            # High confidence + alignment = auto-approve
            return {
                'auto_approve': True,
                'auto_reject': False,
                'escalate_to_gemini': False,
                'reasoning': f"FinBERT {sentiment['interpretation']} ({sentiment['confidence']:.1%}) aligns with trade direction"
            }

        elif not alignment and sentiment['confidence'] > 0.85:
            # High confidence + misalignment = escalate (possible value trap)
            return {
                'auto_approve': False,
                'auto_reject': False,
                'escalate_to_gemini': True,
                'reasoning': f"⚠️ FinBERT {sentiment['interpretation']} ({sentiment['confidence']:.1%}) CONFLICTS with trade - escalating to AI"
            }

        else:
            # Low confidence = escalate
            return {
                'auto_approve': False,
                'auto_reject': False,
                'escalate_to_gemini': True,
                'reasoning': f"FinBERT uncertain ({sentiment['confidence']:.1%}) - escalating to AI"
            }


if __name__ == "__main__":
    print("Testing Sentiment Filter...")
    sf = SentimentFilter()

    # Test FinBERT
    result = sf.analyze_fed_statement("The Federal Reserve will maintain accommodative policy")
    print(f"FinBERT: {result}")

    # Test Zero-Shot
    result = sf.classify_news_headline("Bitcoin surges to new high")
    print(f"Zero-Shot: {result}")

    # Test NER
    result = sf.extract_entities("Jerome Powell announced rates at 5.25%")
    print(f"NER: {result}")
