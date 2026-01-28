"""
Thread Analyzer
Email thread intelligence and conversation analysis
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import re

class ThreadAnalyzer:
    """
    Analyzes email conversation threads
    Extracts insights, action items, sentiment, and key points
    """
    
    def __init__(self, db):
        self.db = db
        
        # Sentiment keywords
        self.positive_keywords = [
            'great', 'excellent', 'perfect', 'love', 'interested', 'definitely',
            'yes', 'sounds good', 'excited', 'looking forward', 'helpful',
            'appreciate', 'thank', 'thanks', 'awesome', 'wonderful'
        ]
        
        self.negative_keywords = [
            'no', 'not interested', 'busy', 'maybe later', 'not now',
            'difficult', 'problem', 'issue', 'concerned', 'worry',
            'unfortunately', 'cant', "can't", 'unable', 'wont', "won't"
        ]
        
        self.neutral_keywords = [
            'okay', 'ok', 'sure', 'noted', 'understood', 'got it'
        ]
        
        # Action item indicators
        self.action_indicators = [
            'will', 'going to', 'plan to', 'need to', 'have to', 'must',
            'should', 'can you', 'could you', 'would you', 'please',
            'schedule', 'meeting', 'call', 'follow up', 'send', 'share'
        ]
        
        # Question patterns
        self.question_patterns = [
            r'\?$',  # Ends with question mark
            r'^(what|when|where|who|why|how|which|can|could|would|will|do|does|is|are)',
            r'(tell me|let me know|wondering|curious)'
        ]
    
    async def analyze_thread(self, thread_id: str) -> Dict:
        """
        Comprehensive thread analysis
        
        Args:
            thread_id: Thread ID to analyze
            
        Returns:
            Dictionary with thread analysis
        """
        # Fetch thread messages
        thread = await self.db.threads.find_one({'_id': thread_id})
        if not thread:
            return {'error': 'Thread not found'}
        
        messages = thread.get('messages', [])
        if not messages:
            return {'error': 'No messages in thread'}
        
        # Perform analysis
        summary = self._generate_summary(messages)
        action_items = self.extract_action_items(thread_id, messages)
        sentiment = self._analyze_sentiment(messages)
        key_points = self._extract_key_points(messages)
        questions = self._extract_questions(messages)
        engagement_level = self._calculate_engagement_level(messages)
        conversation_flow = self._analyze_conversation_flow(messages)
        
        return {
            'thread_id': thread_id,
            'message_count': len(messages),
            'summary': summary,
            'action_items': action_items,
            'sentiment': sentiment,
            'key_points': key_points,
            'questions': questions,
            'engagement_level': engagement_level,
            'conversation_flow': conversation_flow,
            'analyzed_at': datetime.now().isoformat()
        }
    
    def _generate_summary(self, messages: List[Dict]) -> str:
        """Generate conversation summary"""
        if not messages:
            return "No messages to summarize"
        
        # Extract key information
        participants = set()
        topics = []
        
        for msg in messages:
            from_person = msg.get('from', 'Unknown')
            participants.add(from_person)
            
            # Extract potential topics (would use NLP in production)
            content = msg.get('content', '')
            if 'meeting' in content.lower():
                topics.append('meeting request')
            if 'demo' in content.lower():
                topics.append('demo')
            if 'pricing' in content.lower():
                topics.append('pricing')
        
        summary = f"Conversation between {', '.join(participants)} over {len(messages)} messages"
        
        if topics:
            summary += f". Discussed: {', '.join(set(topics))}"
        
        # Determine conversation status
        last_message = messages[-1]
        if last_message.get('from') == 'lead':
            summary += ". Awaiting response from sender."
        else:
            summary += ". Awaiting lead response."
        
        return summary
    
    def extract_action_items(self, thread_id: str, messages: List[Dict] = None) -> List[str]:
        """
        Extract action items from thread
        
        Args:
            thread_id: Thread ID (for DB lookup if messages not provided)
            messages: Optional list of messages
            
        Returns:
            List of action item strings
        """
        if messages is None:
            # Would fetch from DB
            return []
        
        action_items = []
        
        for msg in messages:
            content = msg.get('content', '').lower()
            
            # Look for action indicators
            for indicator in self.action_indicators:
                if indicator in content:
                    # Extract sentence containing action
                    sentences = content.split('.')
                    for sentence in sentences:
                        if indicator in sentence:
                            action_items.append(sentence.strip().capitalize())
        
        # Deduplicate and return
        return list(set(action_items))[:10]  # Limit to 10 most relevant
    
    def _analyze_sentiment(self, messages: List[Dict]) -> Dict:
        """Analyze overall sentiment of conversation"""
        positive_count = 0
        negative_count = 0
        neutral_count = 0
        
        lead_sentiments = []
        sender_sentiments = []
        
        for msg in messages:
            content = msg.get('content', '').lower()
            from_person = msg.get('from', '')
            
            # Count sentiment keywords
            msg_positive = sum(1 for kw in self.positive_keywords if kw in content)
            msg_negative = sum(1 for kw in self.negative_keywords if kw in content)
            msg_neutral = sum(1 for kw in self.neutral_keywords if kw in content)
            
            # Determine dominant sentiment
            if msg_positive > msg_negative:
                sentiment = 'positive'
                positive_count += 1
            elif msg_negative > msg_positive:
                sentiment = 'negative'
                negative_count += 1
            else:
                sentiment = 'neutral'
                neutral_count += 1
            
            # Track by participant
            if from_person == 'lead':
                lead_sentiments.append(sentiment)
            else:
                sender_sentiments.append(sentiment)
        
        # Calculate overall sentiment
        total_messages = len(messages)
        overall = 'neutral'
        
        if positive_count > negative_count and positive_count > neutral_count:
            overall = 'positive'
        elif negative_count > positive_count:
            overall = 'negative'
        
        return {
            'overall': overall,
            'positive_messages': positive_count,
            'negative_messages': negative_count,
            'neutral_messages': neutral_count,
            'positive_percentage': (positive_count / total_messages * 100) if total_messages > 0 else 0,
            'lead_sentiment': Counter(lead_sentiments).most_common(1)[0][0] if lead_sentiments else 'unknown',
            'trend': self._detect_sentiment_trend(messages)
        }
    
    def _detect_sentiment_trend(self, messages: List[Dict]) -> str:
        """Detect if sentiment is improving or declining"""
        if len(messages) < 3:
            return 'stable'
        
        # Analyze last 3 messages vs first 3 messages
        early_messages = messages[:3]
        recent_messages = messages[-3:]
        
        early_score = self._calculate_sentiment_score(early_messages)
        recent_score = self._calculate_sentiment_score(recent_messages)
        
        if recent_score > early_score + 0.2:
            return 'improving'
        elif recent_score < early_score - 0.2:
            return 'declining'
        else:
            return 'stable'
    
    def _calculate_sentiment_score(self, messages: List[Dict]) -> float:
        """Calculate numerical sentiment score"""
        score = 0.0
        
        for msg in messages:
            content = msg.get('content', '').lower()
            
            positive = sum(1 for kw in self.positive_keywords if kw in content)
            negative = sum(1 for kw in self.negative_keywords if kw in content)
            
            score += (positive - negative)
        
        return score / len(messages) if messages else 0.0
    
    def _extract_key_points(self, messages: List[Dict]) -> List[str]:
        """Extract key points from conversation"""
        key_points = []
        
        # Look for messages with important keywords
        important_keywords = [
            'pricing', 'cost', 'budget', 'meeting', 'demo', 'call',
            'implementation', 'timeline', 'team', 'decision', 'interested',
            'requirements', 'features', 'integration'
        ]
        
        for msg in messages:
            content = msg.get('content', '')
            
            # Check if message contains important keywords
            for keyword in important_keywords:
                if keyword in content.lower():
                    # Extract sentence with keyword
                    sentences = content.split('.')
                    for sentence in sentences:
                        if keyword in sentence.lower():
                            key_points.append(sentence.strip())
                            break
        
        return list(set(key_points))[:8]  # Return up to 8 unique points
    
    def _extract_questions(self, messages: List[Dict]) -> List[Dict]:
        """Extract questions from conversation"""
        questions = []
        
        for msg in messages:
            content = msg.get('content', '')
            from_person = msg.get('from', 'unknown')
            timestamp = msg.get('timestamp', datetime.now())
            
            # Find sentences ending with ?
            sentences = content.split('.')
            for sentence in sentences:
                if '?' in sentence:
                    questions.append({
                        'question': sentence.strip(),
                        'asked_by': from_person,
                        'timestamp': timestamp,
                        'answered': self._is_question_answered(sentence, messages)
                    })
        
        return questions
    
    def _is_question_answered(self, question: str, messages: List[Dict]) -> bool:
        """Check if question was answered in subsequent messages"""
        # Simplified check - would use NLP in production
        # Look for response indicators in following messages
        return len(messages) > 1  # Placeholder logic
    
    def _calculate_engagement_level(self, messages: List[Dict]) -> Dict:
        """Calculate engagement level of conversation"""
        total_messages = len(messages)
        
        # Count messages by participant
        lead_messages = sum(1 for msg in messages if msg.get('from') == 'lead')
        sender_messages = total_messages - lead_messages
        
        # Calculate response time
        avg_response_time = self._calculate_avg_response_time(messages)
        
        # Determine engagement level
        if lead_messages >= 3 and avg_response_time < 24:
            level = 'high'
        elif lead_messages >= 2 or avg_response_time < 48:
            level = 'medium'
        else:
            level = 'low'
        
        return {
            'level': level,
            'total_messages': total_messages,
            'lead_messages': lead_messages,
            'sender_messages': sender_messages,
            'response_rate': (lead_messages / sender_messages) if sender_messages > 0 else 0,
            'avg_response_time_hours': avg_response_time
        }
    
    def _calculate_avg_response_time(self, messages: List[Dict]) -> float:
        """Calculate average response time in hours"""
        if len(messages) < 2:
            return 0.0
        
        response_times = []
        
        for i in range(1, len(messages)):
            prev_msg = messages[i-1]
            curr_msg = messages[i]
            
            prev_time = prev_msg.get('timestamp')
            curr_time = curr_msg.get('timestamp')
            
            if prev_time and curr_time:
                if isinstance(prev_time, str):
                    prev_time = datetime.fromisoformat(prev_time)
                if isinstance(curr_time, str):
                    curr_time = datetime.fromisoformat(curr_time)
                
                hours_diff = (curr_time - prev_time).total_seconds() / 3600
                response_times.append(hours_diff)
        
        return sum(response_times) / len(response_times) if response_times else 0.0
    
    def _analyze_conversation_flow(self, messages: List[Dict]) -> Dict:
        """Analyze flow and progression of conversation"""
        # Determine conversation stage
        content_combined = ' '.join([msg.get('content', '').lower() for msg in messages])
        
        stage = 'initial_outreach'
        
        if 'meeting' in content_combined or 'call' in content_combined or 'demo' in content_combined:
            stage = 'meeting_discussion'
        elif 'pricing' in content_combined or 'cost' in content_combined:
            stage = 'pricing_discussion'
        elif any(kw in content_combined for kw in ['interested', 'tell me more', 'learn more']):
            stage = 'interest_shown'
        
        # Check if conversation is stuck
        last_message_time = messages[-1].get('timestamp')
        if isinstance(last_message_time, str):
            last_message_time = datetime.fromisoformat(last_message_time)
        
        days_since_last = (datetime.now() - last_message_time).days if last_message_time else 0
        
        is_stuck = days_since_last > 7 and messages[-1].get('from') == 'sender'
        
        return {
            'stage': stage,
            'progression': 'advancing' if len(messages) >= 3 else 'early',
            'is_stuck': is_stuck,
            'days_since_last_message': days_since_last,
            'next_action': self._suggest_next_action(stage, is_stuck, messages)
        }
    
    def _suggest_next_action(self, stage: str, is_stuck: bool, messages: List[Dict]) -> str:
        """Suggest next action based on conversation state"""
        if is_stuck:
            return "Send gentle follow-up or break-up email"
        
        if stage == 'initial_outreach':
            return "Follow up with value-add content"
        elif stage == 'interest_shown':
            return "Offer demo or specific next step"
        elif stage == 'meeting_discussion':
            return "Confirm meeting time and send calendar invite"
        elif stage == 'pricing_discussion':
            return "Provide pricing details and address concerns"
        else:
            return "Continue nurturing relationship"
    
    async def get_thread_summary_for_lead(self, lead_id: str) -> Dict:
        """
        Get summary of all threads for a lead
        
        Args:
            lead_id: Lead ID
            
        Returns:
            Aggregated thread summary
        """
        threads = await self.db.threads.find({
            'lead_id': lead_id
        }).to_list(length=None)
        
        if not threads:
            return {'error': 'No threads found for lead'}
        
        total_messages = 0
        overall_sentiment = []
        all_action_items = []
        
        for thread in threads:
            messages = thread.get('messages', [])
            total_messages += len(messages)
            
            # Analyze each thread
            analysis = await self.analyze_thread(str(thread['_id']))
            overall_sentiment.append(analysis.get('sentiment', {}).get('overall', 'neutral'))
            all_action_items.extend(analysis.get('action_items', []))
        
        return {
            'lead_id': lead_id,
            'total_threads': len(threads),
            'total_messages': total_messages,
            'avg_messages_per_thread': total_messages / len(threads) if threads else 0,
            'overall_sentiment': Counter(overall_sentiment).most_common(1)[0][0] if overall_sentiment else 'neutral',
            'open_action_items': all_action_items,
            'last_interaction': threads[-1].get('messages', [])[-1].get('timestamp') if threads else None
        }


class ThreadAnalyzerService:
    """Service layer for thread analysis"""
    
    def __init__(self, db):
        self.db = db
        self.analyzer = ThreadAnalyzer(db)
    
    async def analyze_all_active_threads(self) -> List[Dict]:
        """Analyze all active conversation threads"""
        threads = await self.db.threads.find({
            'status': 'active'
        }).to_list(length=None)
        
        analyses = []
        
        for thread in threads:
            analysis = await self.analyzer.analyze_thread(str(thread['_id']))
            analyses.append(analysis)
        
        return analyses
    
    async def get_threads_needing_attention(self) -> List[Dict]:
        """Get threads that need immediate attention"""
        threads = await self.db.threads.find({
            'status': 'active'
        }).to_list(length=None)
        
        needs_attention = []
        
        for thread in threads:
            analysis = await self.analyzer.analyze_thread(str(thread['_id']))
            
            # Flag threads that need attention
            if (analysis.get('conversation_flow', {}).get('is_stuck') or
                analysis.get('sentiment', {}).get('trend') == 'declining' or
                len(analysis.get('questions', [])) > 0):
                
                needs_attention.append({
                    'thread_id': str(thread['_id']),
                    'lead_id': thread.get('lead_id'),
                    'reason': self._determine_attention_reason(analysis),
                    'priority': self._calculate_priority(analysis),
                    'analysis': analysis
                })
        
        # Sort by priority
        needs_attention.sort(key=lambda x: x['priority'], reverse=True)
        
        return needs_attention
    
    def _determine_attention_reason(self, analysis: Dict) -> str:
        """Determine why thread needs attention"""
        if analysis.get('conversation_flow', {}).get('is_stuck'):
            return "Conversation stalled"
        elif analysis.get('sentiment', {}).get('trend') == 'declining':
            return "Sentiment declining"
        elif len(analysis.get('questions', [])) > 0:
            return "Unanswered questions"
        else:
            return "Needs follow-up"
    
    def _calculate_priority(self, analysis: Dict) -> int:
        """Calculate priority score for thread"""
        priority = 0
        
        # High engagement = higher priority
        if analysis.get('engagement_level', {}).get('level') == 'high':
            priority += 3
        
        # Positive sentiment but stuck = high priority
        if (analysis.get('sentiment', {}).get('overall') == 'positive' and
            analysis.get('conversation_flow', {}).get('is_stuck')):
            priority += 5
        
        # Declining sentiment = urgent
        if analysis.get('sentiment', {}).get('trend') == 'declining':
            priority += 4
        
        # Unanswered questions = moderate priority
        if len(analysis.get('questions', [])) > 0:
            priority += 2
        
        return priority
