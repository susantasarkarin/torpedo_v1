"""
Intelligence API Router
Email thread analysis and conversation intelligence
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..database import get_database
from ..intelligence.thread_analyzer import ThreadAnalyzer, ThreadAnalyzerService

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


@router.get("/threads/{thread_id}/analyze")
async def analyze_thread(
    thread_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Comprehensive analysis of email thread
    
    Returns summary, sentiment, action items, and key points
    """
    try:
        analyzer = ThreadAnalyzer(db)
        analysis = await analyzer.analyze_thread(thread_id)
        
        return analysis
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/leads/{lead_id}/threads")
async def get_lead_thread_summary(
    lead_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get aggregated summary of all threads for a lead
    """
    try:
        analyzer = ThreadAnalyzer(db)
        summary = await analyzer.get_thread_summary_for_lead(lead_id)
        
        return summary
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads/active")
async def analyze_active_threads(
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Analyze all active conversation threads
    
    Returns analysis for each active thread
    """
    try:
        service = ThreadAnalyzerService(db)
        analyses = await service.analyze_all_active_threads()
        
        return {
            "analyses": analyses,
            "total_threads": len(analyses),
            "analyzed_at": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads/needs-attention")
async def get_threads_needing_attention(
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get threads that need immediate attention
    
    Flags conversations that are stuck, declining sentiment, or have unanswered questions
    """
    try:
        service = ThreadAnalyzerService(db)
        threads = await service.get_threads_needing_attention()
        
        return {
            "threads": threads,
            "count": len(threads),
            "priority_levels": {
                "high": len([t for t in threads if t['priority'] >= 5]),
                "medium": len([t for t in threads if 2 <= t['priority'] < 5]),
                "low": len([t for t in threads if t['priority'] < 2])
            },
            "generated_at": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads/{thread_id}/sentiment")
async def get_thread_sentiment(
    thread_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get sentiment analysis for thread
    """
    try:
        analyzer = ThreadAnalyzer(db)
        analysis = await analyzer.analyze_thread(thread_id)
        
        return {
            "thread_id": thread_id,
            "sentiment": analysis.get('sentiment', {}),
            "analyzed_at": analysis.get('analyzed_at')
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads/{thread_id}/action-items")
async def get_thread_action_items(
    thread_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Extract action items from thread
    """
    try:
        analyzer = ThreadAnalyzer(db)
        
        # Fetch thread
        thread = await db.threads.find_one({'_id': thread_id})
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        messages = thread.get('messages', [])
        action_items = analyzer.extract_action_items(thread_id, messages)
        
        return {
            "thread_id": thread_id,
            "action_items": action_items,
            "count": len(action_items),
            "extracted_at": datetime.now().isoformat()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/sentiment-trends")
async def get_sentiment_trends(
    days: int = Query(30, ge=1, le=365),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get sentiment trends across all conversations
    """
    try:
        service = ThreadAnalyzerService(db)
        analyses = await service.analyze_all_active_threads()
        
        # Aggregate sentiment data
        sentiment_counts = {"positive": 0, "neutral": 0, "negative": 0}
        for analysis in analyses:
            overall_sentiment = analysis.get('sentiment', {}).get('overall', 'neutral')
            sentiment_counts[overall_sentiment] = sentiment_counts.get(overall_sentiment, 0) + 1
        
        total = len(analyses)
        
        return {
            "sentiment_distribution": {
                "positive": {
                    "count": sentiment_counts['positive'],
                    "percentage": (sentiment_counts['positive'] / total * 100) if total > 0 else 0
                },
                "neutral": {
                    "count": sentiment_counts['neutral'],
                    "percentage": (sentiment_counts['neutral'] / total * 100) if total > 0 else 0
                },
                "negative": {
                    "count": sentiment_counts['negative'],
                    "percentage": (sentiment_counts['negative'] / total * 100) if total > 0 else 0
                }
            },
            "total_threads": total,
            "period_days": days,
            "generated_at": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/engagement-overview")
async def get_engagement_overview(
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get overall engagement metrics across all threads
    """
    try:
        service = ThreadAnalyzerService(db)
        analyses = await service.analyze_all_active_threads()
        
        # Aggregate engagement data
        engagement_levels = {"high": 0, "medium": 0, "low": 0}
        total_messages = 0
        
        for analysis in analyses:
            level = analysis.get('engagement_level', {}).get('level', 'low')
            engagement_levels[level] = engagement_levels.get(level, 0) + 1
            total_messages += analysis.get('message_count', 0)
        
        total_threads = len(analyses)
        
        return {
            "engagement_distribution": {
                "high": {
                    "count": engagement_levels['high'],
                    "percentage": (engagement_levels['high'] / total_threads * 100) if total_threads > 0 else 0
                },
                "medium": {
                    "count": engagement_levels['medium'],
                    "percentage": (engagement_levels['medium'] / total_threads * 100) if total_threads > 0 else 0
                },
                "low": {
                    "count": engagement_levels['low'],
                    "percentage": (engagement_levels['low'] / total_threads * 100) if total_threads > 0 else 0
                }
            },
            "total_threads": total_threads,
            "total_messages": total_messages,
            "avg_messages_per_thread": (total_messages / total_threads) if total_threads > 0 else 0,
            "generated_at": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/stages")
async def get_conversation_stages(
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Get distribution of conversations across different stages
    """
    try:
        service = ThreadAnalyzerService(db)
        analyses = await service.analyze_all_active_threads()
        
        # Count by stage
        stage_counts = {}
        for analysis in analyses:
            stage = analysis.get('conversation_flow', {}).get('stage', 'unknown')
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        
        return {
            "stages": stage_counts,
            "total_conversations": len(analyses),
            "generated_at": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
