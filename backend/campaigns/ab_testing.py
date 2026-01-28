"""
A/B TESTING SERVICE
===================

Statistical A/B testing for email campaigns with automatic winner selection.

Features:
- Random variant assignment with weighted split ratios
- Statistical significance testing:
  * Chi-squared test for conversion comparison
  * Z-test for proportion comparison  
  * Confidence interval calculation
- Automatic winner declaration when significance threshold met
- Winner rollout to remaining recipients
- Real-time metrics tracking

Statistical Methods:
- Chi-squared test: Tests if conversion rate differences are significant
- Z-test for proportions: Compares proportion differences between variants
- Confidence intervals: 95% CI for conversion rates
- P-value threshold: Default 0.05 (95% confidence)

Collections:
- ab_tests: A/B test configurations and results
- ab_test_assignments: Variant assignments per recipient
- campaign_sends: Email performance tracking

Usage:
    service = ABTestingService(db)
    
    # Assign variant to recipient
    variant = service.assign_variant(
        campaign_id="abc123",
        recipient_id="lead_456",
        variants=["control", "variant_a"],
        split_ratio={"control": 0.5, "variant_a": 0.5}
    )
    
    # Check for statistical significance
    result = service.calculate_significance(
        control_data={"conversions": 45, "total": 500},
        variant_data={"conversions": 62, "total": 500}
    )
    
    # Auto-declare winner if significant
    winner = service.should_declare_winner(
        campaign_id="abc123",
        threshold=0.95
    )

Requirements:
    pip install scipy
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Literal, Tuple
from bson import ObjectId
import random
import logging
import math

# Statistical functions
try:
    from scipy import stats
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    logging.warning(
        "scipy not installed. Install with: pip install scipy\n"
        "Statistical significance testing will not be available."
    )

logger = logging.getLogger(__name__)


class ABTestingService:
    """
    Service for A/B testing campaigns with statistical significance analysis.
    
    Attributes:
        db: MongoDB database instance
    """
    
    def __init__(self, db):
        """
        Initialize the A/B testing service.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.ab_tests_col = db.ab_tests
        self.assignments_col = db.ab_test_assignments
        self.sends_col = db.campaign_sends
        self.campaigns_col = db.campaigns
        
        if not SCIPY_AVAILABLE:
            logger.warning("scipy not available - statistical testing disabled")
    
    def assign_variant(
        self,
        campaign_id: str,
        recipient_id: str,
        variants: List[str],
        split_ratio: Optional[Dict[str, float]] = None
    ) -> str:
        """
        Assign a variant to a recipient using weighted random selection.
        
        Args:
            campaign_id: Campaign ID for the A/B test
            recipient_id: Recipient/lead ID to assign
            variants: List of variant names (e.g., ["control", "variant_a"])
            split_ratio: Optional dict of variant weights (default: equal split)
                Example: {"control": 0.5, "variant_a": 0.3, "variant_b": 0.2}
        
        Returns:
            Assigned variant name
        """
        if not variants:
            raise ValueError("At least one variant required")
        
        # Check if already assigned
        existing = self.assignments_col.find_one({
            "campaign_id": ObjectId(campaign_id) if isinstance(campaign_id, str) else campaign_id,
            "recipient_id": ObjectId(recipient_id) if isinstance(recipient_id, str) else recipient_id
        })
        
        if existing:
            return existing["variant"]
        
        # Default to equal split if not specified
        if not split_ratio:
            split_ratio = {v: 1.0 / len(variants) for v in variants}
        
        # Validate split ratio
        total_weight = sum(split_ratio.values())
        if not math.isclose(total_weight, 1.0, abs_tol=0.01):
            raise ValueError(f"Split ratio must sum to 1.0, got {total_weight}")
        
        # Weighted random selection
        variant = random.choices(
            population=variants,
            weights=[split_ratio.get(v, 0) for v in variants],
            k=1
        )[0]
        
        # Store assignment
        assignment = {
            "campaign_id": ObjectId(campaign_id) if isinstance(campaign_id, str) else campaign_id,
            "recipient_id": ObjectId(recipient_id) if isinstance(recipient_id, str) else recipient_id,
            "variant": variant,
            "assigned_at": datetime.utcnow(),
            "converted": False,
            "conversion_value": 0.0
        }
        
        self.assignments_col.insert_one(assignment)
        
        # Update test metrics
        self.ab_tests_col.update_one(
            {"campaign_id": assignment["campaign_id"]},
            {
                "$inc": {f"variants.{variant}.assigned": 1},
                "$setOnInsert": {
                    "campaign_id": assignment["campaign_id"],
                    "created_at": datetime.utcnow(),
                    "status": "active"
                }
            },
            upsert=True
        )
        
        logger.debug(f"Assigned variant '{variant}' to recipient {recipient_id}")
        return variant
    
    def calculate_significance(
        self,
        control_data: Dict[str, int],
        variant_data: Dict[str, int]
    ) -> Dict:
        """
        Calculate statistical significance between control and variant.
        
        Uses both chi-squared test and z-test for proportions to determine
        if the difference in conversion rates is statistically significant.
        
        Args:
            control_data: {"conversions": int, "total": int}
            variant_data: {"conversions": int, "total": int}
        
        Returns:
            {
                "p_value": float,           # P-value from chi-squared test
                "z_score": float,           # Z-score from z-test
                "significant": bool,        # True if p < 0.05
                "confidence": float,        # Confidence level (1 - p_value)
                "control_rate": float,      # Control conversion rate
                "variant_rate": float,      # Variant conversion rate
                "lift": float,              # Percentage lift over control
                "confidence_interval": {
                    "lower": float,         # 95% CI lower bound
                    "upper": float          # 95% CI upper bound
                },
                "method": str               # "chi_squared" or "fallback"
            }
        """
        if not SCIPY_AVAILABLE:
            return self._calculate_significance_fallback(control_data, variant_data)
        
        # Extract data
        control_conv = control_data.get("conversions", 0)
        control_total = control_data.get("total", 0)
        variant_conv = variant_data.get("conversions", 0)
        variant_total = variant_data.get("total", 0)
        
        # Validate inputs
        if control_total == 0 or variant_total == 0:
            return {
                "p_value": 1.0,
                "z_score": 0.0,
                "significant": False,
                "confidence": 0.0,
                "control_rate": 0.0,
                "variant_rate": 0.0,
                "lift": 0.0,
                "confidence_interval": {"lower": 0.0, "upper": 0.0},
                "method": "insufficient_data",
                "message": "Insufficient data for significance testing"
            }
        
        # Calculate conversion rates
        control_rate = control_conv / control_total
        variant_rate = variant_conv / variant_total
        
        # Calculate lift
        if control_rate > 0:
            lift = ((variant_rate - control_rate) / control_rate) * 100
        else:
            lift = 0.0
        
        # Chi-squared test for independence
        # Contingency table: [[converted, not_converted], [converted, not_converted]]
        contingency_table = [
            [control_conv, control_total - control_conv],
            [variant_conv, variant_total - variant_conv]
        ]
        
        chi2, p_value, dof, expected = stats.chi2_contingency(contingency_table)
        
        # Z-test for proportions
        z_score, z_p_value = self._z_test_proportions(
            control_conv, control_total,
            variant_conv, variant_total
        )
        
        # 95% Confidence interval for variant rate
        ci_lower, ci_upper = self._confidence_interval(variant_conv, variant_total)
        
        # Determine significance (p < 0.05)
        significant = p_value < 0.05
        confidence = 1.0 - p_value
        
        result = {
            "p_value": float(p_value),
            "z_score": float(z_score),
            "chi_squared": float(chi2),
            "significant": significant,
            "confidence": float(confidence),
            "control_rate": float(control_rate),
            "variant_rate": float(variant_rate),
            "lift": float(lift),
            "confidence_interval": {
                "lower": float(ci_lower),
                "upper": float(ci_upper)
            },
            "method": "chi_squared",
            "sample_size": {
                "control": control_total,
                "variant": variant_total
            }
        }
        
        logger.info(
            f"Significance test: p={p_value:.4f}, "
            f"lift={lift:.1f}%, significant={significant}"
        )
        
        return result
    
    def _z_test_proportions(
        self,
        conv1: int, total1: int,
        conv2: int, total2: int
    ) -> Tuple[float, float]:
        """
        Perform z-test for comparing two proportions.
        
        Args:
            conv1: Conversions in group 1
            total1: Total in group 1
            conv2: Conversions in group 2
            total2: Total in group 2
        
        Returns:
            (z_score, p_value)
        """
        if not SCIPY_AVAILABLE:
            return 0.0, 1.0
        
        p1 = conv1 / total1 if total1 > 0 else 0
        p2 = conv2 / total2 if total2 > 0 else 0
        
        # Pooled proportion
        p_pool = (conv1 + conv2) / (total1 + total2)
        
        # Standard error
        se = math.sqrt(p_pool * (1 - p_pool) * (1/total1 + 1/total2))
        
        if se == 0:
            return 0.0, 1.0
        
        # Z-score
        z_score = (p2 - p1) / se
        
        # Two-tailed p-value
        p_value = 2 * (1 - stats.norm.cdf(abs(z_score)))
        
        return z_score, p_value
    
    def _confidence_interval(
        self,
        conversions: int,
        total: int,
        confidence_level: float = 0.95
    ) -> Tuple[float, float]:
        """
        Calculate confidence interval for a conversion rate.
        
        Args:
            conversions: Number of conversions
            total: Total sample size
            confidence_level: Confidence level (default: 0.95)
        
        Returns:
            (lower_bound, upper_bound)
        """
        if total == 0:
            return 0.0, 0.0
        
        p = conversions / total
        
        # Wilson score interval (better for small samples)
        z = stats.norm.ppf((1 + confidence_level) / 2)
        denominator = 1 + z**2 / total
        center = (p + z**2 / (2 * total)) / denominator
        margin = z * math.sqrt((p * (1 - p) / total + z**2 / (4 * total**2))) / denominator
        
        lower = max(0.0, center - margin)
        upper = min(1.0, center + margin)
        
        return lower, upper
    
    def _calculate_significance_fallback(
        self,
        control_data: Dict[str, int],
        variant_data: Dict[str, int]
    ) -> Dict:
        """
        Fallback significance calculation without scipy.
        
        Uses simplified statistical approximations.
        
        Args:
            control_data: {"conversions": int, "total": int}
            variant_data: {"conversions": int, "total": int}
        
        Returns:
            Simplified significance result
        """
        control_conv = control_data.get("conversions", 0)
        control_total = control_data.get("total", 0)
        variant_conv = variant_data.get("conversions", 0)
        variant_total = variant_data.get("total", 0)
        
        if control_total == 0 or variant_total == 0:
            return {
                "p_value": 1.0,
                "significant": False,
                "confidence": 0.0,
                "control_rate": 0.0,
                "variant_rate": 0.0,
                "lift": 0.0,
                "method": "fallback",
                "message": "Install scipy for accurate significance testing"
            }
        
        control_rate = control_conv / control_total
        variant_rate = variant_conv / variant_total
        
        # Simple lift calculation
        lift = ((variant_rate - control_rate) / control_rate * 100) if control_rate > 0 else 0
        
        # Rough significance heuristic
        # (not statistically rigorous - just for demo)
        diff = abs(variant_rate - control_rate)
        significant = (diff > 0.05 and 
                      min(control_total, variant_total) >= 100 and
                      min(control_conv, variant_conv) >= 10)
        
        return {
            "p_value": 0.04 if significant else 0.5,
            "significant": significant,
            "confidence": 0.96 if significant else 0.5,
            "control_rate": control_rate,
            "variant_rate": variant_rate,
            "lift": lift,
            "method": "fallback",
            "message": "Install scipy for accurate statistical testing"
        }
    
    def should_declare_winner(
        self,
        campaign_id: str,
        threshold: float = 0.95,
        min_sample_size: int = 100
    ) -> Optional[str]:
        """
        Check if a winner should be declared based on statistical significance.
        
        Args:
            campaign_id: Campaign ID for the A/B test
            threshold: Confidence threshold (default: 0.95 = 95%)
            min_sample_size: Minimum sample size per variant (default: 100)
        
        Returns:
            Winning variant name if significant, None otherwise
        """
        # Get test data
        test = self.ab_tests_col.find_one({"campaign_id": ObjectId(campaign_id)})
        
        if not test:
            logger.warning(f"No A/B test found for campaign {campaign_id}")
            return None
        
        if test.get("winner_declared"):
            return test.get("winner")
        
        variants = test.get("variants", {})
        variant_names = list(variants.keys())
        
        if len(variant_names) < 2:
            logger.warning("Need at least 2 variants for comparison")
            return None
        
        # Assume first variant is control
        control_name = variant_names[0]
        control_data = variants[control_name]
        
        # Check each variant against control
        best_variant = None
        best_confidence = 0.0
        
        for variant_name in variant_names[1:]:
            variant_data = variants[variant_name]
            
            # Check minimum sample size
            if (control_data.get("assigned", 0) < min_sample_size or
                variant_data.get("assigned", 0) < min_sample_size):
                continue
            
            # Calculate significance
            result = self.calculate_significance(
                control_data={
                    "conversions": control_data.get("conversions", 0),
                    "total": control_data.get("assigned", 0)
                },
                variant_data={
                    "conversions": variant_data.get("conversions", 0),
                    "total": variant_data.get("assigned", 0)
                }
            )
            
            # Check if significant and better than control
            if (result["significant"] and 
                result["confidence"] >= threshold and
                result["variant_rate"] > result["control_rate"]):
                
                if result["confidence"] > best_confidence:
                    best_variant = variant_name
                    best_confidence = result["confidence"]
        
        # If no variant is better, control wins
        if best_variant is None and control_data.get("assigned", 0) >= min_sample_size:
            best_variant = control_name
        
        # Declare winner if found
        if best_variant:
            self._declare_winner(campaign_id, best_variant, best_confidence)
            return best_variant
        
        return None
    
    def _declare_winner(self, campaign_id: str, winner: str, confidence: float):
        """
        Declare a winner for the A/B test.
        
        Args:
            campaign_id: Campaign ID
            winner: Winning variant name
            confidence: Statistical confidence level
        """
        self.ab_tests_col.update_one(
            {"campaign_id": ObjectId(campaign_id)},
            {
                "$set": {
                    "winner": winner,
                    "winner_declared": True,
                    "winner_declared_at": datetime.utcnow(),
                    "winner_confidence": confidence,
                    "status": "completed"
                }
            }
        )
        
        logger.info(
            f"Declared winner for campaign {campaign_id}: "
            f"{winner} (confidence: {confidence:.1%})"
        )
    
    def rollout_winner(
        self,
        campaign_id: str,
        winner: Optional[str] = None
    ) -> int:
        """
        Roll out the winning variant to all remaining recipients.
        
        Args:
            campaign_id: Campaign ID
            winner: Winner variant name (auto-detected if None)
        
        Returns:
            Number of recipients switched to winner
        """
        # Get winner if not specified
        if not winner:
            test = self.ab_tests_col.find_one({"campaign_id": ObjectId(campaign_id)})
            if not test or not test.get("winner"):
                raise ValueError("No winner declared yet")
            winner = test["winner"]
        
        # Update all pending assignments to winner
        result = self.assignments_col.update_many(
            {
                "campaign_id": ObjectId(campaign_id),
                "variant": {"$ne": winner},
                "converted": False
            },
            {
                "$set": {
                    "variant": winner,
                    "switched_to_winner": True,
                    "switched_at": datetime.utcnow()
                }
            }
        )
        
        count = result.modified_count
        logger.info(f"Rolled out winner '{winner}' to {count} recipients")
        return count
    
    def record_conversion(
        self,
        recipient_id: str,
        campaign_id: str,
        conversion_value: float = 1.0
    ):
        """
        Record a conversion for a recipient in an A/B test.
        
        Args:
            recipient_id: Recipient ID
            campaign_id: Campaign ID
            conversion_value: Optional conversion value (default: 1.0)
        """
        # Update assignment
        assignment = self.assignments_col.find_one_and_update(
            {
                "campaign_id": ObjectId(campaign_id),
                "recipient_id": ObjectId(recipient_id)
            },
            {
                "$set": {
                    "converted": True,
                    "converted_at": datetime.utcnow(),
                    "conversion_value": conversion_value
                }
            },
            return_document=True
        )
        
        if not assignment:
            logger.warning(f"No assignment found for recipient {recipient_id}")
            return
        
        variant = assignment["variant"]
        
        # Update test metrics
        self.ab_tests_col.update_one(
            {"campaign_id": ObjectId(campaign_id)},
            {
                "$inc": {
                    f"variants.{variant}.conversions": 1,
                    f"variants.{variant}.conversion_value": conversion_value
                }
            }
        )
        
        logger.info(
            f"Recorded conversion for recipient {recipient_id} "
            f"(variant: {variant}, value: {conversion_value})"
        )
    
    def get_test_metrics(self, campaign_id: str) -> Dict:
        """
        Get comprehensive A/B test metrics.
        
        Args:
            campaign_id: Campaign ID
        
        Returns:
            Dictionary with test metrics for all variants
        """
        test = self.ab_tests_col.find_one({"campaign_id": ObjectId(campaign_id)})
        
        if not test:
            raise ValueError(f"No A/B test found for campaign {campaign_id}")
        
        variants = test.get("variants", {})
        metrics = {
            "campaign_id": str(campaign_id),
            "status": test.get("status"),
            "winner": test.get("winner"),
            "winner_declared": test.get("winner_declared", False),
            "variants": {}
        }
        
        for variant_name, variant_data in variants.items():
            assigned = variant_data.get("assigned", 0)
            conversions = variant_data.get("conversions", 0)
            conversion_value = variant_data.get("conversion_value", 0.0)
            
            metrics["variants"][variant_name] = {
                "assigned": assigned,
                "conversions": conversions,
                "conversion_rate": conversions / assigned if assigned > 0 else 0,
                "conversion_value": conversion_value,
                "avg_value": conversion_value / conversions if conversions > 0 else 0
            }
        
        return metrics


def example_usage():
    """Example demonstrating A/B testing service usage."""
    from pymongo import MongoClient
    
    # Connect to database
    client = MongoClient("mongodb://localhost:27017/")
    db = client.campaign_platform
    
    # Initialize service
    service = ABTestingService(db)
    
    print("=" * 80)
    print("A/B TESTING SERVICE EXAMPLE")
    print("=" * 80)
    
    campaign_id = "test_campaign_123"
    variants = ["control", "variant_a", "variant_b"]
    split_ratio = {"control": 0.4, "variant_a": 0.3, "variant_b": 0.3}
    
    # 1. Assign variants to recipients
    print("\n1. Assigning variants to recipients...")
    for i in range(300):
        recipient_id = f"recipient_{i}"
        variant = service.assign_variant(
            campaign_id=campaign_id,
            recipient_id=recipient_id,
            variants=variants,
            split_ratio=split_ratio
        )
        
        # Simulate conversions (variant_a performs better)
        if variant == "control" and random.random() < 0.10:
            service.record_conversion(recipient_id, campaign_id)
        elif variant == "variant_a" and random.random() < 0.15:  # 50% lift
            service.record_conversion(recipient_id, campaign_id)
        elif variant == "variant_b" and random.random() < 0.09:  # Worse
            service.record_conversion(recipient_id, campaign_id)
    
    print("Assigned variants to 300 recipients")
    
    # 2. Get metrics
    print("\n2. Current test metrics...")
    metrics = service.get_test_metrics(campaign_id)
    for variant_name, variant_metrics in metrics["variants"].items():
        print(f"\n{variant_name}:")
        print(f"  - Assigned: {variant_metrics['assigned']}")
        print(f"  - Conversions: {variant_metrics['conversions']}")
        print(f"  - Conversion rate: {variant_metrics['conversion_rate']:.2%}")
    
    # 3. Check significance
    print("\n3. Statistical significance test...")
    if len(metrics["variants"]) >= 2:
        control_metrics = metrics["variants"]["control"]
        variant_a_metrics = metrics["variants"]["variant_a"]
        
        result = service.calculate_significance(
            control_data={
                "conversions": control_metrics["conversions"],
                "total": control_metrics["assigned"]
            },
            variant_data={
                "conversions": variant_a_metrics["conversions"],
                "total": variant_a_metrics["assigned"]
            }
        )
        
        print(f"Control rate: {result['control_rate']:.2%}")
        print(f"Variant A rate: {result['variant_rate']:.2%}")
        print(f"Lift: {result['lift']:.1f}%")
        print(f"P-value: {result['p_value']:.4f}")
        print(f"Significant: {result['significant']}")
        print(f"Confidence: {result['confidence']:.1%}")
        
        if result.get("confidence_interval"):
            ci = result["confidence_interval"]
            print(f"95% CI: [{ci['lower']:.2%}, {ci['upper']:.2%}]")
    
    # 4. Check for winner
    print("\n4. Checking for winner...")
    winner = service.should_declare_winner(campaign_id, threshold=0.95, min_sample_size=50)
    
    if winner:
        print(f"Winner declared: {winner}")
        
        # 5. Rollout winner
        print("\n5. Rolling out winner to remaining recipients...")
        count = service.rollout_winner(campaign_id, winner)
        print(f"Switched {count} recipients to {winner}")
    else:
        print("No winner yet - need more data or higher significance")


if __name__ == "__main__":
    # Note: Requires scipy for full functionality
    # Install with: pip install scipy
    example_usage()
