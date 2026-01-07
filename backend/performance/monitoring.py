"""
PERFORMANCE MONITORING MODULE
Tracks and reports on API performance metrics.
"""

import time
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


# ============== PERFORMANCE METRICS ==============

class PerformanceMetrics:
    """Thread-safe performance metrics collector"""
    
    def __init__(self, retention_hours: int = 24):
        self._lock = threading.RLock()
        self._metrics: Dict[str, List[Dict]] = defaultdict(list)
        self._retention_hours = retention_hours
        self._max_samples_per_endpoint = 1000
    
    def record(self, endpoint: str, duration_ms: float, status_code: int = 200, 
               cache_hit: bool = False, db_queries: int = 0):
        """Record a request metric"""
        with self._lock:
            self._metrics[endpoint].append({
                'timestamp': datetime.utcnow(),
                'duration_ms': duration_ms,
                'status_code': status_code,
                'cache_hit': cache_hit,
                'db_queries': db_queries
            })
            
            # Trim old data
            self._cleanup_endpoint(endpoint)
    
    def _cleanup_endpoint(self, endpoint: str):
        """Remove old samples"""
        cutoff = datetime.utcnow() - timedelta(hours=self._retention_hours)
        samples = self._metrics[endpoint]
        
        # Remove by age
        samples = [s for s in samples if s['timestamp'] > cutoff]
        
        # Limit samples
        if len(samples) > self._max_samples_per_endpoint:
            samples = samples[-self._max_samples_per_endpoint:]
        
        self._metrics[endpoint] = samples
    
    def get_stats(self, endpoint: str = None) -> Dict[str, Any]:
        """Get performance statistics"""
        with self._lock:
            if endpoint:
                return self._calculate_stats(endpoint, self._metrics.get(endpoint, []))
            
            # All endpoints
            return {
                ep: self._calculate_stats(ep, samples)
                for ep, samples in self._metrics.items()
            }
    
    def _calculate_stats(self, endpoint: str, samples: List[Dict]) -> Dict[str, Any]:
        """Calculate statistics for samples"""
        if not samples:
            return {
                'endpoint': endpoint,
                'request_count': 0,
                'avg_duration_ms': 0,
                'p50_duration_ms': 0,
                'p95_duration_ms': 0,
                'p99_duration_ms': 0,
                'max_duration_ms': 0,
                'cache_hit_rate': 0,
                'error_rate': 0
            }
        
        durations = sorted([s['duration_ms'] for s in samples])
        cache_hits = sum(1 for s in samples if s.get('cache_hit'))
        errors = sum(1 for s in samples if s.get('status_code', 200) >= 400)
        
        return {
            'endpoint': endpoint,
            'request_count': len(samples),
            'avg_duration_ms': round(sum(durations) / len(durations), 2),
            'p50_duration_ms': round(durations[len(durations) // 2], 2),
            'p95_duration_ms': round(durations[int(len(durations) * 0.95)], 2) if len(durations) >= 20 else round(durations[-1], 2),
            'p99_duration_ms': round(durations[int(len(durations) * 0.99)], 2) if len(durations) >= 100 else round(durations[-1], 2),
            'max_duration_ms': round(durations[-1], 2),
            'cache_hit_rate': round(cache_hits / len(samples) * 100, 2),
            'error_rate': round(errors / len(samples) * 100, 2)
        }
    
    def get_slow_endpoints(self, threshold_ms: float = 500) -> List[Dict]:
        """Get endpoints exceeding threshold"""
        with self._lock:
            slow = []
            for endpoint, samples in self._metrics.items():
                if not samples:
                    continue
                avg = sum(s['duration_ms'] for s in samples) / len(samples)
                if avg > threshold_ms:
                    slow.append({
                        'endpoint': endpoint,
                        'avg_duration_ms': round(avg, 2),
                        'request_count': len(samples)
                    })
            
            return sorted(slow, key=lambda x: x['avg_duration_ms'], reverse=True)


# ============== PERFORMANCE MONITOR ==============

class PerformanceMonitor:
    """
    Central performance monitoring service.
    Tracks request times, cache hits, database queries.
    """
    
    _instance: Optional['PerformanceMonitor'] = None
    
    def __init__(self):
        self._metrics = PerformanceMetrics()
        self._start_time = datetime.utcnow()
        self._total_requests = 0
        self._db_query_count = 0
        self._lock = threading.RLock()
    
    @classmethod
    def get_instance(cls) -> 'PerformanceMonitor':
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def record_request(self, endpoint: str, duration_ms: float, 
                       status_code: int = 200, cache_hit: bool = False,
                       db_queries: int = 0):
        """Record a request metric"""
        with self._lock:
            self._total_requests += 1
            self._db_query_count += db_queries
        
        self._metrics.record(endpoint, duration_ms, status_code, cache_hit, db_queries)
    
    def get_dashboard(self) -> Dict[str, Any]:
        """Get performance dashboard data"""
        uptime = datetime.utcnow() - self._start_time
        
        # Get top slow endpoints
        slow_endpoints = self._metrics.get_slow_endpoints(threshold_ms=500)[:10]
        
        # Get all endpoint stats
        all_stats = self._metrics.get_stats()
        
        # Calculate totals
        total_cache_hits = sum(
            s.get('cache_hit_rate', 0) * s.get('request_count', 0) / 100
            for s in all_stats.values()
        )
        
        total_requests = sum(s.get('request_count', 0) for s in all_stats.values())
        
        return {
            'generated_at': datetime.utcnow().isoformat(),
            'uptime_seconds': int(uptime.total_seconds()),
            'total_requests': total_requests,
            'overall_cache_hit_rate': round(total_cache_hits / total_requests * 100, 2) if total_requests > 0 else 0,
            'slow_endpoints': slow_endpoints,
            'endpoints': list(all_stats.values())
        }
    
    def get_health(self) -> Dict[str, Any]:
        """Get health check data"""
        slow = self._metrics.get_slow_endpoints(threshold_ms=2000)
        
        status = "healthy"
        if len(slow) > 5:
            status = "degraded"
        elif len(slow) > 10:
            status = "unhealthy"
        
        return {
            'status': status,
            'uptime_seconds': int((datetime.utcnow() - self._start_time).total_seconds()),
            'total_requests': self._total_requests,
            'slow_endpoint_count': len(slow)
        }


# ============== HELPER FUNCTIONS ==============

def get_performance_stats() -> Dict[str, Any]:
    """Get current performance statistics"""
    monitor = PerformanceMonitor.get_instance()
    return monitor.get_dashboard()


def get_performance_health() -> Dict[str, Any]:
    """Get performance health status"""
    monitor = PerformanceMonitor.get_instance()
    return monitor.get_health()


# ============== REQUEST TIMER CONTEXT MANAGER ==============

class RequestTimer:
    """
    Context manager for timing request processing.
    
    Usage:
        with RequestTimer('/api/dashboard') as timer:
            # do work
            timer.cache_hit = True
        # Automatically records metrics
    """
    
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.start_time = None
        self.duration_ms = 0
        self.cache_hit = False
        self.status_code = 200
        self.db_queries = 0
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.duration_ms = (time.perf_counter() - self.start_time) * 1000
        
        if exc_type is not None:
            self.status_code = 500
        
        # Record to monitor
        monitor = PerformanceMonitor.get_instance()
        monitor.record_request(
            self.endpoint,
            self.duration_ms,
            self.status_code,
            self.cache_hit,
            self.db_queries
        )
        
        return False  # Don't suppress exceptions


# ============== DATABASE QUERY COUNTER ==============

class DBQueryCounter:
    """
    Context manager to count database queries.
    
    Usage:
        with DBQueryCounter() as counter:
            # do database operations
            counter.increment()
        print(f"Queries: {counter.count}")
    """
    
    _local = threading.local()
    
    def __init__(self):
        self.count = 0
    
    @classmethod
    def current(cls) -> Optional['DBQueryCounter']:
        """Get current counter in this thread"""
        return getattr(cls._local, 'counter', None)
    
    def __enter__(self):
        self._previous = getattr(self._local, 'counter', None)
        self._local.counter = self
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self._local.counter = self._previous
        return False
    
    def increment(self, n: int = 1):
        """Increment query count"""
        self.count += n
    
    @classmethod
    def record(cls, n: int = 1):
        """Record query to current counter if exists"""
        counter = cls.current()
        if counter:
            counter.increment(n)
