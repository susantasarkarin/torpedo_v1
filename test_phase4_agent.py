#!/usr/bin/env python
"""
Phase 4 Agent Testing Suite
===========================
Tests the Testing & Validation agent against http://139.59.32.72:8000
"""

import httpx
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, List

# Configuration
API_BASE = "http://139.59.32.72:8000"
TIMEOUT = 30

class Phase4Tester:
    def __init__(self):
        self.results = {
            "test_suite": "Phase 4 (Testing & Validation)",
            "timestamp": datetime.utcnow().isoformat(),
            "api_base": API_BASE,
            "tests": []
        }
        self.passed = 0
        self.failed = 0
    
    def add_test(self, name: str, passed: bool, details: Dict[str, Any]):
        """Add a test result"""
        test_result = {
            "name": name,
            "passed": passed,
            "details": details
        }
        self.results["tests"].append(test_result)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
    
    async def test_stats_endpoint(self) -> None:
        """Test 1: Get /agents/4/stats"""
        print("\n" + "="*60)
        print("TEST 1: /agents/4/stats endpoint")
        print("="*60)
        
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.get(f"{API_BASE}/agents/4/stats")
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"✓ Status: {response.status_code}")
                    print(f"Response: {json.dumps(data, indent=2)}")
                    
                    details = {
                        "status_code": response.status_code,
                        "response_keys": list(data.keys()) if isinstance(data, dict) else None
                    }
                    
                    self.add_test("GET /agents/4/stats", True, details)
                else:
                    print(f"✗ Status: {response.status_code}")
                    details = {
                        "status_code": response.status_code,
                        "response": response.text[:200]
                    }
                    self.add_test("GET /agents/4/stats", False, details)
        except Exception as e:
            print(f"✗ Error: {e}")
            self.add_test("GET /agents/4/stats", False, {"error": str(e)})
    
    async def test_run_agent(self) -> Dict[str, Any]:
        """Test 2: Run /agents/run/4 and return response"""
        print("\n" + "="*60)
        print("TEST 2: /agents/run/4 endpoint")
        print("="*60)
        
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(
                    f"{API_BASE}/agents/run/4",
                    json={"phase": 4}
                )
                
                if response.status_code in [200, 202]:
                    data = response.json()
                    print(f"✓ Status: {response.status_code}")
                    print(f"Response keys: {list(data.keys())}")
                    
                    details = {
                        "status_code": response.status_code,
                        "response_keys": list(data.keys()),
                        "timestamp": data.get("timestamp", "N/A")
                    }
                    
                    self.add_test("POST /agents/run/4", True, details)
                    return data
                else:
                    print(f"✗ Status: {response.status_code}")
                    details = {
                        "status_code": response.status_code,
                        "response": response.text[:200]
                    }
                    self.add_test("POST /agents/run/4", False, details)
                    return {}
        except Exception as e:
            print(f"✗ Error: {e}")
            self.add_test("POST /agents/run/4", False, {"error": str(e)})
            return {}
    
    async def validate_health_report_structure(self, agent_response: Dict[str, Any]) -> None:
        """Test 3: Validate health_report structure"""
        print("\n" + "="*60)
        print("TEST 3: Health Report Structure Validation")
        print("="*60)
        
        if not agent_response:
            print("✗ No response data")
            self.add_test("Health report structure", False, {"error": "No response data"})
            return
        
        try:
            # Extract the result - it might be nested in "output"
            if "output" in agent_response:
                health_data = agent_response.get("output", {})
            elif "result" in agent_response:
                health_data = agent_response.get("result", {})
            else:
                health_data = agent_response
            
            health_report = health_data.get("health_report", {})
            
            print(f"Health Report Data:")
            print(json.dumps(health_report, indent=2))
            
            # Check required fields
            required_fields = ["overall_score", "status", "issues", "recommendations"]
            missing_fields = []
            
            for field in required_fields:
                if field not in health_report:
                    missing_fields.append(field)
                    print(f"✗ Missing field: {field}")
                else:
                    print(f"✓ Field present: {field} = {health_report[field]}")
            
            if not missing_fields:
                self.add_test("Health report structure", True, {
                    "has_all_required_fields": True,
                    "fields": required_fields,
                    "sample_score": health_report.get("overall_score"),
                    "sample_status": health_report.get("status")
                })
            else:
                self.add_test("Health report structure", False, {
                    "missing_fields": missing_fields
                })
        
        except Exception as e:
            print(f"✗ Error: {e}")
            self.add_test("Health report structure", False, {"error": str(e)})
    
    async def validate_endpoint_tests_section(self, agent_response: Dict[str, Any]) -> None:
        """Test 4: Validate endpoint_tests section (should have 7 endpoints)"""
        print("\n" + "="*60)
        print("TEST 4: Endpoint Tests Section (Should Test 7 Endpoints)")
        print("="*60)
        
        try:
            # Extract result
            if "output" in agent_response:
                data = agent_response.get("output", {})
            elif "result" in agent_response:
                data = agent_response.get("result", {})
            else:
                data = agent_response
            
            endpoint_tests = data.get("endpoint_tests", {})
            
            if "error" in endpoint_tests:
                print(f"✗ Endpoint tests error: {endpoint_tests['error']}")
                self.add_test("Endpoint tests section", False, {
                    "error": endpoint_tests["error"]
                })
                return
            
            total_tests = endpoint_tests.get("total_tests", 0)
            passed = endpoint_tests.get("passed", 0)
            failed = endpoint_tests.get("failed", 0)
            success_rate = endpoint_tests.get("success_rate", 0)
            tests = endpoint_tests.get("tests", [])
            
            print(f"✓ Total tests: {total_tests}")
            print(f"✓ Passed: {passed}")
            print(f"✓ Failed: {failed}")
            print(f"✓ Success rate: {success_rate}%")
            print(f"✓ Number of test cases: {len(tests)}")
            
            # List each test
            print("\nDetailed Test Results:")
            for test in tests:
                status = test.get("status", "unknown")
                endpoint = test.get("endpoint", "unknown")
                response_code = test.get("response_code", "N/A")
                response_time = test.get("response_time_ms", "N/A")
                print(f"  - {endpoint}: {status} (code: {response_code}, time: {response_time}ms)")
            
            # Check for the known issue: /leads/stats should return 404
            leads_stats_test = next((t for t in tests if "/leads/stats" in t.get("endpoint", "")), None)
            if leads_stats_test:
                if leads_stats_test.get("response_code") == 404:
                    print(f"\n✓ KNOWN ISSUE CONFIRMED: /leads/stats returns 404 (expected)")
                elif leads_stats_test.get("status") == "failed":
                    print(f"\n✓ Known issue detected for /leads/stats")
            
            # Validate
            issues = []
            if total_tests != 7:
                issues.append(f"Expected 7 endpoints, got {total_tests}")
            
            if any(t.get("status") == "error" for t in tests):
                error_count = sum(1 for t in tests if t.get("status") == "error")
                issues.append(f"{error_count} tests had connection/error issues")
            
            test_names = [t.get("name") for t in tests]
            
            passed_test = len(issues) == 0
            self.add_test("Endpoint tests section", passed_test, {
                "total_expected": 7,
                "total_actual": total_tests,
                "passed": passed,
                "failed": failed,
                "success_rate": success_rate,
                "test_names": test_names,
                "issues": issues
            })
        
        except Exception as e:
            print(f"✗ Error: {e}")
            self.add_test("Endpoint tests section", False, {"error": str(e)})
    
    async def validate_data_validation_section(self, agent_response: Dict[str, Any]) -> None:
        """Test 5: Validate data_validation section (should check 4 collections)"""
        print("\n" + "="*60)
        print("TEST 5: Data Validation Section (Should Check 4 Collections)")
        print("="*60)
        
        try:
            # Extract result
            if "output" in agent_response:
                data = agent_response.get("output", {})
            elif "result" in agent_response:
                data = agent_response.get("result", {})
            else:
                data = agent_response
            
            data_validation = data.get("data_validation", {})
            
            if "error" in data_validation:
                print(f"✗ Data validation error: {data_validation['error']}")
                self.add_test("Data validation section", False, {
                    "error": data_validation["error"]
                })
                return
            
            collections_checked = data_validation.get("collections_checked", 0)
            issues_found = data_validation.get("issues_found", 0)
            details = data_validation.get("details", [])
            
            print(f"✓ Collections checked: {collections_checked}")
            print(f"✓ Issues found: {issues_found}")
            print(f"✓ Number of detail entries: {len(details)}")
            
            # List each collection
            print("\nCollection Details:")
            for coll in details:
                name = coll.get("collection", "unknown")
                total_docs = coll.get("total_documents", "N/A")
                issues = coll.get("issues", [])
                print(f"  - {name}: {total_docs} documents, {len(issues)} issues")
                for issue in issues:
                    print(f"    • {issue.get('type', 'unknown')}: {issue}")
            
            # Validate
            issues = []
            if collections_checked != 4:
                issues.append(f"Expected 4 collections, got {collections_checked}")
            
            passed_test = len(issues) == 0
            self.add_test("Data validation section", passed_test, {
                "collections_expected": 4,
                "collections_actual": collections_checked,
                "issues_found": issues_found,
                "collection_names": [d.get("collection") for d in details],
                "validation_issues": issues
            })
        
        except Exception as e:
            print(f"✗ Error: {e}")
            self.add_test("Data validation section", False, {"error": str(e)})
    
    async def validate_performance_check(self, agent_response: Dict[str, Any]) -> None:
        """Test 6: Validate performance_check metrics"""
        print("\n" + "="*60)
        print("TEST 6: Performance Check Metrics")
        print("="*60)
        
        try:
            # Extract result
            if "output" in agent_response:
                data = agent_response.get("output", {})
            elif "result" in agent_response:
                data = agent_response.get("result", {})
            else:
                data = agent_response
            
            performance = data.get("performance_check", {})
            
            if "error" in performance:
                print(f"✗ Performance check error: {performance['error']}")
                self.add_test("Performance check", False, {
                    "error": performance["error"]
                })
                return
            
            metrics = performance.get("metrics", {})
            warnings = performance.get("warnings", [])
            status = performance.get("status", "unknown")
            
            print(f"✓ Status: {status}")
            print(f"✓ Number of warnings: {len(warnings)}")
            
            # Required metrics
            required_metrics = [
                "avg_api_response_ms",
                "cache_hit_rate",
                "avg_pattern_confidence"
            ]
            
            print("\nMetrics:")
            for metric in required_metrics:
                if metric in metrics:
                    print(f"  ✓ {metric}: {metrics[metric]}")
                else:
                    print(f"  ✗ {metric}: MISSING")
            
            print("\nWarnings:")
            for warning in warnings:
                print(f"  - {warning}")
            
            # Validate
            missing_metrics = [m for m in required_metrics if m not in metrics]
            
            passed_test = len(missing_metrics) == 0
            self.add_test("Performance check", passed_test, {
                "status": status,
                "metrics_found": list(metrics.keys()),
                "metrics_expected": required_metrics,
                "missing_metrics": missing_metrics,
                "warning_count": len(warnings),
                "warnings": warnings
            })
        
        except Exception as e:
            print(f"✗ Error: {e}")
            self.add_test("Performance check", False, {"error": str(e)})
    
    async def validate_health_score_calculation(self, agent_response: Dict[str, Any]) -> None:
        """Test 7: Validate health score calculation"""
        print("\n" + "="*60)
        print("TEST 7: Health Score Calculation")
        print("="*60)
        
        try:
            # Extract result
            if "output" in agent_response:
                data = agent_response.get("output", {})
            elif "result" in agent_response:
                data = agent_response.get("result", {})
            else:
                data = agent_response
            
            health_report = data.get("health_report", {})
            endpoint_tests = data.get("endpoint_tests", {})
            
            score = health_report.get("overall_score", 0)
            status = health_report.get("status", "unknown")
            
            print(f"✓ Overall score: {score}")
            print(f"✓ Status: {status}")
            
            # Validate score range
            if 0 <= score <= 100:
                print(f"✓ Score is in valid range [0-100]")
            else:
                print(f"✗ Score is out of range: {score}")
            
            # Validate status based on score
            expected_status = None
            if score >= 90:
                expected_status = "healthy"
            elif score >= 70:
                expected_status = "degraded"
            else:
                expected_status = "critical"
            
            if status == expected_status:
                print(f"✓ Status '{status}' matches score {score}")
            else:
                print(f"✗ Status '{status}' doesn't match expected '{expected_status}' for score {score}")
            
            # Show calculation breakdown
            print("\nScore Breakdown:")
            print(f"  - Endpoints: {endpoint_tests.get('passed', 0)}/{endpoint_tests.get('total_tests', 0)} passed")
            
            passed_test = (0 <= score <= 100) and (status == expected_status)
            self.add_test("Health score calculation", passed_test, {
                "score": score,
                "score_valid_range": 0 <= score <= 100,
                "status": status,
                "status_matches_score": status == expected_status,
                "endpoints_passed": endpoint_tests.get('passed', 0),
                "endpoints_tested": endpoint_tests.get('total_tests', 0)
            })
        
        except Exception as e:
            print(f"✗ Error: {e}")
            self.add_test("Health score calculation", False, {"error": str(e)})
    
    async def verify_known_issue(self, agent_response: Dict[str, Any]) -> None:
        """Test 8: Verify known issue - /leads/stats returns 404"""
        print("\n" + "="*60)
        print("TEST 8: Known Issue Verification - /leads/stats 404")
        print("="*60)
        
        try:
            # Extract result
            if "output" in agent_response:
                data = agent_response.get("output", {})
            elif "result" in agent_response:
                data = agent_response.get("result", {})
            else:
                data = agent_response
            
            endpoint_tests = data.get("endpoint_tests", {})
            tests = endpoint_tests.get("tests", [])
            
            leads_stats_test = next((t for t in tests if "/leads/stats" in t.get("endpoint", "")), None)
            
            if leads_stats_test:
                response_code = leads_stats_test.get("response_code")
                status = leads_stats_test.get("status")
                
                print(f"✓ Found /leads/stats test")
                print(f"  - Response code: {response_code}")
                print(f"  - Status: {status}")
                
                if response_code == 404:
                    print(f"\n✓ EXPECTED: /leads/stats returns 404 (expected warning)")
                    self.add_test("Known issue: /leads/stats 404", True, {
                        "endpoint": "/leads/stats",
                        "response_code": response_code,
                        "is_expected_issue": True
                    })
                else:
                    print(f"\n⚠ /leads/stats returned {response_code} (not 404)")
                    self.add_test("Known issue: /leads/stats 404", False, {
                        "endpoint": "/leads/stats",
                        "response_code": response_code,
                        "expected_code": 404,
                        "note": "May have been fixed or is a different issue"
                    })
            else:
                print(f"✗ /leads/stats test not found in test results")
                self.add_test("Known issue: /leads/stats 404", False, {
                    "error": "/leads/stats test not found"
                })
        
        except Exception as e:
            print(f"✗ Error: {e}")
            self.add_test("Known issue: /leads/stats 404", False, {"error": str(e)})
    
    async def run_all_tests(self) -> None:
        """Run all Phase 4 tests"""
        print("\n" + "█"*60)
        print("█" + " "*58 + "█")
        print("█" + "  PHASE 4 AGENT TESTING SUITE".center(58) + "█")
        print("█" + "  Testing & Validation".center(58) + "█")
        print("█" + " "*58 + "█")
        print("█"*60)
        
        # Test 1: Stats endpoint
        await self.test_stats_endpoint()
        
        # Test 2: Run agent and get response
        agent_response = await self.test_run_agent()
        
        # Tests 3-8: Validate response structure and content
        await self.validate_health_report_structure(agent_response)
        await self.validate_endpoint_tests_section(agent_response)
        await self.validate_data_validation_section(agent_response)
        await self.validate_performance_check(agent_response)
        await self.validate_health_score_calculation(agent_response)
        await self.verify_known_issue(agent_response)
        
        # Summary
        self.print_summary()
    
    def print_summary(self) -> None:
        """Print test summary"""
        print("\n" + "█"*60)
        print("█" + "  TEST SUMMARY".center(58) + "█")
        print("█"*60)
        print(f"\n✓ Passed: {self.passed}")
        print(f"✗ Failed: {self.failed}")
        print(f"Total: {self.passed + self.failed}")
        
        if self.failed == 0:
            print("\n🎉 ALL TESTS PASSED!")
        else:
            print(f"\n⚠️  {self.failed} test(s) failed")
        
        # Save results to file
        output_file = "phase4_test_results.json"
        with open(output_file, "w") as f:
            json.dump(self.results, f, indent=2)
        print(f"\n📄 Detailed results saved to: {output_file}")
        
        # Print JSON results
        print("\n" + "="*60)
        print("JSON RESULTS")
        print("="*60)
        print(json.dumps(self.results, indent=2))


async def main():
    tester = Phase4Tester()
    await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
