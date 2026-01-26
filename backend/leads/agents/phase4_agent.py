"""
Phase 4 Agent: Testing & Validation
====================================

This agent handles:
1. End-to-end testing of all pipeline components
2. Data validation and integrity checks
3. Performance monitoring and reporting
4. Error detection and alerting

Tasks:
- Run automated tests on all Phase 2-3 endpoints
- Validate data consistency across collections
- Check for data quality issues (duplicates, missing fields)
- Generate health reports
"""

import os
import logging
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from .base_agent import BaseAgent, AgentResult, AgentStatus, AgentRegistry

logger = logging.getLogger(__name__)


@AgentRegistry.register
class Phase4Agent(BaseAgent):
    """
    Phase 4 Agent: Testing & Validation
    
    Capabilities:
    - Runs E2E tests on API endpoints
    - Validates data integrity
    - Monitors performance metrics
    - Generates health reports
    """
    
    def __init__(self):
        super().__init__(name="Phase4_Testing", phase=4)
        
        # Default configuration
        self.config = {
            "api_base_url": os.getenv("API_BASE", "http://localhost:8000"),
            "test_timeout": 30,  # seconds per test
            "enable_endpoint_tests": True,
            "enable_data_validation": True,
            "enable_performance_check": True,
            "max_duplicates_allowed": 100,
            "min_required_fields": ["email", "company_name"],
            "performance_thresholds": {
                "api_response_ms": 2000,
                "cache_hit_rate": 0.5,
                "pattern_confidence": 0.6
            }
        }
        
        # Test results storage
        self._test_results: List[Dict[str, Any]] = []
    
    def get_description(self) -> str:
        return """Phase 4 Agent: Testing & Validation
        
        - Runs E2E tests on all endpoints
        - Validates data integrity across collections
        - Monitors performance metrics
        - Generates comprehensive health reports"""
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Phase 4 validation tasks.
        """
        self.log_info("Starting Phase 4 Testing & Validation...")
        
        self._test_results = []
        
        results = {
            "endpoint_tests": {},
            "data_validation": {},
            "performance_check": {},
            "health_report": {}
        }
        
        # Task 1: Endpoint Tests
        if self.config["enable_endpoint_tests"]:
            try:
                endpoint_results = await self._run_endpoint_tests()
                results["endpoint_tests"] = endpoint_results
                self.add_metric("endpoints_tested", endpoint_results.get("total_tests", 0))
                self.add_metric("endpoints_passed", endpoint_results.get("passed", 0))
            except Exception as e:
                self.log_error(f"Endpoint tests failed: {e}")
                results["endpoint_tests"] = {"error": str(e)}
        
        # Task 2: Data Validation
        if self.config["enable_data_validation"]:
            try:
                validation_results = await self._validate_data()
                results["data_validation"] = validation_results
                self.add_metric("collections_validated", validation_results.get("collections_checked", 0))
            except Exception as e:
                self.log_error(f"Data validation failed: {e}")
                results["data_validation"] = {"error": str(e)}
        
        # Task 3: Performance Check
        if self.config["enable_performance_check"]:
            try:
                perf_results = await self._check_performance()
                results["performance_check"] = perf_results
            except Exception as e:
                self.log_error(f"Performance check failed: {e}")
                results["performance_check"] = {"error": str(e)}
        
        # Task 4: Generate Health Report
        try:
            health_report = self._generate_health_report(results)
            results["health_report"] = health_report
        except Exception as e:
            self.log_error(f"Health report generation failed: {e}")
            results["health_report"] = {"error": str(e)}
        
        # Calculate totals
        total_tests = results["endpoint_tests"].get("total_tests", 0)
        passed_tests = results["endpoint_tests"].get("passed", 0)
        
        self.add_metric("records_processed", total_tests)
        self.add_metric("records_success", passed_tests)
        self.add_metric("records_failed", total_tests - passed_tests)
        
        return results
    
    async def _run_endpoint_tests(self) -> Dict[str, Any]:
        """
        Run tests on all Phase 2-4 API endpoints.
        """
        self.log_info("Running endpoint tests...")
        
        base_url = self.config["api_base_url"]
        timeout = self.config["test_timeout"]
        
        # Define test cases
        test_cases = [
            # Phase 2: Classified Gmail
            {
                "name": "classified_gmail_stats",
                "method": "GET",
                "endpoint": "/classified-gmail/stats",
                "expected_status": [200, 401]
            },
            {
                "name": "classified_gmail_list",
                "method": "GET",
                "endpoint": "/classified-gmail/list",
                "expected_status": [200, 401]
            },
            # Phase 3: Email Patterns
            {
                "name": "email_patterns_stats",
                "method": "GET",
                "endpoint": "/email-patterns/stats",
                "expected_status": [200, 401]
            },
            {
                "name": "email_patterns_list",
                "method": "GET",
                "endpoint": "/email-patterns/list",
                "expected_status": [200, 401]
            },
            # Phase 3: Company Cache
            {
                "name": "company_cache_stats",
                "method": "GET",
                "endpoint": "/company-cache/stats",
                "expected_status": [200, 401]
            },
            # Health check
            {
                "name": "health_check",
                "method": "GET",
                "endpoint": "/health",
                "expected_status": [200]
            },
            # Leads
            {
                "name": "leads_stats",
                "method": "GET",
                "endpoint": "/leads/stats",
                "expected_status": [200, 401]
            }
        ]
        
        passed = 0
        failed = 0
        test_details = []
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            for test in test_cases:
                start_time = datetime.utcnow()
                result = {
                    "name": test["name"],
                    "endpoint": test["endpoint"],
                    "method": test["method"],
                    "status": "pending"
                }
                
                try:
                    url = f"{base_url}{test['endpoint']}"
                    
                    if test["method"] == "GET":
                        response = await client.get(url)
                    elif test["method"] == "POST":
                        response = await client.post(url, json=test.get("body", {}))
                    else:
                        response = await client.request(test["method"], url)
                    
                    elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                    
                    if response.status_code in test["expected_status"]:
                        result["status"] = "passed"
                        result["response_code"] = response.status_code
                        result["response_time_ms"] = round(elapsed_ms, 2)
                        passed += 1
                    else:
                        result["status"] = "failed"
                        result["response_code"] = response.status_code
                        result["expected"] = test["expected_status"]
                        result["response_time_ms"] = round(elapsed_ms, 2)
                        failed += 1
                        self.log_warning(f"Test {test['name']} failed: got {response.status_code}")
                        
                except httpx.ConnectError:
                    result["status"] = "error"
                    result["error"] = "Connection refused - is the server running?"
                    failed += 1
                    self.log_error(f"Test {test['name']}: Connection refused")
                except Exception as e:
                    result["status"] = "error"
                    result["error"] = str(e)
                    failed += 1
                    self.log_error(f"Test {test['name']} error: {e}")
                
                test_details.append(result)
                self._test_results.append(result)
        
        total = len(test_cases)
        success_rate = round(passed / max(total, 1) * 100, 1)
        
        self.log_info(f"Endpoint tests: {passed}/{total} passed ({success_rate}%)")
        
        return {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "success_rate": success_rate,
            "tests": test_details
        }
    
    async def _validate_data(self) -> Dict[str, Any]:
        """
        Validate data integrity across collections.
        """
        self.log_info("Validating data integrity...")
        
        validation_results = {
            "collections_checked": 0,
            "issues_found": 0,
            "details": []
        }
        
        # Collections to validate
        collections_config = [
            {
                "name": "classified_gmail",
                "db": "email_automation",
                "required_fields": ["email_id", "segment"],
                "check_duplicates": "email_id"
            },
            {
                "name": "email_patterns",
                "db": "email_automation",
                "required_fields": ["domain", "pattern", "confidence"],
                "check_duplicates": "domain"
            },
            {
                "name": "company_cache",
                "db": "email_automation",
                "required_fields": ["domain"],
                "check_duplicates": "domain"
            },
            {
                "name": "leads_raw",
                "db": "email_automation",
                "required_fields": ["email"],
                "check_duplicates": "email"
            }
        ]
        
        for coll_config in collections_config:
            try:
                db = self.client[coll_config["db"]]
                collection = db[coll_config["name"]]
                
                result = {
                    "collection": coll_config["name"],
                    "total_documents": 0,
                    "issues": []
                }
                
                # Count documents
                result["total_documents"] = collection.count_documents({})
                
                # Check for missing required fields
                for field in coll_config["required_fields"]:
                    missing = collection.count_documents({field: {"$exists": False}})
                    if missing > 0:
                        result["issues"].append({
                            "type": "missing_field",
                            "field": field,
                            "count": missing
                        })
                        validation_results["issues_found"] += 1
                
                # Check for duplicates
                if coll_config.get("check_duplicates"):
                    dup_field = coll_config["check_duplicates"]
                    pipeline = [
                        {"$group": {"_id": f"${dup_field}", "count": {"$sum": 1}}},
                        {"$match": {"count": {"$gt": 1}}},
                        {"$count": "duplicates"}
                    ]
                    dup_result = list(collection.aggregate(pipeline))
                    duplicates = dup_result[0]["duplicates"] if dup_result else 0
                    
                    if duplicates > self.config["max_duplicates_allowed"]:
                        result["issues"].append({
                            "type": "duplicates",
                            "field": dup_field,
                            "count": duplicates
                        })
                        validation_results["issues_found"] += 1
                
                validation_results["details"].append(result)
                validation_results["collections_checked"] += 1
                
            except Exception as e:
                self.log_warning(f"Failed to validate {coll_config['name']}: {e}")
                validation_results["details"].append({
                    "collection": coll_config["name"],
                    "error": str(e)
                })
        
        self.log_info(f"Data validation: {validation_results['collections_checked']} collections, {validation_results['issues_found']} issues")
        
        return validation_results
    
    async def _check_performance(self) -> Dict[str, Any]:
        """
        Check performance metrics against thresholds.
        """
        self.log_info("Checking performance metrics...")
        
        thresholds = self.config["performance_thresholds"]
        
        performance = {
            "metrics": {},
            "warnings": [],
            "status": "healthy"
        }
        
        # Check cache hit rate
        try:
            cache_stats = self.db['company_cache'].aggregate([
                {"$group": {
                    "_id": None,
                    "total_hits": {"$sum": "$cache_hit_count"},
                    "total_entries": {"$sum": 1}
                }}
            ])
            cache_data = list(cache_stats)
            
            if cache_data:
                total_hits = cache_data[0].get("total_hits", 0)
                total_entries = cache_data[0].get("total_entries", 1)
                hit_rate = total_hits / max(total_entries, 1)
                
                performance["metrics"]["cache_hit_rate"] = round(hit_rate, 3)
                
                if hit_rate < thresholds["cache_hit_rate"]:
                    performance["warnings"].append(f"Cache hit rate {hit_rate:.1%} below threshold {thresholds['cache_hit_rate']:.1%}")
                    performance["status"] = "degraded"
        except Exception as e:
            self.log_warning(f"Cache hit rate check failed: {e}")
        
        # Check pattern confidence average
        try:
            pattern_stats = self.db['email_patterns'].aggregate([
                {"$group": {
                    "_id": None,
                    "avg_confidence": {"$avg": "$confidence"},
                    "total": {"$sum": 1}
                }}
            ])
            pattern_data = list(pattern_stats)
            
            if pattern_data:
                avg_confidence = pattern_data[0].get("avg_confidence", 0)
                
                performance["metrics"]["avg_pattern_confidence"] = round(avg_confidence, 3)
                
                if avg_confidence < thresholds["pattern_confidence"]:
                    performance["warnings"].append(f"Average pattern confidence {avg_confidence:.1%} below threshold {thresholds['pattern_confidence']:.1%}")
                    performance["status"] = "degraded"
        except Exception as e:
            self.log_warning(f"Pattern confidence check failed: {e}")
        
        # Check API response times from recent tests
        if self._test_results:
            response_times = [t.get("response_time_ms", 0) for t in self._test_results if t.get("response_time_ms")]
            if response_times:
                avg_response = sum(response_times) / len(response_times)
                performance["metrics"]["avg_api_response_ms"] = round(avg_response, 2)
                
                if avg_response > thresholds["api_response_ms"]:
                    performance["warnings"].append(f"Average API response {avg_response:.0f}ms exceeds threshold {thresholds['api_response_ms']}ms")
                    performance["status"] = "degraded"
        
        self.log_info(f"Performance check: {performance['status']}, {len(performance['warnings'])} warnings")
        
        return performance
    
    def _generate_health_report(self, all_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate comprehensive health report.
        """
        self.log_info("Generating health report...")
        
        # Calculate overall health score
        score = 100
        issues = []
        
        # Endpoint tests impact
        endpoint_results = all_results.get("endpoint_tests", {})
        if endpoint_results.get("success_rate", 100) < 100:
            penalty = (100 - endpoint_results.get("success_rate", 100)) * 0.5
            score -= penalty
            issues.append(f"Endpoint tests: {endpoint_results.get('failed', 0)} failed")
        
        # Data validation impact
        validation = all_results.get("data_validation", {})
        if validation.get("issues_found", 0) > 0:
            score -= min(validation["issues_found"] * 5, 20)
            issues.append(f"Data validation: {validation['issues_found']} issues")
        
        # Performance impact
        perf = all_results.get("performance_check", {})
        if perf.get("status") == "degraded":
            score -= 10
            issues.extend(perf.get("warnings", []))
        
        # Determine status
        if score >= 90:
            status = "healthy"
        elif score >= 70:
            status = "degraded"
        else:
            status = "critical"
        
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "overall_score": max(round(score, 1), 0),
            "status": status,
            "summary": {
                "endpoints_tested": endpoint_results.get("total_tests", 0),
                "endpoints_passed": endpoint_results.get("passed", 0),
                "data_issues": validation.get("issues_found", 0),
                "performance_warnings": len(perf.get("warnings", []))
            },
            "issues": issues,
            "recommendations": []
        }
        
        # Add recommendations
        if endpoint_results.get("failed", 0) > 0:
            report["recommendations"].append("Check backend logs for endpoint failures")
        if validation.get("issues_found", 0) > 0:
            report["recommendations"].append("Run data cleanup to fix integrity issues")
        if perf.get("status") == "degraded":
            report["recommendations"].append("Review performance metrics and optimize queries")
        
        self.log_info(f"Health report: {status} (score: {score:.1f})")
        
        return report
    
    def get_test_results(self) -> List[Dict[str, Any]]:
        """Get all test results from last run"""
        return self._test_results
