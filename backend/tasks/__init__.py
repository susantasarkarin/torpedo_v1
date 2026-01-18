"""
Backend Tasks Package
Celery task definitions for background processing
"""

from celery_app import celery_app

__all__ = ['celery_app']
