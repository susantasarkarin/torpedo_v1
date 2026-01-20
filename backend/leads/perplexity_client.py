"""
PERPLEXITY CLIENT STUB
======================
Perplexity has been removed from the system in favor of OpenAI web search.
This stub file exists to prevent import errors from existing endpoints.
All functions return disabled/error status gracefully.
"""

def is_perplexity_enabled() -> bool:
    """Perplexity is disabled - use OpenAI web search instead."""
    return False

def get_perplexity_settings() -> dict:
    """Return empty settings - Perplexity removed."""
    return {
        "hourly_limit": 0,
        "daily_limit": 0,
        "default_model": None,
        "enabled": False,
        "message": "Perplexity has been removed. Use OpenAI web search for discovery."
    }

def check_rate_limit() -> tuple:
    """Always return not allowed - Perplexity disabled."""
    return False, "Perplexity has been removed. Use OpenAI web search for discovery."

async def discover_companies(*args, **kwargs) -> dict:
    """Perplexity disabled - use OpenAI web search instead."""
    return {
        "success": False,
        "error": "Perplexity has been removed. Use OpenAI web search for company discovery.",
        "content": "",
        "companies": []
    }

async def discover_contacts_direct(*args, **kwargs) -> dict:
    """Perplexity disabled - use OpenAI web search instead."""
    return {
        "success": False,
        "error": "Perplexity has been removed. Use OpenAI web search for contact discovery.",
        "contacts": []
    }

async def discover_roles(*args, **kwargs) -> dict:
    """Perplexity disabled - use OpenAI web search instead."""
    return {
        "success": False,
        "error": "Perplexity has been removed. Use OpenAI web search for role discovery.",
        "roles": []
    }

async def research_company(*args, **kwargs) -> dict:
    """Perplexity disabled - use OpenAI web search instead."""
    return {
        "success": False,
        "error": "Perplexity has been removed. Use OpenAI web search for company research.",
        "data": {}
    }

def get_perplexity_usage_stats() -> dict:
    """Return empty usage - Perplexity disabled."""
    return {
        "enabled": False,
        "message": "Perplexity has been removed",
        "total_requests": 0,
        "total_cost": 0
    }

async def perplexity_query(*args, **kwargs) -> dict:
    """Perplexity disabled - use OpenAI web search instead."""
    return {
        "success": False,
        "error": "Perplexity has been removed. Use OpenAI web search for AI discovery.",
        "content": ""
    }

async def call_perplexity(*args, **kwargs) -> dict:
    """Perplexity disabled - use OpenAI web search instead."""
    return {
        "success": False,
        "error": "Perplexity has been removed. Use OpenAI web search for AI queries.",
        "content": ""
    }
