"""
A/B Test Analyzer Agent - Analyze campaign test results and recommend optimizations
"""

import logging
from typing import Any, Dict, List, Optional
import json

from .base_agent import BaseAgent, LEADS_PER_BATCH
from .schemas import (
    ABTestAnalyzerConfig,
    VariantPerformance,
    TestWinner,
    NextVariantSuggestion,
    ABTestAnalysis,
    ABTestAnalyzerResult,
)

logger = logging.getLogger(__name__)


class ABTestAnalyzerAgent(BaseAgent[ABTestAnalyzerResult]):
    """
    Agent that analyzes A/B test results and recommends next variants to test.
    Identifies what made winners win and suggests copy improvements.
    
    Input: Test results with control and variant performance data
    Output: Analysis of winners, reasoning, and suggestions for next tests
    """
    
    agent_name = "ab_test_analyzer"
    agent_description = "Analyzes A/B test results and recommends optimizations"
    output_model = ABTestAnalyzerResult
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.agent_config = ABTestAnalyzerConfig(**(config or {}))
    
    def get_system_prompt(self) -> str:
        config = self.agent_config
        metrics_str = ", ".join(config.focus_metrics)
        
        return f"""You are an expert A/B testing analyst specializing in email campaign optimization. Your task is to analyze test results and identify winning variants, explain what made them win, and suggest next experiments.

TEST ANALYSIS FOCUS:
- Analyze open rates, click rates, reply rates, and conversion rates
- Determine what elements made winners win (subject line, CTA, length, tone)
- Assess statistical significance of results
- Identify patterns and copy elements that resonate
- Suggest next variants to test based on winning patterns

SIGNIFICANCE CRITERIA:
- Minimum sample size: {config.minimum_sample_size} emails per variant
- Confidence threshold: {config.significance_threshold * 100}%
- Focus metrics: {metrics_str}

ELEMENTS TO ANALYZE FOR WINNERS:
1. SUBJECT LINE: Length, specificity, emotional trigger, curiosity gap
2. CTA: Ease of commitment, clarity, positioning (early/late in email)
3. EMAIL LENGTH: Word count, paragraph structure, readability
4. TONE: Formal vs casual, urgency level, personalization depth
5. STRUCTURE: Story arc, proof elements, social proof, scarcity

OUTPUT FORMAT (JSON):
{{
    "tests_analyzed": [
        {{
            "test_name": "Subject Line Test V3",
            "control_variant": {{
                "variant_id": "control",
                "variant_name": "Control",
                "emails_sent": 500,
                "opens": 125,
                "clicks": 38,
                "replies": 12,
                "conversions": 5,
                "open_rate": 0.25,
                "click_rate": 0.076,
                "reply_rate": 0.024,
                "conversion_rate": 0.01,
                "subject_line": "Quick question about your sales process",
                "cta_text": "Want to talk?",
                "email_length": "medium"
            }},
            "test_variants": [
                {{
                    "variant_id": "A",
                    "variant_name": "Curiosity Gap Subject",
                    "emails_sent": 500,
                    "opens": 175,
                    "clicks": 56,
                    "replies": 18,
                    "conversions": 8,
                    "open_rate": 0.35,
                    "click_rate": 0.112,
                    "reply_rate": 0.036,
                    "conversion_rate": 0.016,
                    "subject_line": "One thing your competitors are doing (that you're not)",
                    "cta_text": "See what we found",
                    "email_length": "medium"
                }}
            ],
            "test_winner": {{
                "winner_id": "A",
                "winner_name": "Curiosity Gap Subject",
                "metrics_won": ["open_rate", "click_rate", "reply_rate", "conversion_rate"],
                "primary_win_reason": "Curiosity gap subject line drove 40% higher opens",
                "detailed_reasoning": "The subject 'One thing your competitors are doing' created curiosity without being pushy. Recipients wanted to see what they were missing. This carried through to higher engagement on the entire email.",
                "improvement_over_control": {{
                    "open_rate": 0.40,
                    "click_rate": 0.47,
                    "reply_rate": 0.50,
                    "conversion_rate": 0.60
                }},
                "statistical_confidence": 0.98
            }},
            "is_statistically_significant": true,
            "recommended_copy_changes": [
                "Use curiosity gap approach in subject lines going forward",
                "Shorten CTAs from questions to action statements",
                "Test competitor comparison angle in email body"
            ],
            "next_variant_suggestions": [
                {{
                    "experiment_name": "CTA Positioning Test",
                    "variant_a_description": "CTA in first paragraph (early commitment ask)",
                    "variant_b_description": "CTA in final paragraph (after building case)",
                    "expected_improvement": "15-20% higher engagement if CTA positioning matters",
                    "hypothesis": "Readers need more context before committing; late CTA may improve conversion",
                    "why_this_variant": "Winner used 'See what we found' CTA - want to test if CTA placement affects response rates"
                }}
            ]
        }}
    ],
    "total_tests": 1,
    "winners_identified": 1,
    "statistically_significant_count": 1
}}"""
    
    def build_prompt(self, input_data: Any) -> str:
        """Build the prompt for analyzing A/B tests."""
        tests = []
        
        if isinstance(input_data, list):
            tests = input_data
        elif isinstance(input_data, dict):
            tests = input_data.get("tests", [input_data])
        
        # Format tests for analysis
        tests_formatted = []
        for i, test in enumerate(tests):
            test_name = test.get('test_name', f'Test {i+1}')
            control = test.get('control_variant', {})
            variants = test.get('test_variants', [])
            
            control_str = f"""Control Variant:
  - Name: {control.get('variant_name', 'Control')}
  - Emails Sent: {control.get('emails_sent', 0)}
  - Opens: {control.get('opens', 0)} ({control.get('open_rate', 0)*100:.1f}%)
  - Clicks: {control.get('clicks', 0)} ({control.get('click_rate', 0)*100:.1f}%)
  - Replies: {control.get('replies', 0)} ({control.get('reply_rate', 0)*100:.1f}%)
  - Conversions: {control.get('conversions', 0)} ({control.get('conversion_rate', 0)*100:.1f}%)
  - Subject: {control.get('subject_line', 'Unknown')}
  - CTA: {control.get('cta_text', 'Unknown')}
  - Length: {control.get('email_length', 'unknown')}"""
            
            variants_str = ""
            for j, variant in enumerate(variants):
                variants_str += f"""
Variant {chr(65+j)}:
  - Name: {variant.get('variant_name', f'Variant {chr(65+j)}')}
  - Emails Sent: {variant.get('emails_sent', 0)}
  - Opens: {variant.get('opens', 0)} ({variant.get('open_rate', 0)*100:.1f}%)
  - Clicks: {variant.get('clicks', 0)} ({variant.get('click_rate', 0)*100:.1f}%)
  - Replies: {variant.get('replies', 0)} ({variant.get('reply_rate', 0)*100:.1f}%)
  - Conversions: {variant.get('conversions', 0)} ({variant.get('conversion_rate', 0)*100:.1f}%)
  - Subject: {variant.get('subject_line', 'Unknown')}
  - CTA: {variant.get('cta_text', 'Unknown')}
  - Length: {variant.get('email_length', 'unknown')}"""
            
            test_str = f"""Test {i+1}: {test_name}

{control_str}{variants_str}"""
            
            tests_formatted.append(test_str)
        
        tests_text = "\n\n".join(tests_formatted)
        config = self.agent_config
        
        prompt = f"""Analyze the following {len(tests_formatted)} A/B tests:

{tests_text}

**Analysis Parameters:**
- Minimum sample size for validity: {config.minimum_sample_size}
- Statistical significance threshold: {config.significance_threshold * 100}%
- Primary metrics to focus on: {', '.join(config.focus_metrics)}

**Requirements:**
1. For each test, identify the winning variant
2. Analyze WHAT made the winner win (focus on subject line, CTA, length, tone)
3. Explain the reasoning for why this variant performed better
4. Calculate percentage improvements over control for each metric
5. Assess whether results are statistically significant
6. Provide recommended copy changes based on winners
7. Suggest 2-3 next variants to test based on winning patterns
8. For each next variant, provide testing hypothesis and expected improvement

Return analysis for all {len(tests_formatted)} tests in the specified JSON format."""
        
        return prompt
    
    def parse_response(self, response_text: str) -> ABTestAnalyzerResult:
        """Parse the AI response into ABTestAnalyzerResult."""
        data = self._extract_json_from_response(response_text)
        
        tests_analyzed = []
        winners_identified = 0
        statistically_significant_count = 0
        
        for test_data in data.get("tests_analyzed", []):
            try:
                # Parse control variant
                control_data = test_data.get("control_variant", {})
                control = VariantPerformance(
                    variant_id=control_data.get("variant_id", "control"),
                    variant_name=control_data.get("variant_name", "Control"),
                    emails_sent=control_data.get("emails_sent", 0),
                    opens=control_data.get("opens", 0),
                    clicks=control_data.get("clicks", 0),
                    replies=control_data.get("replies", 0),
                    conversions=control_data.get("conversions", 0),
                    open_rate=control_data.get("open_rate", 0.0),
                    click_rate=control_data.get("click_rate", 0.0),
                    reply_rate=control_data.get("reply_rate", 0.0),
                    conversion_rate=control_data.get("conversion_rate", 0.0),
                    subject_line=control_data.get("subject_line", ""),
                    cta_text=control_data.get("cta_text", ""),
                    email_length=control_data.get("email_length", "")
                )
                
                # Parse test variants
                test_variants = []
                for variant_data in test_data.get("test_variants", []):
                    variant = VariantPerformance(
                        variant_id=variant_data.get("variant_id", ""),
                        variant_name=variant_data.get("variant_name", ""),
                        emails_sent=variant_data.get("emails_sent", 0),
                        opens=variant_data.get("opens", 0),
                        clicks=variant_data.get("clicks", 0),
                        replies=variant_data.get("replies", 0),
                        conversions=variant_data.get("conversions", 0),
                        open_rate=variant_data.get("open_rate", 0.0),
                        click_rate=variant_data.get("click_rate", 0.0),
                        reply_rate=variant_data.get("reply_rate", 0.0),
                        conversion_rate=variant_data.get("conversion_rate", 0.0),
                        subject_line=variant_data.get("subject_line", ""),
                        cta_text=variant_data.get("cta_text", ""),
                        email_length=variant_data.get("email_length", "")
                    )
                    test_variants.append(variant)
                
                # Parse winner
                winner_data = test_data.get("test_winner", {})
                winner = TestWinner(
                    winner_id=winner_data.get("winner_id", ""),
                    winner_name=winner_data.get("winner_name", ""),
                    metrics_won=winner_data.get("metrics_won", []),
                    primary_win_reason=winner_data.get("primary_win_reason", ""),
                    detailed_reasoning=winner_data.get("detailed_reasoning", ""),
                    improvement_over_control=winner_data.get("improvement_over_control", {}),
                    statistical_confidence=winner_data.get("statistical_confidence", 0.0)
                )
                winners_identified += 1
                
                # Parse next variant suggestions
                next_variants = []
                for next_data in test_data.get("next_variant_suggestions", []):
                    next_variant = NextVariantSuggestion(
                        experiment_name=next_data.get("experiment_name", ""),
                        variant_a_description=next_data.get("variant_a_description", ""),
                        variant_b_description=next_data.get("variant_b_description", ""),
                        expected_improvement=next_data.get("expected_improvement", ""),
                        hypothesis=next_data.get("hypothesis", ""),
                        why_this_variant=next_data.get("why_this_variant", "")
                    )
                    next_variants.append(next_variant)
                
                # Track statistical significance
                is_significant = test_data.get("is_statistically_significant", False)
                if is_significant:
                    statistically_significant_count += 1
                
                # Create test analysis
                test_analysis = ABTestAnalysis(
                    test_name=test_data.get("test_name", ""),
                    control_variant=control,
                    test_variants=test_variants,
                    test_winner=winner,
                    is_statistically_significant=is_significant,
                    recommended_copy_changes=test_data.get("recommended_copy_changes", []),
                    next_variant_suggestions=next_variants
                )
                tests_analyzed.append(test_analysis)
            except Exception as e:
                logger.warning(f"Failed to parse test analysis: {e}")
                continue
        
        return ABTestAnalyzerResult(
            tests_analyzed=tests_analyzed,
            total_tests=len(tests_analyzed),
            winners_identified=winners_identified,
            statistically_significant_count=statistically_significant_count
        )
    
    async def analyze_test_results(
        self,
        control: Dict[str, Any],
        variants: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze A/B test results and identify winner.
        
        Args:
            control: Control variant performance data
            variants: List of variant performance data
            
        Returns:
            Dict with winner analysis and reasoning
        """
        # Calculate which metric won on
        metrics_won = []
        
        for metric in self.agent_config.focus_metrics:
            control_metric = control.get(f"{metric}", 0)
            max_variant_metric = max((v.get(f"{metric}", 0) for v in variants), default=0)
            
            if max_variant_metric > control_metric:
                metrics_won.append(metric)
        
        return {
            "metrics_won": metrics_won,
            "analysis": "Test analysis available via full agent execution"
        }
    
    async def suggest_next_variants(
        self,
        winner: Dict[str, Any],
        campaign_context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Suggest next variants to test based on winner patterns.
        
        Args:
            winner: Winning variant data
            campaign_context: Campaign context and historical data
            
        Returns:
            List of suggested variants to test next
        """
        suggestions = [
            {
                "experiment_name": "Follow-on Test Based on Winner",
                "variant_a_description": "Test derived from winning element",
                "variant_b_description": "Alternative based on winner insights",
                "hypothesis": "Building on winner success",
                "expected_improvement": "Available via full agent analysis"
            }
        ]
        
        return suggestions
    
    def analyze_tests_batch(self, tests: List[Dict[str, Any]]) -> ABTestAnalyzerResult:
        """
        Analyze a batch of A/B tests.
        
        Args:
            tests: List of test dicts with control and variant data
            
        Returns:
            ABTestAnalyzerResult with analysis and recommendations
        """
        result = self.execute({"tests": tests}, use_web_search=False)
        if result.success and result.data:
            return ABTestAnalyzerResult(**result.data)
        return ABTestAnalyzerResult()
