"""
Meeting Booking Predictor
Predicts likelihood of leads booking meetings and optimal timing
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder, StandardScaler
from typing import Dict, List, Optional, Tuple
import joblib
import os
from datetime import datetime, timedelta
from collections import Counter

class MeetingPredictor:
    """
    Machine learning model to predict meeting booking probability
    Analyzes engagement patterns to identify meeting-ready leads
    """
    
    def __init__(self, db, model_path: str = 'models/meeting_predictor.pkl'):
        self.db = db
        self.model_path = model_path
        self.model: Optional[RandomForestClassifier] = None
        self.scaler = StandardScaler()
        self.encoders = {}
        
        # Feature configuration
        self.categorical_features = ['industry', 'seniority', 'company_size', 'lead_source']
        self.numerical_features = [
            'reply_count', 'email_opens', 'email_clicks', 'link_clicks',
            'engagement_score', 'conversation_length', 'days_in_conversation',
            'response_time_avg_hours', 'positive_sentiment_ratio', 
            'question_count', 'cta_click_rate'
        ]
        self.all_features = self.categorical_features + self.numerical_features
        
        # Load or initialize model
        self._load_or_initialize_model()
    
    def _load_or_initialize_model(self):
        """Load existing model or initialize new one"""
        if os.path.exists(self.model_path):
            try:
                self.model = joblib.load(self.model_path)
                print(f"Loaded meeting predictor from {self.model_path}")
            except Exception as e:
                print(f"Error loading model: {e}")
                self._initialize_new_model()
        else:
            self._initialize_new_model()
    
    def _initialize_new_model(self):
        """Initialize new random forest classifier"""
        self.model = RandomForestClassifier(
            n_estimators=150,
            max_depth=10,
            min_samples_split=10,
            min_samples_leaf=5,
            max_features='sqrt',
            random_state=42,
            class_weight='balanced'
        )
        print("Initialized new random forest model for meeting prediction")
    
    def extract_features(self, lead: Dict) -> Dict[str, float]:
        """
        Extract features from lead engagement data
        
        Args:
            lead: Lead dictionary with engagement history
            
        Returns:
            Dictionary of feature values
        """
        features = {}
        
        # Categorical features
        features['industry'] = lead.get('industry', 'unknown')
        features['seniority'] = lead.get('seniority', 'unknown')
        features['company_size'] = lead.get('company_size', 'unknown')
        features['lead_source'] = lead.get('source', 'unknown')
        
        # Basic engagement metrics
        features['reply_count'] = lead.get('previous_replies', 0)
        features['email_opens'] = lead.get('email_opens', 0)
        features['email_clicks'] = lead.get('email_clicks', 0)
        features['link_clicks'] = lead.get('link_clicks', 0)
        
        # Calculated engagement score
        features['engagement_score'] = self._calculate_engagement_score(lead)
        
        # Conversation metrics
        conversation = lead.get('conversation_history', [])
        features['conversation_length'] = len(conversation)
        features['days_in_conversation'] = self._calculate_conversation_duration(conversation)
        features['response_time_avg_hours'] = self._calculate_avg_response_time(conversation)
        
        # Sentiment analysis
        features['positive_sentiment_ratio'] = self._calculate_positive_sentiment(conversation)
        
        # Content analysis
        features['question_count'] = self._count_questions_in_replies(conversation)
        
        # CTA engagement
        features['cta_click_rate'] = self._calculate_cta_click_rate(lead)
        
        return features
    
    def _calculate_engagement_score(self, lead: Dict) -> float:
        """Calculate overall engagement score"""
        score = 0.0
        
        # Weight different engagement types
        score += lead.get('email_opens', 0) * 1.0
        score += lead.get('email_clicks', 0) * 2.5
        score += lead.get('previous_replies', 0) * 5.0
        score += lead.get('link_clicks', 0) * 3.0
        
        return min(score, 100.0)  # Cap at 100
    
    def _calculate_conversation_duration(self, conversation: List[Dict]) -> int:
        """Calculate days between first and last message"""
        if not conversation:
            return 0
        
        dates = []
        for msg in conversation:
            if 'timestamp' in msg:
                if isinstance(msg['timestamp'], str):
                    dates.append(datetime.fromisoformat(msg['timestamp']))
                else:
                    dates.append(msg['timestamp'])
        
        if len(dates) < 2:
            return 0
        
        return (max(dates) - min(dates)).days
    
    def _calculate_avg_response_time(self, conversation: List[Dict]) -> float:
        """Calculate average response time in hours"""
        if len(conversation) < 2:
            return 0.0
        
        response_times = []
        
        for i in range(1, len(conversation)):
            prev_msg = conversation[i-1]
            curr_msg = conversation[i]
            
            if 'timestamp' in prev_msg and 'timestamp' in curr_msg:
                prev_time = prev_msg['timestamp']
                curr_time = curr_msg['timestamp']
                
                if isinstance(prev_time, str):
                    prev_time = datetime.fromisoformat(prev_time)
                if isinstance(curr_time, str):
                    curr_time = datetime.fromisoformat(curr_time)
                
                hours_diff = (curr_time - prev_time).total_seconds() / 3600
                response_times.append(hours_diff)
        
        return np.mean(response_times) if response_times else 0.0
    
    def _calculate_positive_sentiment(self, conversation: List[Dict]) -> float:
        """Calculate ratio of positive sentiment messages"""
        if not conversation:
            return 0.0
        
        positive_keywords = [
            'interested', 'sounds good', 'perfect', 'great', 'excellent',
            'yes', 'definitely', 'absolutely', 'love', 'excited'
        ]
        
        positive_count = 0
        
        for msg in conversation:
            content = msg.get('content', '').lower()
            if any(keyword in content for keyword in positive_keywords):
                positive_count += 1
        
        return positive_count / len(conversation) if conversation else 0.0
    
    def _count_questions_in_replies(self, conversation: List[Dict]) -> int:
        """Count questions in lead's replies"""
        question_count = 0
        
        for msg in conversation:
            if msg.get('from') == 'lead':
                content = msg.get('content', '')
                question_count += content.count('?')
        
        return question_count
    
    def _calculate_cta_click_rate(self, lead: Dict) -> float:
        """Calculate CTA click rate"""
        cta_shown = lead.get('cta_shown', 0)
        cta_clicked = lead.get('cta_clicked', 0)
        
        if cta_shown == 0:
            return 0.0
        
        return cta_clicked / cta_shown
    
    def prepare_features_dataframe(self, features_list: List[Dict]) -> pd.DataFrame:
        """Convert features to encoded DataFrame"""
        df = pd.DataFrame(features_list)
        
        # Encode categorical features
        for cat_feature in self.categorical_features:
            if cat_feature in df.columns:
                if cat_feature not in self.encoders:
                    self.encoders[cat_feature] = LabelEncoder()
                    df[cat_feature] = self.encoders[cat_feature].fit_transform(df[cat_feature].astype(str))
                else:
                    df[cat_feature] = df[cat_feature].astype(str).apply(
                        lambda x: x if x in self.encoders[cat_feature].classes_ else 'unknown'
                    )
                    df[cat_feature] = self.encoders[cat_feature].transform(df[cat_feature])
        
        return df
    
    def predict_meeting_probability(self, lead: Dict) -> float:
        """
        Predict probability that lead will book a meeting
        
        Args:
            lead: Lead dictionary with engagement data
            
        Returns:
            Probability score between 0.0 and 1.0
        """
        if self.model is None:
            # If model not trained, use heuristic
            return self._heuristic_meeting_probability(lead)
        
        # Extract features
        features = self.extract_features(lead)
        
        # Prepare DataFrame
        X = self.prepare_features_dataframe([features])
        
        # Scale numerical features
        X[self.numerical_features] = self.scaler.transform(X[self.numerical_features])
        
        # Predict probability
        probability = self.model.predict_proba(X)[0][1]
        
        return float(probability)
    
    def _heuristic_meeting_probability(self, lead: Dict) -> float:
        """Fallback heuristic when model not available"""
        score = 0.0
        
        # High engagement signals
        if lead.get('previous_replies', 0) >= 2:
            score += 0.3
        if lead.get('email_clicks', 0) >= 3:
            score += 0.2
        if lead.get('link_clicks', 0) >= 2:
            score += 0.2
        
        # Positive conversation signals
        conversation = lead.get('conversation_history', [])
        if len(conversation) >= 3:
            score += 0.15
        
        # Senior decision makers
        if lead.get('seniority') in ['C-Level', 'VP', 'Director']:
            score += 0.15
        
        return min(score, 1.0)
    
    def suggest_meeting_ask_timing(self, lead: Dict) -> Dict:
        """
        Suggest optimal timing for asking to book meeting
        
        Args:
            lead: Lead dictionary
            
        Returns:
            Dictionary with timing recommendation
        """
        probability = self.predict_meeting_probability(lead)
        conversation = lead.get('conversation_history', [])
        reply_count = lead.get('previous_replies', 0)
        
        # Determine readiness level
        if probability >= 0.7:
            readiness = 'ready_now'
            recommendation = 'Ask for meeting in next email'
            wait_days = 0
        elif probability >= 0.5:
            readiness = 'almost_ready'
            recommendation = 'Continue conversation, ask after 1-2 more exchanges'
            wait_days = 1
        elif probability >= 0.3:
            readiness = 'warming_up'
            recommendation = 'Build more rapport, ask after 3-4 more exchanges'
            wait_days = 3
        else:
            readiness = 'not_ready'
            recommendation = 'Focus on value building, not ready for meeting ask'
            wait_days = 7
        
        # Check if already asked
        already_asked = self._check_meeting_already_asked(conversation)
        
        return {
            'readiness': readiness,
            'probability': probability,
            'recommendation': recommendation,
            'suggested_wait_days': wait_days,
            'already_asked': already_asked,
            'reply_count': reply_count,
            'conversation_length': len(conversation),
            'factors': {
                'engagement_level': 'high' if probability > 0.6 else 'medium' if probability > 0.3 else 'low',
                'conversation_depth': 'deep' if len(conversation) >= 5 else 'moderate' if len(conversation) >= 2 else 'shallow',
                'response_rate': 'good' if reply_count >= 2 else 'fair' if reply_count >= 1 else 'poor'
            }
        }
    
    def _check_meeting_already_asked(self, conversation: List[Dict]) -> bool:
        """Check if meeting request was already made"""
        meeting_keywords = ['meeting', 'call', 'schedule', 'calendar', 'zoom', 'available']
        
        for msg in conversation:
            if msg.get('from') == 'sender':
                content = msg.get('content', '').lower()
                if any(keyword in content for keyword in meeting_keywords):
                    return True
        
        return False
    
    def get_meeting_ready_leads(self, leads: List[Dict], threshold: float = 0.6) -> List[Dict]:
        """
        Get leads ready for meeting ask
        
        Args:
            leads: List of lead dictionaries
            threshold: Minimum probability threshold
            
        Returns:
            List of meeting-ready leads with details
        """
        meeting_ready = []
        
        for lead in leads:
            probability = self.predict_meeting_probability(lead)
            
            if probability >= threshold:
                timing = self.suggest_meeting_ask_timing(lead)
                
                meeting_ready.append({
                    'lead_id': str(lead.get('_id', lead.get('id'))),
                    'name': f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
                    'company': lead.get('company', 'N/A'),
                    'title': lead.get('title', ''),
                    'email': lead.get('email', ''),
                    'meeting_probability': probability,
                    'readiness': timing['readiness'],
                    'recommendation': timing['recommendation'],
                    'already_asked': timing['already_asked']
                })
        
        # Sort by probability
        meeting_ready.sort(key=lambda x: x['meeting_probability'], reverse=True)
        
        return meeting_ready
    
    def train(self, training_data: List[Dict], labels: List[int]) -> Dict[str, float]:
        """
        Train the meeting prediction model
        
        Args:
            training_data: List of lead dictionaries
            labels: Binary labels (1 = booked meeting, 0 = no meeting)
            
        Returns:
            Training metrics
        """
        # Extract features
        features_list = [self.extract_features(lead) for lead in training_data]
        
        # Prepare DataFrame
        X = self.prepare_features_dataframe(features_list)
        y = np.array(labels)
        
        # Scale numerical features
        X[self.numerical_features] = self.scaler.fit_transform(X[self.numerical_features])
        
        # Train model
        self.model.fit(X, y)
        
        # Calculate metrics
        train_score = self.model.score(X, y)
        
        # Save model
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        joblib.save(self.model, self.model_path)
        
        return {
            'train_accuracy': train_score,
            'n_samples': len(training_data),
            'n_features': len(self.all_features)
        }


class MeetingPredictionService:
    """Service layer for meeting predictions"""
    
    def __init__(self, db):
        self.db = db
        self.predictor = MeetingPredictor(db)
    
    async def get_meeting_ready_dashboard(self) -> Dict:
        """
        Get dashboard of meeting-ready leads
        
        Returns:
            Dashboard data with segmented leads
        """
        # Fetch engaged leads
        leads = await self.db.leads.find({
            'status': {'$in': ['engaged', 'active']},
            'previous_replies': {'$gte': 1}
        }).to_list(length=None)
        
        ready_now = []
        almost_ready = []
        warming_up = []
        
        for lead in leads:
            probability = self.predictor.predict_meeting_probability(lead)
            timing = self.predictor.suggest_meeting_ask_timing(lead)
            
            lead_info = {
                'lead_id': str(lead['_id']),
                'name': f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
                'company': lead.get('company', 'N/A'),
                'title': lead.get('title', ''),
                'probability': probability,
                'recommendation': timing['recommendation']
            }
            
            if timing['readiness'] == 'ready_now':
                ready_now.append(lead_info)
            elif timing['readiness'] == 'almost_ready':
                almost_ready.append(lead_info)
            elif timing['readiness'] == 'warming_up':
                warming_up.append(lead_info)
        
        return {
            'ready_now': sorted(ready_now, key=lambda x: x['probability'], reverse=True),
            'almost_ready': sorted(almost_ready, key=lambda x: x['probability'], reverse=True),
            'warming_up': sorted(warming_up, key=lambda x: x['probability'], reverse=True),
            'total_leads_analyzed': len(leads),
            'generated_at': datetime.now().isoformat()
        }
