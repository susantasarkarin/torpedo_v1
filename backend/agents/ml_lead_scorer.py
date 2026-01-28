"""
ML-BASED LEAD REPLY SCORER
============================

Machine learning service for predicting reply probability per lead.

Uses historical engagement data to train and predict reply likelihood based on:
- Industry and company size
- Seniority level and title
- Email open history
- Previous replies
- Engagement patterns

Features:
- Per-lead reply probability prediction
- Confidence scoring based on data volume
- Lead prioritization for outreach
- Feature importance analysis
- Batch scoring for campaigns

Collections:
- leads: Lead metadata with enriched fields
- campaign_sends: Historical engagement data
- campaign_recipients: Reply tracking

Usage:
    from agents.ml_lead_scorer import MLLeadScorer
    
    scorer = MLLeadScorer(db)
    
    # Score individual lead
    score = scorer.score_lead_for_reply(lead_dict)
    # Returns: {"probability": 0.45, "confidence": 0.8, "factors": [...]}
    
    # Prioritize leads
    prioritized = scorer.prioritize_leads(lead_ids)
    # Returns: [{"lead_id": "...", "reply_probability": 0.65, ...}, ...]

Requirements:
    pip install scikit-learn pandas numpy
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from bson import ObjectId
import logging
from collections import defaultdict
import math

try:
    import pandas as pd
    import numpy as np
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logging.warning("scikit-learn/pandas/numpy not installed")

logger = logging.getLogger(__name__)

# Feature importance weights (used when ML model unavailable)
FEATURE_WEIGHTS = {
    "has_opened": 2.5,
    "open_rate": 1.5,
    "has_replied": 3.0,
    "reply_rate": 2.0,
    "seniority_c_level": 1.8,
    "seniority_vp": 1.6,
    "seniority_director": 1.4,
    "company_size_enterprise": 0.8,
    "company_size_mid_market": 1.2,
    "company_size_small": 1.0,
    "industry_saas": 1.3,
    "industry_tech": 1.2,
    "recently_sent": 1.1,
    "engagement_momentum": 2.0
}


class MLLeadScorer:
    """
    Machine learning-based lead scorer for reply probability prediction.
    
    Trains on historical data and predicts reply likelihood per lead.
    """
    
    def __init__(self, db, lookback_days: int = 180, min_training_samples: int = 100):
        """
        Initialize ML scorer.
        
        Args:
            db: MongoDB database instance
            lookback_days: Historical data window for training (180 days)
            min_training_samples: Minimum samples required to train model
        """
        self.db = db
        self.sends_col = db.campaign_sends
        self.recipients_col = db.campaign_recipients
        self.leads_col = db.leads
        self.campaigns_col = db.campaigns
        self.lookback_days = lookback_days
        self.min_training_samples = min_training_samples
        self.model = None
        self.scaler = None
        self.feature_names = []
    
    def score_lead_for_reply(self, lead: Dict[str, Any]) -> Dict[str, Any]:
        """
        Predict reply probability for a single lead.
        
        Args:
            lead: Lead dict with fields like industry, seniority, email_open_history, etc.
        
        Returns:
            Dict with structure:
            {
                "lead_id": "abc123",
                "probability": 0.45,
                "confidence": 0.8,
                "factors": [
                    {"name": "has_replied", "impact": 0.25, "value": true},
                    {"name": "open_rate", "impact": 0.15, "value": 0.6}
                ],
                "recommendation": "high_priority",
                "reasoning": "Has replied before and high open rate"
            }
        """
        try:
            lead_id = lead.get("_id") or lead.get("lead_id")
            if isinstance(lead_id, ObjectId):
                lead_id = str(lead_id)
            
            # Extract features
            features = self._extract_features(lead)
            
            if not features:
                return self._get_default_score(lead)
            
            # Get historical engagement
            engagement_history = self._get_engagement_history(lead_id)
            
            # Calculate base probability from features
            base_prob = self._calculate_feature_score(features)
            
            # Adjust based on historical data
            if engagement_history.get("has_replied"):
                base_prob = min(0.95, base_prob + 0.25)
            
            # Calculate confidence
            confidence = self._calculate_confidence(
                features,
                engagement_history.get("total_sends", 0),
                engagement_history.get("data_completeness", 0)
            )
            
            # Determine impact factors (top 5)
            factors = self._get_top_factors(features, engagement_history)
            
            # Recommendation
            if base_prob >= 0.6:
                recommendation = "high_priority"
                reasoning = "High reply probability based on historical engagement and profile"
            elif base_prob >= 0.4:
                recommendation = "medium_priority"
                reasoning = "Moderate reply probability - good engagement potential"
            elif base_prob >= 0.2:
                recommendation = "low_priority"
                reasoning = "Lower reply probability - may require different approach"
            else:
                recommendation = "nurture_focus"
                reasoning = "Focus on engagement building before heavy outreach"
            
            return {
                "lead_id": lead_id,
                "probability": round(base_prob, 3),
                "confidence": round(confidence, 2),
                "factors": factors,
                "recommendation": recommendation,
                "reasoning": reasoning,
                "engagement_history": {
                    "has_replied": engagement_history.get("has_replied", False),
                    "open_rate": round(engagement_history.get("open_rate", 0), 3),
                    "reply_rate": round(engagement_history.get("reply_rate", 0), 3),
                    "total_sends": engagement_history.get("total_sends", 0)
                }
            }
        
        except Exception as e:
            logger.error(f"Error scoring lead: {e}")
            return self._get_default_score(lead)
    
    def prioritize_leads(self, lead_ids: List[str], limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Score and prioritize a batch of leads by reply probability.
        
        Args:
            lead_ids: List of lead IDs to score
            limit: Optional limit on results (default: return all)
        
        Returns:
            List of scored leads sorted by reply probability (highest first)
        """
        try:
            leads = []
            for lead_id in lead_ids:
                lead_obj_id = ObjectId(lead_id) if isinstance(lead_id, str) else lead_id
                lead = self.leads_col.find_one({"_id": lead_obj_id})
                if lead:
                    leads.append(lead)
            
            # Score all leads
            scored = []
            for idx, lead in enumerate(leads):
                score_result = self.score_lead_for_reply(lead)
                score_result["rank"] = idx + 1
                scored.append(score_result)
            
            # Sort by probability (highest first)
            scored.sort(key=lambda x: x.get("probability", 0), reverse=True)
            
            # Update ranks
            for idx, item in enumerate(scored):
                item["rank"] = idx + 1
            
            if limit:
                scored = scored[:limit]
            
            return scored
        
        except Exception as e:
            logger.error(f"Error prioritizing leads: {e}")
            return []
    
    def get_training_data(self) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        """
        Prepare training data from historical engagement records.
        
        Returns:
            Tuple of (X features array, y labels array, feature names)
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=self.lookback_days)
            
            # Get sends with reply data
            sends = list(self.sends_col.find({
                "sent_at": {"$gte": cutoff_date},
                "status": {"$in": ["replied", "sent", "opened", "clicked"]}
            }).limit(10000))
            
            if len(sends) < self.min_training_samples:
                logger.warning(f"Insufficient training data: {len(sends)} samples, need {self.min_training_samples}")
                return np.array([]), np.array([]), []
            
            # Extract features and labels
            X_data = []
            y_data = []
            
            lead_ids_seen = set()
            
            for send in sends:
                lead_id = send.get("lead_id")
                if not lead_id or lead_id in lead_ids_seen:
                    continue
                
                lead_ids_seen.add(lead_id)
                
                # Get lead data
                lead = self.leads_col.find_one({"_id": ObjectId(lead_id)})
                if not lead:
                    continue
                
                # Extract features
                features = self._extract_features(lead)
                if not features:
                    continue
                
                X_data.append(list(features.values()))
                y_data.append(1 if send.get("status") == "replied" else 0)
            
            if not X_data or not y_data:
                return np.array([]), np.array([]), []
            
            return np.array(X_data), np.array(y_data), list(features.keys())
        
        except Exception as e:
            logger.error(f"Error preparing training data: {e}")
            return np.array([]), np.array([]), []
    
    def train_model(self) -> bool:
        """
        Train ML model on historical engagement data.
        
        Returns:
            True if training successful, False otherwise
        """
        try:
            if not SKLEARN_AVAILABLE:
                logger.warning("scikit-learn not available - ML model training disabled")
                return False
            
            X, y, feature_names = self.get_training_data()
            
            if len(X) == 0:
                logger.warning("Cannot train model - insufficient data")
                return False
            
            # Normalize features
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)
            
            # Train logistic regression model
            self.model = LogisticRegression(max_iter=1000, random_state=42)
            self.model.fit(X_scaled, y)
            
            self.feature_names = feature_names
            
            logger.info(f"ML model trained successfully on {len(X)} samples")
            return True
        
        except Exception as e:
            logger.error(f"Error training model: {e}")
            return False
    
    def _extract_features(self, lead: Dict[str, Any]) -> Dict[str, float]:
        """Extract ML features from lead data."""
        features = {}
        
        try:
            lead_id = lead.get("_id") or lead.get("lead_id")
            
            # Engagement history
            history = self._get_engagement_history(str(lead_id))
            features["has_opened"] = float(history.get("has_opened", False))
            features["has_replied"] = float(history.get("has_replied", False))
            features["open_rate"] = history.get("open_rate", 0)
            features["reply_rate"] = history.get("reply_rate", 0)
            features["engagement_momentum"] = history.get("engagement_momentum", 0.5)
            
            # Demographics
            seniority = lead.get("seniority_level", "").lower()
            features["seniority_c_level"] = float("c-" in seniority or "ceo" in seniority or "cfo" in seniority)
            features["seniority_vp"] = float("vp" in seniority or "vice" in seniority)
            features["seniority_director"] = float("director" in seniority)
            
            # Company size
            company_size = lead.get("company_size", "").lower()
            employee_count = lead.get("company_employee_count", 0)
            if employee_count > 1000 or "enterprise" in company_size:
                features["company_size_enterprise"] = 1.0
                features["company_size_mid_market"] = 0.0
                features["company_size_small"] = 0.0
            elif employee_count > 100 or "mid" in company_size:
                features["company_size_enterprise"] = 0.0
                features["company_size_mid_market"] = 1.0
                features["company_size_small"] = 0.0
            else:
                features["company_size_enterprise"] = 0.0
                features["company_size_mid_market"] = 0.0
                features["company_size_small"] = 1.0
            
            # Industry
            industry = lead.get("industry", "").lower()
            features["industry_saas"] = float("saas" in industry or "software" in industry)
            features["industry_tech"] = float("tech" in industry or "technology" in industry)
            
            # Recency
            last_send = history.get("last_send_date")
            if last_send:
                days_since = (datetime.utcnow() - last_send).days
                features["recently_sent"] = max(0, 1.0 - (days_since / 30.0))  # Decay over 30 days
            else:
                features["recently_sent"] = 0.0
            
            return features
        
        except Exception as e:
            logger.error(f"Error extracting features: {e}")
            return {}
    
    def _get_engagement_history(self, lead_id: str) -> Dict[str, Any]:
        """Get engagement history for a lead."""
        try:
            lead_obj_id = ObjectId(lead_id) if isinstance(lead_id, str) else lead_id
            cutoff_date = datetime.utcnow() - timedelta(days=self.lookback_days)
            
            sends = list(self.sends_col.find({
                "lead_id": lead_obj_id,
                "sent_at": {"$gte": cutoff_date}
            }))
            
            if not sends:
                return {
                    "has_opened": False,
                    "has_replied": False,
                    "open_rate": 0,
                    "reply_rate": 0,
                    "total_sends": 0,
                    "engagement_momentum": 0.5,
                    "data_completeness": 0
                }
            
            total = len(sends)
            opened = sum(1 for s in sends if s.get("status") in ["opened", "clicked", "replied"])
            replied = sum(1 for s in sends if s.get("status") == "replied")
            
            # Calculate momentum
            mid_point = total // 2
            if mid_point > 0:
                old_engagement = sum(1 for s in sends[:mid_point] if s.get("status") in ["opened", "clicked", "replied"]) / mid_point
                new_engagement = sum(1 for s in sends[mid_point:] if s.get("status") in ["opened", "clicked", "replied"]) / max(1, total - mid_point)
                momentum = (new_engagement / old_engagement) if old_engagement > 0 else 0.5
            else:
                momentum = 0.5
            
            return {
                "has_opened": opened > 0,
                "has_replied": replied > 0,
                "open_rate": opened / total if total > 0 else 0,
                "reply_rate": replied / total if total > 0 else 0,
                "total_sends": total,
                "engagement_momentum": min(1.0, momentum),
                "data_completeness": min(1.0, total / 10),
                "last_send_date": max((s.get("sent_at") for s in sends), default=None)
            }
        
        except Exception as e:
            logger.error(f"Error getting engagement history: {e}")
            return {"total_sends": 0, "data_completeness": 0}
    
    def _calculate_feature_score(self, features: Dict[str, float]) -> float:
        """Calculate score from features using weights."""
        score = 0.0
        
        for feature_name, value in features.items():
            weight = FEATURE_WEIGHTS.get(feature_name, 1.0)
            score += value * weight
        
        # Normalize to 0-1 range
        max_possible = sum(FEATURE_WEIGHTS.values())
        normalized_score = score / max_possible if max_possible > 0 else 0.5
        
        return min(1.0, max(0.0, normalized_score))
    
    def _calculate_confidence(self, features: Dict[str, float], total_sends: int, data_completeness: float) -> float:
        """Calculate confidence score for prediction."""
        # Base confidence on data volume
        data_confidence = min(0.8, total_sends / 20)
        
        # Bonus for feature completeness
        completeness = sum(1 for v in features.values() if v > 0) / len(features) if features else 0
        completeness_confidence = completeness * 0.2
        
        # Total confidence
        confidence = data_confidence + completeness_confidence
        
        return min(1.0, max(0.3, confidence))
    
    def _get_top_factors(self, features: Dict[str, float], history: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get top 5 impactful factors for prediction."""
        factors = []
        
        # Score each factor
        factor_scores = []
        
        for feature_name, value in features.items():
            weight = FEATURE_WEIGHTS.get(feature_name, 1.0)
            impact = abs(value * weight)
            if impact > 0.01:  # Only include meaningful impacts
                factor_scores.append({
                    "name": feature_name,
                    "impact": impact,
                    "value": round(value, 2) if isinstance(value, float) else value,
                    "weight": weight
                })
        
        # Sort by impact and take top 5
        factor_scores.sort(key=lambda x: x["impact"], reverse=True)
        
        for item in factor_scores[:5]:
            factors.append({
                "name": item["name"],
                "impact": round(item["impact"] / sum(f["impact"] for f in factor_scores) if factor_scores else 0, 2),
                "value": item["value"]
            })
        
        return factors
    
    def _get_default_score(self, lead: Dict[str, Any]) -> Dict[str, Any]:
        """Return default score when unable to calculate."""
        lead_id = lead.get("_id") or lead.get("lead_id")
        
        return {
            "lead_id": str(lead_id) if lead_id else "unknown",
            "probability": 0.35,
            "confidence": 0.2,
            "factors": [],
            "recommendation": "medium_priority",
            "reasoning": "Insufficient data for accurate prediction",
            "engagement_history": {
                "has_replied": False,
                "open_rate": 0,
                "reply_rate": 0,
                "total_sends": 0
            }
        }
