"""
SEO Monitoring Router for Torpedo CRM
=====================================

This router provides AI-powered SEO monitoring and analysis for websites
managed through the Marketing module.

To integrate, add this to your backend:
1. Copy this file to backend/routers/seo_monitoring.py
2. Add to main.py: from routers import seo_monitoring
3. Add: app.include_router(seo_monitoring.router)
4. Install: pip install google-generativeai textstat readability-lxml

Environment Variables:
- GEMINI_API_KEY: For AI-powered analysis
- OPENAI_API_KEY: Fallback AI provider
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from enum import Enum
import re
import json

router = APIRouter(prefix="/api/seo", tags=["SEO Monitoring"])

# ============================================================================
# MODELS
# ============================================================================

class SEOScore(BaseModel):
    overall: int = Field(..., ge=0, le=100, description="Overall SEO score 0-100")
    title: int = Field(..., ge=0, le=100)
    description: int = Field(..., ge=0, le=100)
    keywords: int = Field(..., ge=0, le=100)
    content: int = Field(..., ge=0, le=100)
    readability: int = Field(..., ge=0, le=100)
    technical: int = Field(..., ge=0, le=100)

class SEOIssue(BaseModel):
    severity: str  # 'critical', 'warning', 'info'
    category: str  # 'title', 'description', 'keywords', 'content', 'technical'
    message: str
    recommendation: str
    page_slug: Optional[str] = None

class SEORecommendation(BaseModel):
    priority: int  # 1-5, 1 being highest
    category: str
    title: str
    description: str
    implementation: str
    estimated_impact: str  # 'high', 'medium', 'low'

class PageSEOAnalysis(BaseModel):
    page_slug: str
    title: str
    analyzed_at: datetime
    score: SEOScore
    issues: List[SEOIssue]
    recommendations: List[SEORecommendation]
    keyword_analysis: Dict[str, Any]
    readability_metrics: Dict[str, Any]

class WebsiteSEOReport(BaseModel):
    website_id: str
    domain: str
    analyzed_at: datetime
    overall_score: int
    page_scores: Dict[str, int]
    total_issues: int
    critical_issues: int
    top_recommendations: List[SEORecommendation]
    keyword_coverage: Dict[str, Any]
    competitor_comparison: Optional[Dict[str, Any]] = None

class ContentAnalysisRequest(BaseModel):
    content: str
    focus_keyword: Optional[str] = None
    target_keywords: Optional[List[str]] = None
    page_type: str = "page"  # 'home', 'page', 'blog', 'service'

class ContentAnalysisResponse(BaseModel):
    score: int
    readability_grade: str
    keyword_density: Dict[str, float]
    issues: List[SEOIssue]
    recommendations: List[str]
    ai_suggestions: Optional[str] = None

class SEOTrackingEntry(BaseModel):
    website_id: str
    page_slug: str
    date: datetime
    score: int
    issues_count: int
    keywords_tracked: List[str]

# ============================================================================
# SEO ANALYSIS FUNCTIONS
# ============================================================================

def analyze_title(title: str, focus_keyword: Optional[str] = None) -> Dict[str, Any]:
    """Analyze page title for SEO"""
    issues = []
    score = 100
    
    # Length check (optimal: 50-60 chars)
    if len(title) < 30:
        issues.append({
            "severity": "warning",
            "message": f"Title is too short ({len(title)} chars). Aim for 50-60 characters.",
            "recommendation": "Add more descriptive keywords to your title."
        })
        score -= 15
    elif len(title) > 60:
        issues.append({
            "severity": "warning", 
            "message": f"Title is too long ({len(title)} chars). Google may truncate it.",
            "recommendation": "Shorten your title to under 60 characters."
        })
        score -= 10
    
    # Focus keyword check
    if focus_keyword:
        if focus_keyword.lower() not in title.lower():
            issues.append({
                "severity": "critical",
                "message": f"Focus keyword '{focus_keyword}' not found in title.",
                "recommendation": f"Include '{focus_keyword}' near the beginning of your title."
            })
            score -= 25
        elif not title.lower().startswith(focus_keyword.lower()[:20]):
            issues.append({
                "severity": "info",
                "message": "Focus keyword should ideally appear at the beginning of the title.",
                "recommendation": "Consider restructuring the title to lead with your focus keyword."
            })
            score -= 5
    
    # Special characters check
    if '|' in title or '-' in title:
        pass  # Good - using separator
    else:
        issues.append({
            "severity": "info",
            "message": "Consider adding a brand separator (| or -) to your title.",
            "recommendation": "Format: 'Primary Keyword | Brand Name'"
        })
    
    return {"score": max(0, score), "issues": issues}

def analyze_description(description: str, focus_keyword: Optional[str] = None) -> Dict[str, Any]:
    """Analyze meta description for SEO"""
    issues = []
    score = 100
    
    # Length check (optimal: 150-160 chars)
    if len(description) < 120:
        issues.append({
            "severity": "warning",
            "message": f"Description is too short ({len(description)} chars). Aim for 150-160 characters.",
            "recommendation": "Expand your description with compelling copy and keywords."
        })
        score -= 15
    elif len(description) > 160:
        issues.append({
            "severity": "warning",
            "message": f"Description is too long ({len(description)} chars). Google may truncate it.",
            "recommendation": "Shorten to under 160 characters while keeping it compelling."
        })
        score -= 10
    
    # Focus keyword check
    if focus_keyword and focus_keyword.lower() not in description.lower():
        issues.append({
            "severity": "critical",
            "message": f"Focus keyword '{focus_keyword}' not found in description.",
            "recommendation": f"Include '{focus_keyword}' naturally in your description."
        })
        score -= 20
    
    # Call to action check
    cta_words = ['learn', 'discover', 'get', 'find', 'try', 'start', 'book', 'contact', 'call']
    has_cta = any(word in description.lower() for word in cta_words)
    if not has_cta:
        issues.append({
            "severity": "info",
            "message": "Description lacks a clear call-to-action.",
            "recommendation": "Add action words like 'Learn more', 'Get started', 'Discover'."
        })
        score -= 5
    
    return {"score": max(0, score), "issues": issues}

def analyze_content(content: str, focus_keyword: Optional[str] = None, 
                   target_keywords: Optional[List[str]] = None) -> Dict[str, Any]:
    """Analyze page content for SEO"""
    issues = []
    score = 100
    
    # Word count
    words = content.split()
    word_count = len(words)
    
    if word_count < 300:
        issues.append({
            "severity": "critical",
            "message": f"Content is too thin ({word_count} words). Aim for at least 500 words.",
            "recommendation": "Add more comprehensive, valuable content to the page."
        })
        score -= 25
    elif word_count < 500:
        issues.append({
            "severity": "warning",
            "message": f"Content could be longer ({word_count} words). Aim for 500+ words.",
            "recommendation": "Consider adding more detail, examples, or FAQs."
        })
        score -= 10
    
    # Keyword density
    keyword_density = {}
    if focus_keyword:
        focus_count = content.lower().count(focus_keyword.lower())
        density = (focus_count / word_count) * 100 if word_count > 0 else 0
        keyword_density[focus_keyword] = round(density, 2)
        
        if density < 0.5:
            issues.append({
                "severity": "warning",
                "message": f"Focus keyword density is low ({density:.1f}%). Aim for 1-2%.",
                "recommendation": f"Use '{focus_keyword}' more naturally throughout the content."
            })
            score -= 15
        elif density > 3:
            issues.append({
                "severity": "warning",
                "message": f"Focus keyword density is high ({density:.1f}%). Risk of keyword stuffing.",
                "recommendation": "Reduce keyword usage and use synonyms instead."
            })
            score -= 10
    
    # Target keywords check
    if target_keywords:
        missing_keywords = []
        for kw in target_keywords:
            if kw.lower() not in content.lower():
                missing_keywords.append(kw)
            else:
                kw_count = content.lower().count(kw.lower())
                density = (kw_count / word_count) * 100 if word_count > 0 else 0
                keyword_density[kw] = round(density, 2)
        
        if missing_keywords:
            issues.append({
                "severity": "info",
                "message": f"Target keywords not found: {', '.join(missing_keywords[:3])}",
                "recommendation": "Consider including these keywords where relevant."
            })
            score -= 5
    
    # Heading structure (simplified check)
    h1_count = content.lower().count('<h1')
    h2_count = content.lower().count('<h2')
    
    if h1_count == 0:
        issues.append({
            "severity": "critical",
            "message": "No H1 heading found on the page.",
            "recommendation": "Add a single H1 heading containing your focus keyword."
        })
        score -= 20
    elif h1_count > 1:
        issues.append({
            "severity": "warning",
            "message": f"Multiple H1 headings found ({h1_count}). Use only one H1.",
            "recommendation": "Keep one H1 and change others to H2 or H3."
        })
        score -= 10
    
    if h2_count == 0:
        issues.append({
            "severity": "warning",
            "message": "No H2 headings found. Use subheadings to structure content.",
            "recommendation": "Break content into sections with H2 headings."
        })
        score -= 10
    
    # Readability (simplified Flesch-Kincaid approximation)
    sentences = len(re.findall(r'[.!?]+', content))
    avg_sentence_length = word_count / max(sentences, 1)
    
    readability_score = 100
    if avg_sentence_length > 25:
        issues.append({
            "severity": "warning",
            "message": f"Average sentence length is high ({avg_sentence_length:.0f} words).",
            "recommendation": "Use shorter sentences for better readability."
        })
        readability_score -= 15
    
    return {
        "score": max(0, score),
        "issues": issues,
        "keyword_density": keyword_density,
        "word_count": word_count,
        "readability_score": readability_score,
        "avg_sentence_length": round(avg_sentence_length, 1)
    }

def calculate_overall_score(title_score: int, desc_score: int, content_score: int,
                           technical_score: int = 80) -> SEOScore:
    """Calculate overall SEO score from component scores"""
    overall = int((title_score * 0.15 + desc_score * 0.15 + 
                  content_score * 0.5 + technical_score * 0.2))
    
    return SEOScore(
        overall=overall,
        title=title_score,
        description=desc_score,
        keywords=content_score,  # Using content score as proxy
        content=content_score,
        readability=content_score,  # Could be separate
        technical=technical_score
    )

# ============================================================================
# API ENDPOINTS
# ============================================================================

@router.post("/analyze/content", response_model=ContentAnalysisResponse)
async def analyze_content_endpoint(request: ContentAnalysisRequest):
    """
    Analyze content for SEO optimization.
    Returns score, issues, and AI-powered recommendations.
    """
    content_analysis = analyze_content(
        request.content,
        request.focus_keyword,
        request.target_keywords
    )
    
    return ContentAnalysisResponse(
        score=content_analysis["score"],
        readability_grade=get_readability_grade(content_analysis.get("readability_score", 75)),
        keyword_density=content_analysis.get("keyword_density", {}),
        issues=[SEOIssue(
            severity=i["severity"],
            category="content",
            message=i["message"],
            recommendation=i["recommendation"]
        ) for i in content_analysis["issues"]],
        recommendations=[i["recommendation"] for i in content_analysis["issues"]],
        ai_suggestions=None  # Will be populated by AI agent
    )

@router.post("/analyze/page")
async def analyze_page(
    website_id: str,
    page_slug: str,
    title: str,
    description: str,
    content: str,
    focus_keyword: Optional[str] = None,
    target_keywords: Optional[List[str]] = None
) -> PageSEOAnalysis:
    """
    Perform comprehensive SEO analysis on a page.
    """
    # Analyze components
    title_result = analyze_title(title, focus_keyword)
    desc_result = analyze_description(description, focus_keyword)
    content_result = analyze_content(content, focus_keyword, target_keywords)
    
    # Combine issues
    all_issues = []
    for issue in title_result["issues"]:
        all_issues.append(SEOIssue(
            severity=issue["severity"],
            category="title",
            message=issue["message"],
            recommendation=issue["recommendation"],
            page_slug=page_slug
        ))
    for issue in desc_result["issues"]:
        all_issues.append(SEOIssue(
            severity=issue["severity"],
            category="description",
            message=issue["message"],
            recommendation=issue["recommendation"],
            page_slug=page_slug
        ))
    for issue in content_result["issues"]:
        all_issues.append(SEOIssue(
            severity=issue["severity"],
            category="content",
            message=issue["message"],
            recommendation=issue["recommendation"],
            page_slug=page_slug
        ))
    
    # Calculate overall score
    score = calculate_overall_score(
        title_result["score"],
        desc_result["score"],
        content_result["score"]
    )
    
    # Generate recommendations
    recommendations = generate_recommendations(all_issues)
    
    return PageSEOAnalysis(
        page_slug=page_slug,
        title=title,
        analyzed_at=datetime.utcnow(),
        score=score,
        issues=all_issues,
        recommendations=recommendations,
        keyword_analysis={
            "focus_keyword": focus_keyword,
            "density": content_result.get("keyword_density", {}),
            "word_count": content_result.get("word_count", 0)
        },
        readability_metrics={
            "score": content_result.get("readability_score", 0),
            "avg_sentence_length": content_result.get("avg_sentence_length", 0),
            "grade": get_readability_grade(content_result.get("readability_score", 75))
        }
    )

@router.get("/report/{website_id}")
async def get_seo_report(website_id: str) -> WebsiteSEOReport:
    """
    Get comprehensive SEO report for a website.
    Analyzes all pages and provides actionable insights.
    """
    # This would fetch from database - returning mock for now
    return WebsiteSEOReport(
        website_id=website_id,
        domain="surveyfieldwork.com",
        analyzed_at=datetime.utcnow(),
        overall_score=78,
        page_scores={
            "home": 82,
            "about": 75,
            "services": 80,
            "blog": 70
        },
        total_issues=12,
        critical_issues=2,
        top_recommendations=[
            SEORecommendation(
                priority=1,
                category="content",
                title="Add more content to key pages",
                description="Several pages have thin content under 500 words.",
                implementation="Expand About and Services pages with detailed information.",
                estimated_impact="high"
            ),
            SEORecommendation(
                priority=2,
                category="keywords",
                title="Optimize focus keywords",
                description="Focus keywords are missing from some page titles.",
                implementation="Review and update meta titles to include target keywords.",
                estimated_impact="high"
            )
        ],
        keyword_coverage={
            "market research": {"pages": 4, "density_avg": 1.5},
            "survey fieldwork": {"pages": 3, "density_avg": 1.2},
            "audience sampling": {"pages": 2, "density_avg": 0.8}
        }
    )

@router.get("/tracking/{website_id}")
async def get_seo_tracking(
    website_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> List[SEOTrackingEntry]:
    """
    Get historical SEO tracking data for trend analysis.
    """
    # Would fetch from database - returning mock data
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=30)
    if not end_date:
        end_date = datetime.utcnow()
    
    # Mock historical data
    entries = []
    current = start_date
    score = 70
    while current <= end_date:
        entries.append(SEOTrackingEntry(
            website_id=website_id,
            page_slug="home",
            date=current,
            score=min(100, score + (current - start_date).days // 7 * 2),
            issues_count=max(0, 15 - (current - start_date).days // 7),
            keywords_tracked=["market research", "survey fieldwork"]
        ))
        current += timedelta(days=7)
    
    return entries

@router.post("/ai/optimize")
async def ai_optimize_content(
    content: str,
    focus_keyword: str,
    target_audience: str = "business professionals",
    content_type: str = "service page"
):
    """
    Use AI to suggest content optimizations.
    Integrates with Gemini/OpenAI for intelligent recommendations.
    """
    # This would call the AI agent - returning placeholder
    return {
        "suggestions": [
            "Consider adding a FAQ section to address common queries about " + focus_keyword,
            "Include statistics or case studies to build credibility",
            "Add internal links to related service pages",
            "Consider adding customer testimonials specific to this service"
        ],
        "optimized_title": f"{focus_keyword.title()} Services | Survey Fieldwork - Expert Solutions",
        "optimized_description": f"Discover our {focus_keyword} services. Survey Fieldwork provides comprehensive solutions for {target_audience}. Get a free consultation today.",
        "keyword_suggestions": [
            focus_keyword + " services",
            focus_keyword + " solutions",
            "best " + focus_keyword,
            focus_keyword + " for business"
        ]
    }

@router.post("/schedule-analysis")
async def schedule_seo_analysis(
    website_id: str,
    frequency: str = "weekly",  # 'daily', 'weekly', 'monthly'
    background_tasks: BackgroundTasks = None
):
    """
    Schedule recurring SEO analysis for a website.
    Results are stored and used for trend tracking.
    """
    # Would set up a Celery task - returning confirmation
    return {
        "message": f"SEO analysis scheduled for website {website_id}",
        "frequency": frequency,
        "next_analysis": datetime.utcnow() + timedelta(days=1 if frequency == "daily" else 7),
        "enabled": True
    }

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_readability_grade(score: int) -> str:
    """Convert readability score to grade"""
    if score >= 90:
        return "A (Very Easy)"
    elif score >= 80:
        return "B (Easy)"
    elif score >= 70:
        return "C (Fairly Easy)"
    elif score >= 60:
        return "D (Standard)"
    elif score >= 50:
        return "E (Fairly Difficult)"
    else:
        return "F (Difficult)"

def generate_recommendations(issues: List[SEOIssue]) -> List[SEORecommendation]:
    """Generate prioritized recommendations from issues"""
    recommendations = []
    
    # Group by severity
    critical = [i for i in issues if i.severity == "critical"]
    warnings = [i for i in issues if i.severity == "warning"]
    
    priority = 1
    for issue in critical[:3]:  # Top 3 critical
        recommendations.append(SEORecommendation(
            priority=priority,
            category=issue.category,
            title=f"Fix: {issue.message[:50]}...",
            description=issue.message,
            implementation=issue.recommendation,
            estimated_impact="high"
        ))
        priority += 1
    
    for issue in warnings[:2]:  # Top 2 warnings
        recommendations.append(SEORecommendation(
            priority=priority,
            category=issue.category,
            title=f"Improve: {issue.message[:50]}...",
            description=issue.message,
            implementation=issue.recommendation,
            estimated_impact="medium"
        ))
        priority += 1
    
    return recommendations
