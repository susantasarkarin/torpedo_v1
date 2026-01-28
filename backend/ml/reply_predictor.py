"""
Reply Probability Predictor
AI-driven prediction of email reply likelihood using gradient boosting
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import LabelEncoder, StandardScaler
from typing import Dict, List, Optional, Tuple
import joblib
import os
from datetime import datetime, timedelta
from collections import defaultdict

class ReplyPredictor:
    """
    Machine learning model to predict probability of email reply
    Uses historical data to train gradient boosting classifier
    """
    
    def __init__(self, db, model_path: str = 'models/reply_predictor.pkl'):
        self.db = db
        self.model_path = model_path
        self.model: Optional[GradientBoostingClassifier] = None
        self.scaler = StandardScaler()
        self.encoders = {}
        
        # Feature configuration
        self.categorical_features = ['industry', 'seniority', 'company_size', 'email_domain']
        self.numerical_features = [
            'email_opens', 'email_clicks', 'previous_replies', 
            'days_since_first_contact', 'emails_sent', 'company_employee_count',
            'subject_line_length', 'email_body_length', 'personalization_score'
        ]
        self.all_features = self.categorical_features + self.numerical_features
        
        # Load or initialize model
        self._load_or_initialize_model()
    
    def _load_or_initialize_model(self):
        """Load existing model or initialize new one"""
        if os.path.exists(self.model_path):
            try:
                self.model = joblib.load(self.model_path)
                print(f"Loaded existing model from {self.model_path}")
            except Exception as e:
                print(f"Error loading model: {e}")
                self._initialize_new_model()
        else:
            self._initialize_new_model()
    
    def _initialize_new_model(self):
        """Initialize new gradient boosting classifier"""
        self.model = GradientBoostingClassifier(
            n_estimators=100,
            learning_rate=0.1,
            max_depth=5,
            min_samples_split=20,
            min_samples_leaf=10,
            subsample=0.8,
            random_state=42
        )
        print("Initialized new gradient boosting model")
    
    def extract_features(self, lead: Dict) -> Dict[str, float]:
        """
        Extract features from lead data
        
        Args:
            lead: Lead dictionary with profile and engagement data
            
        Returns:
            Dictionary of feature values
        """
        features = {}
        
        # Categorical features
        features['industry'] = lead.get('industry', 'unknown')
        features['seniority'] = lead.get('seniority', 'unknown')
        features['company_size'] = lead.get('company_size', 'unknown')
        
        # Extract domain from email
        email = lead.get('email', '')
        features['email_domain'] = email.split('@')[-1] if '@' in email else 'unknown'
        
        # Numerical features
        features['email_opens'] = lead.get('email_opens', 0)
        features['email_clicks'] = lead.get('email_clicks', 0)
        features['previous_replies'] = lead.get('previous_replies', 0)
        features['emails_sent'] = lead.get('emails_sent', 0)
        features['company_employee_count'] = lead.get('company_employee_count', 0)
        
        # Calculate days since first contact
        first_contact = lead.get('first_contact_date')
        if first_contact:
            if isinstance(first_contact, str):
                first_contact = datetime.fromisoformat(first_contact)
            features['days_since_first_contact'] = (datetime.now() - first_contact).days
        else:
            features['days_since_first_contact'] = 0
        
        # Email content features
        last_subject = lead.get('last_subject_line', '')
        last_body = lead.get('last_email_body', '')
        features['subject_line_length'] = len(last_subject)
        features['email_body_length'] = len(last_body)
        
        # Personalization score (count of personalized fields)
        features['personalization_score'] = self._calculate_personalization_score(lead)
        
        return features
    
    def _calculate_personalization_score(self, lead: Dict) -> int:
        """Calculate personalization score based on available data"""
        score = 0
        personalized_fields = [
            'first_name', 'last_name', 'company', 'title', 
            'industry', 'recent_news', 'mutual_connection'
        ]
        
        for field in personalized_fields:
            if lead.get(field):
                score += 1
        
        return score
    
    def prepare_features_dataframe(self, features_list: List[Dict]) -> pd.DataFrame:
        """
        Convert list of feature dictionaries to encoded DataFrame
        
        Args:
            features_list: List of feature dictionaries
            
        Returns:
            Encoded and scaled DataFrame
        """
        df = pd.DataFrame(features_list)
        
        # Encode categorical features
        for cat_feature in self.categorical_features:
            if cat_feature in df.columns:
                if cat_feature not in self.encoders:
                    self.encoders[cat_feature] = LabelEncoder()
                    df[cat_feature] = self.encoders[cat_feature].fit_transform(df[cat_feature].astype(str))
                else:
                    # Handle unseen categories
                    df[cat_feature] = df[cat_feature].astype(str).apply(
                        lambda x: x if x in self.encoders[cat_feature].classes_ else 'unknown'
                    )
                    df[cat_feature] = self.encoders[cat_feature].transform(df[cat_feature])
        
        return df
    
    def train(self, training_data: List[Dict], labels: List[int]) -> Dict[str, float]:
        """
        Train the reply prediction model
        
        Args:
            training_data: List of lead dictionaries with features
            labels: List of binary labels (1 = replied, 0 = no reply)
            
        Returns:
            Training metrics dictionary
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
        
        # Calculate training metrics
        train_score = self.model.score(X, y)
        
        # Save model
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        joblib.save(self.model, self.model_path)
        
        return {
            'train_accuracy': train_score,
            'n_samples': len(training_data),
            'n_features': len(self.all_features)
        }
    
    def predict_reply_probability(self, lead: Dict) -> float:
        """
        Predict probability that lead will reply to email
        
        Args:
            lead: Lead dictionary with profile and engagement data
            
        Returns:
            Probability score between 0.0 and 1.0
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        # Extract features
        features = self.extract_features(lead)
        
        # Prepare DataFrame
        X = self.prepare_features_dataframe([features])
        
        # Scale numerical features
        X[self.numerical_features] = self.scaler.transform(X[self.numerical_features])
        
        # Predict probability
        probability = self.model.predict_proba(X)[0][1]  # Probability of class 1 (reply)
        
        return float(probability)
    
    def get_prediction_factors(self, lead: Dict) -> Dict[str, float]:
        """
        Get feature importance for prediction explanation
        
        Args:
            lead: Lead dictionary
            
        Returns:
            Dictionary of feature importance scores
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        # Get feature importances from model
        feature_importance = self.model.feature_importances_
        
        # Create dictionary of feature names and importances
        importance_dict = {}
        for i, feature in enumerate(self.all_features):
            if i < len(feature_importance):
                importance_dict[feature] = float(feature_importance[i])
        
        # Sort by importance
        sorted_importance = dict(sorted(
            importance_dict.items(), 
            key=lambda x: x[1], 
            reverse=True
        ))
        
        return sorted_importance
    
    def batch_predict(self, leads: List[Dict]) -> List[Tuple[str, float]]:
        """
        Predict reply probability for multiple leads
        
        Args:
            leads: List of lead dictionaries
            
        Returns:
            List of tuples (lead_id, probability)
        """
        predictions = []
        
        for lead in leads:
            lead_id = lead.get('id', lead.get('_id', 'unknown'))
            probability = self.predict_reply_probability(lead)
            predictions.append((str(lead_id), probability))
        
        return predictions
    
    def get_model_performance(self) -> Dict[str, any]:
        """
        Get model performance metrics
        
        Returns:
            Dictionary with model statistics
        """
        if self.model is None:
            return {'status': 'not_trained'}
        
        return {
            'status': 'trained',
            'n_estimators': self.model.n_estimators,
            'learning_rate': self.model.learning_rate,
            'max_depth': self.model.max_depth,
            'n_features': len(self.all_features),
            'categorical_features': self.categorical_features,
            'numerical_features': self.numerical_features
        }
    
    async def fetch_training_data(self, days_back: int = 90) -> Tuple[List[Dict], List[int]]:
        """
        Fetch historical lead data for training
        
        Args:
            days_back: Number of days to look back for data
            
        Returns:
            Tuple of (training_data, labels)
        """
        cutoff_date = datetime.now() - timedelta(days=days_back)
        
        # Fetch leads with engagement data
        leads = await self.db.leads.find({
            'created_at': {'$gte': cutoff_date},
            'emails_sent': {'$gt': 0}
        }).to_list(length=None)
        
        training_data = []
        labels = []
        
        for lead in leads:
            training_data.append(lead)
            # Label: 1 if lead has replied, 0 otherwise
            labels.append(1 if lead.get('previous_replies', 0) > 0 else 0)
        
        return training_data, labels
    
    async def retrain_model(self, days_back: int = 90) -> Dict[str, any]:
        """
        Retrain model with latest data
        
        Args:
            days_back: Number of days to look back for training data
            
        Returns:
            Training results
        """
        print(f"Fetching training data from last {days_back} days...")
        training_data, labels = await self.fetch_training_data(days_back)
        
        if len(training_data) < 50:
            return {
                'status': 'insufficient_data',
                'n_samples': len(training_data),
                'message': 'Need at least 50 samples for training'
            }
        
        print(f"Training model with {len(training_data)} samples...")
        metrics = self.train(training_data, labels)
        
        return {
            'status': 'success',
            **metrics,
            'trained_at': datetime.now().isoformat()
        }


class ReplyPredictionService:
    """Service layer for reply predictions"""
    
    def __init__(self, db):
        self.db = db
        self.predictor = ReplyPredictor(db)
    
    async def predict_for_campaign(self, campaign_id: str) -> List[Dict]:
        """
        Predict reply probability for all leads in campaign
        
        Args:
            campaign_id: Campaign ID
            
        Returns:
            List of predictions with lead details
        """
        # Fetch campaign leads
        leads = await self.db.leads.find({
            'campaign_id': campaign_id,
            'status': {'$in': ['active', 'engaged']}
        }).to_list(length=None)
        
        predictions = []
        
        for lead in leads:
            probability = self.predictor.predict_reply_probability(lead)
            factors = self.predictor.get_prediction_factors(lead)
            
            predictions.append({
                'lead_id': str(lead['_id']),
                'name': f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
                'company': lead.get('company', 'N/A'),
                'email': lead.get('email', ''),
                'reply_probability': probability,
                'confidence': 'high' if probability > 0.7 else 'medium' if probability > 0.4 else 'low',
                'top_factors': dict(list(factors.items())[:5])
            })
        
        # Sort by probability (highest first)
        predictions.sort(key=lambda x: x['reply_probability'], reverse=True)
        
        return predictions
    
    async def get_hot_leads(self, limit: int = 20, min_probability: float = 0.6) -> List[Dict]:
        """
        Get leads with highest reply probability
        
        Args:
            limit: Maximum number of leads to return
            min_probability: Minimum probability threshold
            
        Returns:
            List of hot leads
        """
        # Fetch active leads
        leads = await self.db.leads.find({
            'status': {'$in': ['active', 'engaged']},
            'emails_sent': {'$gt': 0}
        }).to_list(length=None)
        
        hot_leads = []
        
        for lead in leads:
            probability = self.predictor.predict_reply_probability(lead)
            
            if probability >= min_probability:
                hot_leads.append({
                    'lead_id': str(lead['_id']),
                    'name': f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
                    'company': lead.get('company', 'N/A'),
                    'title': lead.get('title', ''),
                    'email': lead.get('email', ''),
                    'reply_probability': probability,
                    'last_contact': lead.get('last_contact_date'),
                    'emails_sent': lead.get('emails_sent', 0),
                    'email_opens': lead.get('email_opens', 0)
                })
        
        # Sort by probability and limit
        hot_leads.sort(key=lambda x: x['reply_probability'], reverse=True)
        
        return hot_leads[:limit]
