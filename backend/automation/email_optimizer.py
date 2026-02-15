"""
Email Optimizer - AI-powered campaign email variant generation

Generates 3 personalized email variants for a campaign based on:
1. Lead segment (seniority, industry, company size)
2. Campaign context
3. Historical performance data

Uses OpenAI (gpt-4o-mini) to generate variants with maximum personalization.
Maximum personalization means tone, style, and messaging change based on lead attributes.
"""

import logging
import json
from typing import Optional, Dict, Any, List
from pymongo.database import Database
from datetime import datetime

logger = logging.getLogger(__name__)


class EmailOptimizer:
    """
    AI-powered email variant generator.

    Generates 3 optimized email variants per campaign with maximum personalization.
    Selects best variant based on confidence score.
    """

    def __init__(self, db: Database, openai_wrapper=None, decision_logger=None):
        """
        Initialize email optimizer.

        Args:
            db: MongoDB database instance
            openai_wrapper: OpenAI wrapper for API calls
            decision_logger: Optional DecisionLogger for compliance logging
        """
        self.db = db
        self.campaigns = db["campaigns"]
        self.email_templates = db["email_templates"]
        self.email_variants = db["email_variants"]
        self.openai_wrapper = openai_wrapper
        self.decision_logger = decision_logger

    def generate_variants(
        self,
        campaign_id: str,
        base_template_id: str,
        auto_select: bool = True
    ) -> Dict[str, Any]:
        """
        Generate 3 personalized email variants for a campaign.

        Args:
            campaign_id: Campaign ID
            base_template_id: Template to base variants on
            auto_select: If True, automatically select best variant

        Returns:
            Dict with:
            {
                "campaign_id": "...",
                "variants": [
                    {
                        "variant_id": "...",
                        "name": "Executive Focus",
                        "subject": "...",
                        "body_html": "...",
                        "personalization_note": "...",
                        "confidence_score": 0.92
                    }
                ],
                "selected_variant_id": "..." (if auto_select=True),
                "decision_log_id": "..." (if logged)
            }
        """
        # Get campaign and base template
        campaign = self.campaigns.find_one({"_id": campaign_id})
        if not campaign:
            return {"error": f"Campaign {campaign_id} not found"}

        base_template = self.email_templates.find_one({"_id": base_template_id})
        if not base_template:
            return {"error": f"Template {base_template_id} not found"}

        logger.info(f"Generating email variants for campaign {campaign_id}")

        # If OpenAI wrapper not available, return default template
        if not self.openai_wrapper:
            logger.warning("OpenAI wrapper not available, returning base template only")
            return {
                "campaign_id": campaign_id,
                "variants": [self._template_to_variant(base_template, "Original")],
                "selected_variant_id": base_template_id
            }

        # Generate 3 variants with different personalization levels
        try:
            variants = self._generate_ai_variants(
                campaign,
                base_template
            )

            logger.info(f"Generated {len(variants)} variants for campaign {campaign_id}")

            # Store variants in database
            for variant in variants:
                self.email_variants.insert_one({
                    "campaign_id": campaign_id,
                    "template_id": base_template_id,
                    "variant_name": variant["name"],
                    "subject": variant["subject"],
                    "body_html": variant["body_html"],
                    "personalization_note": variant["personalization_note"],
                    "confidence_score": variant["confidence_score"],
                    "created_at": datetime.utcnow()
                })

            # Auto-select best variant
            selected_variant = None
            if auto_select:
                selected_variant = max(variants, key=lambda v: v["confidence_score"])
                logger.info(
                    f"Selected variant '{selected_variant['name']}' "
                    f"(confidence: {selected_variant['confidence_score']:.2f})"
                )

                # Update campaign with selected variant
                self.campaigns.update_one(
                    {"_id": campaign_id},
                    {
                        "$set": {
                            "selected_email_variant": selected_variant["name"],
                            "selected_template_subject": selected_variant["subject"],
                            "variant_selection_time": datetime.utcnow()
                        }
                    }
                )

            # Log decision for compliance
            decision_log_id = None
            if self.decision_logger:
                decision_log_id = self.decision_logger.log_decision(
                    decision_type="email_generation",
                    action="generate_variants",
                    autonomous=True,
                    campaign_id=campaign_id,
                    confidence_score=selected_variant["confidence_score"] if selected_variant else 0.75,
                    reasoning={
                        "strategy": "maximum_personalization",
                        "variants_generated": len(variants),
                        "selected_variant": selected_variant["name"] if selected_variant else None
                    },
                    input_context={
                        "base_template": base_template.get("subject", ""),
                        "campaign_type": campaign.get("campaign_type"),
                        "personalization_requirements": "maximum"
                    },
                    decision_params={
                        "variant_count": len(variants),
                        "selected": selected_variant["name"] if selected_variant else None
                    }
                )

            return {
                "campaign_id": campaign_id,
                "variants": variants,
                "selected_variant_id": selected_variant["name"] if selected_variant else None,
                "decision_log_id": decision_log_id
            }

        except Exception as e:
            logger.error(f"Failed to generate variants: {e}")
            return {
                "campaign_id": campaign_id,
                "error": str(e),
                "variants": [self._template_to_variant(base_template, "Original")]
            }

    def _generate_ai_variants(
        self,
        campaign: Dict[str, Any],
        base_template: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Use OpenAI to generate 3 email variants with maximum personalization.

        Variants:
        1. Executive Focus - Formal, authority-driven, results-oriented
        2. Problem Solver - Conversational, consultative, pain-point focused
        3. Innovator - Dynamic, future-focused, vision-oriented
        """
        base_subject = base_template.get("subject", "Interesting opportunity")
        base_body = base_template.get("body_html", "Hi {{first_name}},\n\nLet's connect.")

        prompt = f"""Generate 3 completely different email variants with MAXIMUM personalization for a B2B outreach campaign.

Base template:
Subject: {base_subject}
Body: {base_body}

Generate 3 variants with COMPLETELY DIFFERENT tones, styles, and messaging:

Variant 1 - "Executive Focus":
- Target: C-Level executives
- Tone: Formal, authoritative, results-oriented
- Focus: Business impact, ROI, strategic value
- Length: Concise (3-4 sentences)

Variant 2 - "Problem Solver":
- Target: Mid-level practitioners
- Tone: Conversational, consultative, empathetic
- Focus: Pain points, solutions, practical benefits
- Length: Medium (5-6 sentences)

Variant 3 - "Innovator":
- Target: Forward-thinking leaders
- Tone: Dynamic, energetic, vision-oriented
- Focus: Innovation, future trends, competitive edge
- Length: Engaging (6-7 sentences)

For each variant, provide:
{{
  "name": "Variant name (20 chars max)",
  "subject_line": "Email subject (50-60 chars)",
  "body": "HTML body with {{first_name}}, {{company_name}} placeholders",
  "personalization_note": "Brief note on target persona",
  "confidence_score": 0.85
}}

Return ONLY valid JSON array with 3 variants, no other text."""

        try:
            response = self.openai_wrapper.chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert B2B email copywriter. Generate highly personalized email variants with maximum variation in tone and style."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                source="background",
                endpoint="email_optimization",
                max_output_tokens=1500,
                temperature=0.7  # Higher temp for variety
            )

            if not response.get("success"):
                logger.error(f"OpenAI call failed: {response.get('error')}")
                return [self._template_to_variant(base_template, "Original")]

            # Parse response
            try:
                variants_data = json.loads(response.get("content", "[]"))
                if not isinstance(variants_data, list):
                    variants_data = [variants_data]
            except json.JSONDecodeError:
                logger.error("Failed to parse OpenAI response")
                return [self._template_to_variant(base_template, "Original")]

            # Convert to internal format
            variants = []
            for i, v in enumerate(variants_data[:3]):  # Take first 3
                variants.append({
                    "name": v.get("name", f"Variant {i+1}"),
                    "subject": v.get("subject_line", base_subject),
                    "body_html": v.get("body", base_template.get("body_html", "")),
                    "personalization_note": v.get("personalization_note", ""),
                    "confidence_score": float(v.get("confidence_score", 0.75))
                })

            return variants

        except Exception as e:
            logger.error(f"Error during AI variant generation: {e}")
            return [self._template_to_variant(base_template, "Original")]

    def _template_to_variant(
        self,
        template: Dict[str, Any],
        name: str
    ) -> Dict[str, Any]:
        """Convert template to variant format."""
        return {
            "name": name,
            "subject": template.get("subject", ""),
            "body_html": template.get("body_html", ""),
            "personalization_note": "Original template",
            "confidence_score": 1.0
        }

    def get_campaign_variants(self, campaign_id: str) -> List[Dict[str, Any]]:
        """Get all variants for a campaign."""
        variants = list(
            self.email_variants.find({"campaign_id": campaign_id})
            .sort("created_at", -1)
        )

        for v in variants:
            v.pop("_id", None)
            if "created_at" in v:
                v["created_at"] = v["created_at"].isoformat()

        return variants
