"""
AUTO OPTIMIZER - THOMPSON SAMPLING A/B TEST OPTIMIZER
======================================================

Continuous variant performance monitoring with automatic traffic reallocation using
Thompson Sampling (multi-armed bandit algorithm).

Features:
- Real-time variant performance tracking
- Thompson Sampling bandit algorithm for optimal traffic allocation
- Early winner detection with statistical confidence
- Automatic recipient reallocation to winning variants
- Beta distribution modeling for conversion probabilities

Algorithm:
Thompson Sampling uses Bayesian inference to balance exploration and exploitation:
1. Model each variant's conversion rate as a Beta distribution
2. Sample from each variant's Beta(successes + 1, failures + 1)
3. Allocate traffic proportionally to sampled values
4. Continuously update distributions as data arrives

Collections:
- campaigns: Campaign definitions with A/B test config
- campaign_sends: Email send and engagement history
- campaign_recipients: Recipient list and variant assignments
- ab_tests: A/B test configurations and results

Usage:
    from campaigns.auto_optimizer import AutoOptimizer
    
    optimizer = AutoOptimizer(db)
    
    # Get optimal traffic allocation
    allocation = optimizer.allocate_traffic("campaign_123")
    # Returns: {"A": 0.35, "B": 0.65}
    
    # Check if we can declare a winner early
    winner = optimizer.detect_winner_early("campaign_123")
    # Returns: "B" or None
    
    # Reallocate remaining recipients to winner
    result = optimizer.reallocate_recipients(
        campaign_id="campaign_123",
        new_ratio={"A": 0.2, "B": 0.8}
    )

Requirements:
    pip install scipy numpy
"""

from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
from bson import ObjectId
import logging

try:
    from scipy.stats import beta, binom_test
    import numpy as np
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    logging.warning(
        "scipy/numpy not installed. Install with: pip install scipy numpy\n"
        "Thompson Sampling optimization will not be available."
    )

logger = logging.getLogger(__name__)


class AutoOptimizer:
    """
    Automatic A/B test optimizer using Thompson Sampling bandit algorithm.
    
    Continuously monitors variant performance and reallocates traffic to winners.
    """
    
    def __init__(self, db):
        """
        Initialize the auto optimizer.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.campaigns_col = db.campaigns
        self.sends_col = db.campaign_sends
        self.recipients_col = db.campaign_recipients
        self.ab_tests_col = db.ab_tests
        
        if not SCIPY_AVAILABLE:
            logger.error("scipy/numpy not available - optimizer disabled")
    
    def allocate_traffic(
        self,
        campaign_id: str,
        num_samples: int = 10000
    ) -> Dict[str, float]:
        """
        Calculate optimal traffic allocation using Thompson Sampling.
        
        Uses Beta distributions to model each variant's conversion probability,
        then samples to determine optimal allocation.
        
        Args:
            campaign_id: Campaign identifier
            num_samples: Number of Monte Carlo samples (default: 10000)
        
        Returns:
            Dict mapping variant names to allocation ratios
            Example: {"A": 0.35, "B": 0.45, "C": 0.20}
        
        Algorithm:
            1. Get performance data (sends, conversions) per variant
            2. Model each variant as Beta(conversions + 1, non_conversions + 1)
            3. Sample num_samples times from each Beta distribution
            4. Count how often each variant has highest sample
            5. Return allocation proportional to "win" counts
        """
        if not SCIPY_AVAILABLE:
            logger.error("scipy not available")
            return {}
        
        try:
            # Get campaign and variants
            campaign = self.campaigns_col.find_one({"_id": ObjectId(campaign_id)})
            if not campaign:
                logger.error(f"Campaign {campaign_id} not found")
                return {}
            
            ab_config = campaign.get("ab_test_config", {})
            if not ab_config or not ab_config.get("enabled"):
                logger.error(f"A/B testing not enabled for campaign {campaign_id}")
                return {}
            
            variants = ab_config.get("variants", [])
            if not variants:
                logger.error(f"No variants configured for campaign {campaign_id}")
                return {}
            
            # Get performance data for each variant
            variant_stats = self._get_variant_performance(campaign_id, variants)
            
            if not variant_stats:
                # No data yet, return equal allocation
                equal_split = 1.0 / len(variants)
                return {v: equal_split for v in variants}
            
            # Thompson Sampling: Sample from Beta distributions
            win_counts = {v: 0 for v in variants}
            
            for _ in range(num_samples):
                samples = {}
                for variant in variants:
                    stats = variant_stats.get(variant, {"conversions": 0, "total": 0})
                    conversions = stats["conversions"]
                    total = stats["total"]
                    failures = total - conversions
                    
                    # Beta(α=successes+1, β=failures+1) - Laplace smoothing
                    alpha = conversions + 1
                    beta_param = failures + 1
                    
                    # Sample from Beta distribution
                    samples[variant] = np.random.beta(alpha, beta_param)
                
                # Winner is variant with highest sample
                winner = max(samples, key=samples.get)
                win_counts[winner] += 1
            
            # Convert win counts to allocation ratios
            total_wins = sum(win_counts.values())
            allocation = {
                variant: win_counts[variant] / total_wins
                for variant in variants
            }
            
            logger.info(f"Thompson Sampling allocation for {campaign_id}: {allocation}")
            return allocation
        
        except Exception as e:
            logger.error(f"Error calculating traffic allocation: {e}")
            return {}
    
    def detect_winner_early(
        self,
        campaign_id: str,
        confidence_threshold: float = 0.95,
        min_samples_per_variant: int = 100
    ) -> Optional[str]:
        """
        Detect if we can declare a winner before test completion.
        
        Uses Bayesian probability that each variant is the best. Declares winner
        when one variant has >confidence_threshold probability of being best.
        
        Args:
            campaign_id: Campaign identifier
            confidence_threshold: Minimum probability to declare winner (default: 0.95)
            min_samples_per_variant: Minimum sends required per variant (default: 100)
        
        Returns:
            Winning variant name if detected, None otherwise
        
        Algorithm:
            1. Get performance data for all variants
            2. Check minimum sample size requirement
            3. Sample from Beta distributions for each variant
            4. Count how often each variant has highest conversion rate
            5. If one variant wins >confidence_threshold of the time, declare winner
        """
        if not SCIPY_AVAILABLE:
            logger.error("scipy not available")
            return None
        
        try:
            # Get campaign and variants
            campaign = self.campaigns_col.find_one({"_id": ObjectId(campaign_id)})
            if not campaign:
                logger.error(f"Campaign {campaign_id} not found")
                return None
            
            ab_config = campaign.get("ab_test_config", {})
            if not ab_config or not ab_config.get("enabled"):
                return None
            
            variants = ab_config.get("variants", [])
            if len(variants) < 2:
                return None
            
            # Get performance data
            variant_stats = self._get_variant_performance(campaign_id, variants)
            
            # Check minimum sample requirement
            for variant in variants:
                stats = variant_stats.get(variant, {"total": 0})
                if stats["total"] < min_samples_per_variant:
                    logger.info(
                        f"Variant {variant} has only {stats['total']} samples "
                        f"(min: {min_samples_per_variant})"
                    )
                    return None
            
            # Run Thompson Sampling simulation
            num_samples = 100000
            win_counts = {v: 0 for v in variants}
            
            for _ in range(num_samples):
                samples = {}
                for variant in variants:
                    stats = variant_stats[variant]
                    conversions = stats["conversions"]
                    total = stats["total"]
                    failures = total - conversions
                    
                    alpha = conversions + 1
                    beta_param = failures + 1
                    samples[variant] = np.random.beta(alpha, beta_param)
                
                winner = max(samples, key=samples.get)
                win_counts[winner] += 1
            
            # Calculate probabilities
            probabilities = {
                variant: win_counts[variant] / num_samples
                for variant in variants
            }
            
            # Check if any variant exceeds confidence threshold
            best_variant = max(probabilities, key=probabilities.get)
            best_probability = probabilities[best_variant]
            
            logger.info(f"Winner probabilities: {probabilities}")
            
            if best_probability >= confidence_threshold:
                logger.info(
                    f"Winner detected: {best_variant} "
                    f"(confidence: {best_probability:.2%})"
                )
                
                # Update campaign with winner
                self.campaigns_col.update_one(
                    {"_id": ObjectId(campaign_id)},
                    {
                        "$set": {
                            "ab_test_config.winner_variant": best_variant,
                            "ab_test_config.test_status": "completed",
                            "ab_test_config.winner_detected_at": datetime.utcnow(),
                            "ab_test_config.winner_confidence": best_probability
                        }
                    }
                )
                
                return best_variant
            
            return None
        
        except Exception as e:
            logger.error(f"Error detecting winner: {e}")
            return None
    
    def reallocate_recipients(
        self,
        campaign_id: str,
        new_ratio: Dict[str, float]
    ) -> Dict:
        """
        Reallocate remaining (pending) recipients to new variant ratios.
        
        Updates variant assignments for recipients who haven't been sent yet,
        based on new traffic allocation ratios.
        
        Args:
            campaign_id: Campaign identifier
            new_ratio: New allocation ratios, e.g. {"A": 0.2, "B": 0.8}
        
        Returns:
            Dict with reallocation statistics:
            {
                "total_reallocated": 450,
                "by_variant": {"A": 90, "B": 360},
                "previous_allocation": {"A": 0.5, "B": 0.5}
            }
        """
        try:
            # Validate ratios sum to 1.0
            ratio_sum = sum(new_ratio.values())
            if not (0.99 <= ratio_sum <= 1.01):
                logger.error(f"Invalid ratio sum: {ratio_sum}")
                return {"error": "Ratios must sum to 1.0"}
            
            # Get pending recipients (not yet sent)
            pending_recipients = list(self.recipients_col.find({
                "campaign_id": campaign_id,
                "status": "pending"
            }))
            
            if not pending_recipients:
                logger.info(f"No pending recipients to reallocate for {campaign_id}")
                return {
                    "total_reallocated": 0,
                    "by_variant": {},
                    "message": "No pending recipients"
                }
            
            total_pending = len(pending_recipients)
            variants = list(new_ratio.keys())
            
            # Calculate new counts per variant
            new_counts = {}
            remaining = total_pending
            
            for i, variant in enumerate(variants[:-1]):
                count = int(total_pending * new_ratio[variant])
                new_counts[variant] = count
                remaining -= count
            
            # Last variant gets remaining
            new_counts[variants[-1]] = remaining
            
            # Shuffle recipients for random assignment
            import random
            random.shuffle(pending_recipients)
            
            # Reassign variants
            reallocation_stats = {variant: 0 for variant in variants}
            idx = 0
            
            for variant, count in new_counts.items():
                for _ in range(count):
                    if idx >= len(pending_recipients):
                        break
                    
                    recipient = pending_recipients[idx]
                    self.recipients_col.update_one(
                        {"_id": recipient["_id"]},
                        {"$set": {"ab_variant": variant}}
                    )
                    reallocation_stats[variant] += 1
                    idx += 1
            
            logger.info(
                f"Reallocated {total_pending} recipients: {reallocation_stats}"
            )
            
            # Update campaign with new ratio
            self.campaigns_col.update_one(
                {"_id": ObjectId(campaign_id)},
                {"$set": {"ab_test_config.split_ratio": new_ratio}}
            )
            
            return {
                "total_reallocated": total_pending,
                "by_variant": reallocation_stats,
                "new_ratio": new_ratio
            }
        
        except Exception as e:
            logger.error(f"Error reallocating recipients: {e}")
            return {"error": str(e)}
    
    def _get_variant_performance(
        self,
        campaign_id: str,
        variants: List[str]
    ) -> Dict[str, Dict]:
        """
        Get performance metrics for each variant.
        
        Args:
            campaign_id: Campaign identifier
            variants: List of variant names
        
        Returns:
            Dict mapping variant to performance stats:
            {
                "A": {"total": 500, "conversions": 45, "conversion_rate": 0.09},
                "B": {"total": 500, "conversions": 62, "conversion_rate": 0.124}
            }
        """
        variant_stats = {}
        
        # Get A/B test config to determine winning metric
        campaign = self.campaigns_col.find_one({"_id": ObjectId(campaign_id)})
        ab_config = campaign.get("ab_test_config", {})
        winning_metric = ab_config.get("winning_metric", "reply_rate")
        
        for variant in variants:
            # Get all sends for this variant
            sends = list(self.sends_col.find({
                "campaign_id": campaign_id,
                "ab_variant": variant
            }))
            
            total = len(sends)
            conversions = 0
            
            # Count conversions based on winning metric
            if winning_metric == "open_rate":
                conversions = sum(1 for s in sends if s.get("opened_at"))
            elif winning_metric == "click_rate":
                conversions = sum(1 for s in sends if s.get("clicked_at"))
            elif winning_metric == "reply_rate":
                conversions = sum(1 for s in sends if s.get("replied_at"))
            else:
                # Default to reply rate
                conversions = sum(1 for s in sends if s.get("replied_at"))
            
            conversion_rate = conversions / total if total > 0 else 0.0
            
            variant_stats[variant] = {
                "total": total,
                "conversions": conversions,
                "conversion_rate": conversion_rate
            }
        
        return variant_stats
    
    def get_optimization_status(self, campaign_id: str) -> Dict:
        """
        Get current optimization status and recommendations.
        
        Args:
            campaign_id: Campaign identifier
        
        Returns:
            Dict with optimization status and recommendations
        """
        try:
            campaign = self.campaigns_col.find_one({"_id": ObjectId(campaign_id)})
            if not campaign:
                return {"error": "Campaign not found"}
            
            ab_config = campaign.get("ab_test_config", {})
            if not ab_config or not ab_config.get("enabled"):
                return {"error": "A/B testing not enabled"}
            
            variants = ab_config.get("variants", [])
            variant_stats = self._get_variant_performance(campaign_id, variants)
            
            # Calculate recommended allocation
            recommended_allocation = self.allocate_traffic(campaign_id)
            
            # Check for early winner
            winner = self.detect_winner_early(campaign_id)
            
            return {
                "campaign_id": campaign_id,
                "variants": variants,
                "current_allocation": ab_config.get("split_ratio", {}),
                "recommended_allocation": recommended_allocation,
                "variant_performance": variant_stats,
                "winner_detected": winner,
                "test_status": ab_config.get("test_status", "running")
            }
        
        except Exception as e:
            logger.error(f"Error getting optimization status: {e}")
            return {"error": str(e)}


# ============== EXAMPLE USAGE ==============

if __name__ == "__main__":
    from pymongo import MongoClient
    
    # Connect to database
    client = MongoClient("mongodb://localhost:27017/")
    db = client.campaign_platform
    
    optimizer = AutoOptimizer(db)
    
    # Example: Get optimization status
    campaign_id = "60d5ec49f1a2c8b5e8c9a123"
    status = optimizer.get_optimization_status(campaign_id)
    print(f"\nOptimization Status:")
    print(f"  Current allocation: {status.get('current_allocation')}")
    print(f"  Recommended allocation: {status.get('recommended_allocation')}")
    print(f"  Winner detected: {status.get('winner_detected')}")
    
    # Example: Allocate traffic using Thompson Sampling
    allocation = optimizer.allocate_traffic(campaign_id)
    print(f"\nThompson Sampling allocation: {allocation}")
    
    # Example: Detect early winner
    winner = optimizer.detect_winner_early(campaign_id)
    if winner:
        print(f"\nEarly winner detected: {winner}")
        
        # Reallocate remaining recipients to winner
        result = optimizer.reallocate_recipients(
            campaign_id=campaign_id,
            new_ratio={winner: 0.8, "other": 0.2}  # 80% to winner
        )
        print(f"Reallocated {result['total_reallocated']} recipients")
