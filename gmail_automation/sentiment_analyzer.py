"""
Sentiment Analysis Module

Provides AI-based sentiment analysis for email content.
Determines tone, emotion, urgency, and context of emails.

Supports multiple analysis backends:
- TextBlob (default, no API required)
- OpenAI GPT (optional, requires API key)
- Custom analyzers

Usage:
    from gmail_automation.sentiment_analyzer import SentimentAnalyzer
    
    analyzer = SentimentAnalyzer()
    result = analyzer.analyze(email)
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
from datetime import datetime
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Sentiment(Enum):
    """Overall sentiment classification."""
    VERY_POSITIVE = "very_positive"
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    VERY_NEGATIVE = "very_negative"


class Tone(Enum):
    """Email tone classification."""
    PROFESSIONAL = "professional"
    CASUAL = "casual"
    FORMAL = "formal"
    FRIENDLY = "friendly"
    URGENT = "urgent"
    FRUSTRATED = "frustrated"
    APOLOGETIC = "apologetic"
    APPRECIATIVE = "appreciative"
    NEUTRAL = "neutral"


class Urgency(Enum):
    """Urgency level."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class Intent(Enum):
    """Detected email intent."""
    REQUEST = "request"
    INQUIRY = "inquiry"
    COMPLAINT = "complaint"
    FEEDBACK = "feedback"
    APPRECIATION = "appreciation"
    INFORMATION = "information"
    FOLLOW_UP = "follow_up"
    INTRODUCTION = "introduction"
    NEGOTIATION = "negotiation"
    CONFIRMATION = "confirmation"
    UNKNOWN = "unknown"


@dataclass
class SentimentResult:
    """
    Result of sentiment analysis.
    
    Attributes:
        email_id: Email message ID
        sentiment: Overall sentiment classification
        sentiment_score: Sentiment polarity (-1 to 1)
        subjectivity: How subjective the content is (0 to 1)
        tone: Detected tone of the email
        urgency: Urgency level
        intent: Detected intent
        emotions: Detected emotions with confidence scores
        key_phrases: Important phrases extracted
        action_items: Detected action items
        summary: Brief summary of the email
        language: Detected language
        confidence: Overall confidence in analysis
    """
    email_id: str
    sentiment: Sentiment = Sentiment.NEUTRAL
    sentiment_score: float = 0.0
    subjectivity: float = 0.0
    tone: Tone = Tone.NEUTRAL
    urgency: Urgency = Urgency.NONE
    intent: Intent = Intent.UNKNOWN
    emotions: Dict[str, float] = field(default_factory=dict)
    key_phrases: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    summary: str = ""
    language: str = "en"
    confidence: float = 0.0
    analyzed_at: datetime = field(default_factory=datetime.now)
    raw_scores: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'email_id': self.email_id,
            'sentiment': self.sentiment.value,
            'sentiment_score': self.sentiment_score,
            'subjectivity': self.subjectivity,
            'tone': self.tone.value,
            'urgency': self.urgency.value,
            'intent': self.intent.value,
            'emotions': self.emotions,
            'key_phrases': self.key_phrases,
            'action_items': self.action_items,
            'summary': self.summary,
            'language': self.language,
            'confidence': self.confidence,
            'analyzed_at': self.analyzed_at.isoformat()
        }
    
    def is_positive(self) -> bool:
        """Check if sentiment is positive."""
        return self.sentiment in [Sentiment.POSITIVE, Sentiment.VERY_POSITIVE]
    
    def is_negative(self) -> bool:
        """Check if sentiment is negative."""
        return self.sentiment in [Sentiment.NEGATIVE, Sentiment.VERY_NEGATIVE]
    
    def requires_attention(self) -> bool:
        """Check if email requires immediate attention."""
        return (
            self.urgency in [Urgency.CRITICAL, Urgency.HIGH] or
            self.sentiment == Sentiment.VERY_NEGATIVE or
            self.intent == Intent.COMPLAINT
        )


class TextBlobAnalyzer:
    """
    Sentiment analyzer using TextBlob library.
    No API required, works offline.
    """
    
    def __init__(self):
        """Initialize TextBlob analyzer."""
        try:
            from textblob import TextBlob
            self.TextBlob = TextBlob
            self.available = True
        except ImportError:
            logger.warning("TextBlob not installed. Run: pip install textblob")
            self.available = False
    
    def analyze(self, text: str) -> Tuple[float, float]:
        """
        Analyze text sentiment.
        
        Args:
            text: Text to analyze
            
        Returns:
            Tuple of (polarity, subjectivity)
            polarity: -1 (negative) to 1 (positive)
            subjectivity: 0 (objective) to 1 (subjective)
        """
        if not self.available:
            return 0.0, 0.0
        
        try:
            blob = self.TextBlob(text)
            return blob.sentiment.polarity, blob.sentiment.subjectivity
        except Exception as e:
            logger.error(f"TextBlob analysis failed: {e}")
            return 0.0, 0.0


class OpenAIAnalyzer:
    """
    Advanced sentiment analyzer using OpenAI GPT.
    COST CONTROL: Uses gpt-4o-mini by default with strict token limits.
    Requires OPENAI_API_KEY environment variable.
    """
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        """
        Initialize OpenAI analyzer.
        COST CONTROL: Changed default model from gpt-3.5-turbo to gpt-4o-mini (cheaper).
        
        Args:
            api_key: OpenAI API key (uses env var if not provided)
            model: OpenAI model to use (default: gpt-4o-mini for cost control)
        """
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        self.model = model
        self.available = bool(self.api_key)
        self._client = None
        
        # COST CONTROL: Check kill switch
        if os.getenv("DISABLE_OPENAI_CALLS", "").lower() in ("true", "1", "yes"):
            self.available = False
            logger.info("OpenAI calls disabled via DISABLE_OPENAI_CALLS")
            return
        
        if self.available:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
            except ImportError:
                logger.warning("OpenAI package not installed. Run: pip install openai")
                self.available = False
    
    def analyze(self, text: str) -> Dict[str, Any]:
        """
        Perform sentiment analysis using GPT.
        COST CONTROL: Optimized prompt and reduced max_tokens.
        
        Args:
            text: Text to analyze
            
        Returns:
            Dictionary with analysis results
        """
        if not self.available or not self._client:
            return {}
        
        # COST CONTROL: Optimized prompt from ~200 tokens to ~80 tokens
        prompt = f"""Analyze email sentiment. Return JSON:
{{"sentiment":"very_positive|positive|neutral|negative|very_negative","sentiment_score":-1.0 to 1.0,"tone":"professional|casual|formal|friendly|urgent|frustrated|apologetic|appreciative|neutral","urgency":"critical|high|medium|low|none","intent":"request|inquiry|complaint|feedback|appreciation|information|follow_up|introduction|negotiation|confirmation|unknown","key_phrases":["phrase1","phrase2"],"summary":"1-2 sentences"}}

Email:
{text[:1000]}"""  # COST CONTROL: Reduced from 2000 to 1000 chars

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Email sentiment analyzer. JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=200  # COST CONTROL: Reduced from 500
            )
            
            import json
            content = response.choices[0].message.content
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                return json.loads(json_match.group())
            return {}
            
        except Exception as e:
            logger.error(f"OpenAI analysis failed: {e}")
            return {}


class PatternAnalyzer:
    """
    Rule-based pattern analyzer for detecting tone, urgency, and intent.
    No external dependencies required.
    """
    
    # Urgency patterns
    URGENCY_PATTERNS = {
        Urgency.CRITICAL: [
            r'\b(emergency|critical|immediately|now|asap)\b',
            r'\b(drop everything|urgent matter)\b',
            r'!!+',
        ],
        Urgency.HIGH: [
            r'\b(urgent|priority|time.?sensitive|deadline)\b',
            r'\b(by (today|tomorrow|end of day|eod))\b',
            r'\b(need|require)\s+(this\s+)?(urgently|immediately)\b',
        ],
        Urgency.MEDIUM: [
            r'\b(soon|when possible|at your earliest)\b',
            r'\b(this week|next few days)\b',
        ],
        Urgency.LOW: [
            r'\b(when you have time|no rush|whenever)\b',
            r'\b(fyi|for your information)\b',
        ]
    }
    
    # Intent patterns
    INTENT_PATTERNS = {
        Intent.REQUEST: [
            r'\b(please|kindly|could you|can you|would you)\b',
            r'\b(request|asking|need you to)\b',
            r'\?$',
        ],
        Intent.INQUIRY: [
            r'\b(wondering|curious|question|inquire|asking about)\b',
            r'\b(what|when|where|why|how|which)\b.*\?',
        ],
        Intent.COMPLAINT: [
            r'\b(disappointed|frustrated|unacceptable|issue|problem)\b',
            r'\b(not satisfied|unhappy|concerned|upset)\b',
            r'\b(complaint|complain|failing)\b',
        ],
        Intent.FEEDBACK: [
            r'\b(feedback|suggestion|thoughts|opinion)\b',
            r'\b(recommend|propose|idea)\b',
        ],
        Intent.APPRECIATION: [
            r'\b(thank|thanks|grateful|appreciate|well done)\b',
            r'\b(great job|excellent|amazing|awesome)\b',
        ],
        Intent.FOLLOW_UP: [
            r'\b(follow.?up|following up|checking in)\b',
            r'\b(any update|status|progress)\b',
            r'\b(circling back|touching base)\b',
        ],
        Intent.INTRODUCTION: [
            r'\b(introduce|introducing|meet|new to)\b',
            r'\b(reaching out|connecting)\b',
        ],
        Intent.CONFIRMATION: [
            r'\b(confirm|confirming|acknowledge|received)\b',
            r'\b(yes|agreed|approved|accepted)\b',
        ]
    }
    
    # Tone indicators
    TONE_PATTERNS = {
        Tone.FORMAL: [
            r'\b(dear|sincerely|regards|respectfully)\b',
            r'\b(herewith|hereby|pursuant|aforementioned)\b',
        ],
        Tone.CASUAL: [
            r'\b(hey|hi|yo|sup)\b',
            r'\b(gonna|wanna|gotta|lol|haha)\b',
            r':\)|;\)|:D|:P',
        ],
        Tone.FRIENDLY: [
            r'\b(hope you\'?re? (doing )?well|good to hear)\b',
            r'\b(looking forward|excited|happy to)\b',
        ],
        Tone.URGENT: [
            r'\b(urgent|asap|immediately|now|critical)\b',
            r'!!!',
        ],
        Tone.FRUSTRATED: [
            r'\b(frustrated|annoyed|disappointed|unacceptable)\b',
            r'\b(again|still|yet another)\b',
        ],
        Tone.APOLOGETIC: [
            r'\b(sorry|apologize|apologies|my bad)\b',
            r'\b(regret|unfortunately|mistake)\b',
        ],
        Tone.APPRECIATIVE: [
            r'\b(thank|thanks|grateful|appreciate)\b',
            r'\b(wonderful|excellent|great|awesome)\b',
        ]
    }
    
    # Emotion keywords
    EMOTION_KEYWORDS = {
        'joy': ['happy', 'glad', 'excited', 'thrilled', 'delighted', 'pleased', 'wonderful'],
        'anger': ['angry', 'frustrated', 'annoyed', 'upset', 'furious', 'outraged'],
        'fear': ['worried', 'concerned', 'anxious', 'afraid', 'nervous', 'scared'],
        'sadness': ['sad', 'disappointed', 'sorry', 'regret', 'unfortunate'],
        'surprise': ['surprised', 'shocked', 'amazed', 'unexpected', 'astonished'],
        'trust': ['trust', 'confident', 'reliable', 'assured', 'believe'],
        'anticipation': ['looking forward', 'excited about', 'can\'t wait', 'eager']
    }
    
    def detect_urgency(self, text: str) -> Tuple[Urgency, float]:
        """
        Detect urgency level in text.
        
        Returns:
            Tuple of (urgency_level, confidence)
        """
        text_lower = text.lower()
        
        for urgency, patterns in self.URGENCY_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    return urgency, 0.8
        
        return Urgency.NONE, 1.0
    
    def detect_intent(self, text: str) -> Tuple[Intent, float]:
        """
        Detect primary intent of the email.
        
        Returns:
            Tuple of (intent, confidence)
        """
        text_lower = text.lower()
        intent_scores: Dict[Intent, int] = {}
        
        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                matches = len(re.findall(pattern, text_lower, re.IGNORECASE))
                intent_scores[intent] = intent_scores.get(intent, 0) + matches
        
        if intent_scores:
            best_intent = max(intent_scores.keys(), key=lambda k: intent_scores[k])
            if intent_scores[best_intent] > 0:
                confidence = min(intent_scores[best_intent] * 0.2, 0.9)
                return best_intent, confidence
        
        return Intent.UNKNOWN, 0.0
    
    def detect_tone(self, text: str) -> Tuple[Tone, float]:
        """
        Detect tone of the email.
        
        Returns:
            Tuple of (tone, confidence)
        """
        text_lower = text.lower()
        tone_scores: Dict[Tone, int] = {}
        
        for tone, patterns in self.TONE_PATTERNS.items():
            for pattern in patterns:
                matches = len(re.findall(pattern, text_lower, re.IGNORECASE))
                tone_scores[tone] = tone_scores.get(tone, 0) + matches
        
        if tone_scores:
            best_tone = max(tone_scores.keys(), key=lambda k: tone_scores[k])
            if tone_scores[best_tone] > 0:
                confidence = min(tone_scores[best_tone] * 0.25, 0.85)
                return best_tone, confidence
        
        # Default to professional if formal elements present
        if re.search(r'\b(dear|regards|sincerely)\b', text_lower):
            return Tone.PROFESSIONAL, 0.6
        
        return Tone.NEUTRAL, 0.5
    
    def detect_emotions(self, text: str) -> Dict[str, float]:
        """
        Detect emotions in text.
        
        Returns:
            Dictionary of emotion names to confidence scores
        """
        text_lower = text.lower()
        emotions: Dict[str, float] = {}
        
        for emotion, keywords in self.EMOTION_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw in text_lower)
            if count > 0:
                emotions[emotion] = min(count * 0.3, 0.9)
        
        return emotions
    
    def extract_action_items(self, text: str) -> List[str]:
        """
        Extract action items from text.
        
        Returns:
            List of action item strings
        """
        action_patterns = [
            r'(?:please|kindly|could you|can you)\s+([^.!?\n]+[.!?]?)',
            r'(?:need you to|would like you to|require you to)\s+([^.!?\n]+[.!?]?)',
            r'(?:action required|to.?do|next steps?)[:]\s*([^.!?\n]+[.!?]?)',
        ]
        
        actions = []
        for pattern in action_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            actions.extend([m.strip() for m in matches if len(m.strip()) > 10])
        
        return actions[:5]  # Limit to 5 action items
    
    def extract_key_phrases(self, text: str) -> List[str]:
        """
        Extract key phrases from text.
        
        Returns:
            List of key phrase strings
        """
        # Simple extraction based on capitalization and quotes
        patterns = [
            r'"([^"]+)"',  # Quoted text
            r"'([^']+)'",  # Single quoted
            r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b',  # Title case phrases
        ]
        
        phrases = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            phrases.extend([m.strip() for m in matches if 3 < len(m.strip()) < 50])
        
        # Also extract noun phrases (simple approach)
        sentences = text.split('.')
        for sentence in sentences[:5]:
            words = sentence.strip().split()
            if 3 <= len(words) <= 8:
                phrases.append(' '.join(words))
        
        return list(set(phrases))[:5]


class SentimentAnalyzer:
    """
    Main sentiment analyzer that combines multiple analysis methods.
    
    Supports TextBlob (offline) and OpenAI (advanced) analysis.
    """
    
    def __init__(
        self,
        use_openai: bool = False,
        openai_api_key: Optional[str] = None,
        openai_model: str = "gpt-3.5-turbo"
    ):
        """
        Initialize sentiment analyzer.
        
        Args:
            use_openai: Whether to use OpenAI for analysis
            openai_api_key: OpenAI API key
            openai_model: OpenAI model to use
        """
        self.textblob = TextBlobAnalyzer()
        self.patterns = PatternAnalyzer()
        
        self.use_openai = use_openai
        self.openai: Optional[OpenAIAnalyzer] = None
        
        if use_openai:
            self.openai = OpenAIAnalyzer(openai_api_key, openai_model)
            if not self.openai.available:
                logger.warning("OpenAI not available, falling back to TextBlob")
                self.use_openai = False
    
    def analyze(self, email) -> SentimentResult:
        """
        Perform comprehensive sentiment analysis on an email.
        
        Args:
            email: Email object to analyze
            
        Returns:
            SentimentResult with full analysis
        """
        # Get text content
        text = self._get_email_text(email)
        
        if not text:
            return SentimentResult(
                email_id=getattr(email, 'id', 'unknown'),
                confidence=0.0
            )
        
        # Use OpenAI if available and enabled
        if self.use_openai and self.openai and self.openai.available:
            return self._analyze_with_openai(email, text)
        
        # Fall back to TextBlob + Pattern analysis
        return self._analyze_with_textblob(email, text)
    
    def _get_email_text(self, email) -> str:
        """Extract text content from email."""
        if hasattr(email, 'get_plain_body'):
            text = email.get_plain_body()
        elif hasattr(email, 'body_text'):
            text = email.body_text or email.snippet
        elif isinstance(email, str):
            text = email
        else:
            text = str(email)
        
        return text.strip()
    
    def _analyze_with_textblob(self, email, text: str) -> SentimentResult:
        """
        Analyze using TextBlob and pattern matching.
        
        Args:
            email: Email object
            text: Email text content
            
        Returns:
            SentimentResult
        """
        email_id = getattr(email, 'id', 'unknown')
        
        # TextBlob sentiment
        polarity, subjectivity = self.textblob.analyze(text)
        
        # Classify sentiment
        sentiment = self._classify_sentiment(polarity)
        
        # Pattern-based analysis
        urgency, _ = self.patterns.detect_urgency(text)
        intent, _ = self.patterns.detect_intent(text)
        tone, _ = self.patterns.detect_tone(text)
        emotions = self.patterns.detect_emotions(text)
        action_items = self.patterns.extract_action_items(text)
        key_phrases = self.patterns.extract_key_phrases(text)
        
        # Generate summary (simple extraction)
        summary = self._generate_simple_summary(text)
        
        # Calculate confidence
        confidence = 0.7 if self.textblob.available else 0.5
        
        return SentimentResult(
            email_id=email_id,
            sentiment=sentiment,
            sentiment_score=polarity,
            subjectivity=subjectivity,
            tone=tone,
            urgency=urgency,
            intent=intent,
            emotions=emotions,
            key_phrases=key_phrases,
            action_items=action_items,
            summary=summary,
            confidence=confidence,
            raw_scores={
                'polarity': polarity,
                'subjectivity': subjectivity
            }
        )
    
    def _analyze_with_openai(self, email, text: str) -> SentimentResult:
        """
        Analyze using OpenAI GPT.
        
        Args:
            email: Email object
            text: Email text content
            
        Returns:
            SentimentResult
        """
        email_id = getattr(email, 'id', 'unknown')
        
        result = self.openai.analyze(text)
        
        if not result:
            # Fall back to TextBlob
            return self._analyze_with_textblob(email, text)
        
        try:
            sentiment = Sentiment(result.get('sentiment', 'neutral'))
        except ValueError:
            sentiment = Sentiment.NEUTRAL
        
        try:
            tone = Tone(result.get('tone', 'neutral'))
        except ValueError:
            tone = Tone.NEUTRAL
        
        try:
            urgency = Urgency(result.get('urgency', 'none'))
        except ValueError:
            urgency = Urgency.NONE
        
        try:
            intent = Intent(result.get('intent', 'unknown'))
        except ValueError:
            intent = Intent.UNKNOWN
        
        return SentimentResult(
            email_id=email_id,
            sentiment=sentiment,
            sentiment_score=result.get('sentiment_score', 0.0),
            subjectivity=0.5,  # Not provided by GPT
            tone=tone,
            urgency=urgency,
            intent=intent,
            emotions=result.get('emotions', {}),
            key_phrases=result.get('key_phrases', []),
            action_items=result.get('action_items', []),
            summary=result.get('summary', ''),
            confidence=0.85,
            raw_scores=result
        )
    
    def _classify_sentiment(self, polarity: float) -> Sentiment:
        """Classify polarity score into sentiment category."""
        if polarity >= 0.5:
            return Sentiment.VERY_POSITIVE
        elif polarity >= 0.1:
            return Sentiment.POSITIVE
        elif polarity <= -0.5:
            return Sentiment.VERY_NEGATIVE
        elif polarity <= -0.1:
            return Sentiment.NEGATIVE
        else:
            return Sentiment.NEUTRAL
    
    def _generate_simple_summary(self, text: str, max_length: int = 150) -> str:
        """Generate a simple summary by extracting the first meaningful sentences."""
        # Clean and split into sentences
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
        
        if not sentences:
            return text[:max_length] if len(text) > max_length else text
        
        summary = sentences[0]
        if len(sentences) > 1 and len(summary) < max_length // 2:
            summary += ". " + sentences[1]
        
        if len(summary) > max_length:
            summary = summary[:max_length-3] + "..."
        
        return summary
    
    def analyze_batch(self, emails: List) -> List[SentimentResult]:
        """
        Analyze multiple emails.
        
        Args:
            emails: List of Email objects
            
        Returns:
            List of SentimentResult objects
        """
        results = []
        for email in emails:
            try:
                result = self.analyze(email)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to analyze email: {e}")
                results.append(SentimentResult(
                    email_id=getattr(email, 'id', 'unknown'),
                    confidence=0.0
                ))
        return results
    
    def get_sentiment_summary(
        self, 
        results: List[SentimentResult]
    ) -> Dict[str, Any]:
        """
        Get summary statistics for analyzed emails.
        
        Args:
            results: List of SentimentResult objects
            
        Returns:
            Summary statistics dictionary
        """
        if not results:
            return {}
        
        summary = {
            'total': len(results),
            'sentiment_distribution': {},
            'average_sentiment_score': 0.0,
            'average_subjectivity': 0.0,
            'urgency_distribution': {},
            'intent_distribution': {},
            'tone_distribution': {},
            'requires_attention': 0,
            'top_emotions': {},
            'common_action_items': []
        }
        
        total_score = 0.0
        total_subjectivity = 0.0
        all_emotions: Dict[str, float] = {}
        all_actions: List[str] = []
        
        for result in results:
            # Count sentiments
            s = result.sentiment.value
            summary['sentiment_distribution'][s] = \
                summary['sentiment_distribution'].get(s, 0) + 1
            
            # Count urgency
            u = result.urgency.value
            summary['urgency_distribution'][u] = \
                summary['urgency_distribution'].get(u, 0) + 1
            
            # Count intents
            i = result.intent.value
            summary['intent_distribution'][i] = \
                summary['intent_distribution'].get(i, 0) + 1
            
            # Count tones
            t = result.tone.value
            summary['tone_distribution'][t] = \
                summary['tone_distribution'].get(t, 0) + 1
            
            # Sum scores
            total_score += result.sentiment_score
            total_subjectivity += result.subjectivity
            
            # Count attention needed
            if result.requires_attention():
                summary['requires_attention'] += 1
            
            # Aggregate emotions
            for emotion, score in result.emotions.items():
                all_emotions[emotion] = all_emotions.get(emotion, 0) + score
            
            # Collect action items
            all_actions.extend(result.action_items)
        
        # Calculate averages
        summary['average_sentiment_score'] = total_score / len(results)
        summary['average_subjectivity'] = total_subjectivity / len(results)
        
        # Top emotions
        if all_emotions:
            sorted_emotions = sorted(
                all_emotions.items(), 
                key=lambda x: x[1], 
                reverse=True
            )
            summary['top_emotions'] = dict(sorted_emotions[:5])
        
        # Common action items (deduplicated)
        summary['common_action_items'] = list(set(all_actions))[:10]
        
        return summary


def analyze_text(text: str, use_openai: bool = False) -> SentimentResult:
    """
    Convenience function to analyze text directly.
    
    Args:
        text: Text to analyze
        use_openai: Whether to use OpenAI
        
    Returns:
        SentimentResult
    """
    analyzer = SentimentAnalyzer(use_openai=use_openai)
    return analyzer.analyze(text)


if __name__ == "__main__":
    # Example usage
    sample_email = """
    Hi John,
    
    I hope this email finds you well. I'm writing to follow up on our 
    previous discussion about the project deadline.
    
    I'm quite concerned that we haven't received the updated requirements 
    yet. Could you please send them by end of day tomorrow? This is 
    becoming urgent as the client is expecting our proposal next week.
    
    Thank you for your help with this matter.
    
    Best regards,
    Sarah
    """
    
    analyzer = SentimentAnalyzer()
    result = analyzer.analyze(sample_email)
    
    print(f"Sentiment: {result.sentiment.value} (score: {result.sentiment_score:.2f})")
    print(f"Tone: {result.tone.value}")
    print(f"Urgency: {result.urgency.value}")
    print(f"Intent: {result.intent.value}")
    print(f"Emotions: {result.emotions}")
    print(f"Action Items: {result.action_items}")
    print(f"Summary: {result.summary}")
