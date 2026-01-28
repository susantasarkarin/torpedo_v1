#!/usr/bin/env python3
"""
AGENT 11 INTEGRATION TEST SCRIPT
Tests all deliverability and analytics endpoints

Usage: python test_agent11_endpoints.py
"""

import requests
import json
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8000"
TEST_DOMAIN = "surveyfieldwork.com"

# Colors for output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def test_endpoint(method, endpoint, description):
    """Test a single endpoint"""
    url = f"{BASE_URL}{endpoint}"
    print(f"\n{Colors.BLUE}Testing:{Colors.END} {description}")
    print(f"  {method} {endpoint}")
    
    try:
        if method == "GET":
            response = requests.get(url, timeout=10)
        elif method == "POST":
            response = requests.post(url, json={}, timeout=10)
        
        if response.status_code == 200:
            print(f"  {Colors.GREEN}✓ Success{Colors.END} (Status: {response.status_code})")
            data = response.json()
            print(f"  Response keys: {list(data.keys())[:5]}...")
            return True
        else:
            print(f"  {Colors.YELLOW}⚠ Warning{Colors.END} (Status: {response.status_code})")
            print(f"  Response: {response.text[:100]}...")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"  {Colors.RED}✗ Failed{Colors.END} - Server not running at {BASE_URL}")
        return False
    except Exception as e:
        print(f"  {Colors.RED}✗ Failed{Colors.END} - {str(e)}")
        return False

def main():
    """Run all tests"""
    print(f"\n{Colors.BLUE}{'='*70}{Colors.END}")
    print(f"{Colors.GREEN}AGENT 11 ENDPOINT INTEGRATION TESTS{Colors.END}")
    print(f"{Colors.BLUE}{'='*70}{Colors.END}")
    print(f"\nServer: {BASE_URL}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    tests = []
    
    # DELIVERABILITY ENDPOINTS
    print(f"\n\n{Colors.YELLOW}{'='*70}{Colors.END}")
    print(f"{Colors.YELLOW}DELIVERABILITY MONITORING ENDPOINTS{Colors.END}")
    print(f"{Colors.YELLOW}{'='*70}{Colors.END}")
    
    tests.append(test_endpoint(
        "GET",
        "/deliverability/domains",
        "List all monitored domains"
    ))
    
    tests.append(test_endpoint(
        "GET",
        f"/deliverability/domains/{TEST_DOMAIN}/health",
        f"Get health check for {TEST_DOMAIN}"
    ))
    
    tests.append(test_endpoint(
        "POST",
        f"/deliverability/domains/{TEST_DOMAIN}/check",
        f"Trigger manual check for {TEST_DOMAIN}"
    ))
    
    tests.append(test_endpoint(
        "GET",
        "/deliverability/gmail-accounts/usage",
        "Get Gmail pool usage statistics"
    ))
    
    tests.append(test_endpoint(
        "GET",
        "/deliverability/reputation?days=7",
        "Get reputation metrics (last 7 days)"
    ))
    
    tests.append(test_endpoint(
        "GET",
        "/deliverability/alerts",
        "Get active deliverability alerts"
    ))
    
    # ANALYTICS ENDPOINTS
    print(f"\n\n{Colors.YELLOW}{'='*70}{Colors.END}")
    print(f"{Colors.YELLOW}CAMPAIGN ANALYTICS ENDPOINTS{Colors.END}")
    print(f"{Colors.YELLOW}{'='*70}{Colors.END}")
    
    # Note: These will likely return 404 without a real campaign_id
    # But we can test that the endpoints exist
    TEST_CAMPAIGN_ID = "test_campaign_id"
    
    tests.append(test_endpoint(
        "GET",
        f"/campaigns/automation/campaigns/{TEST_CAMPAIGN_ID}/analytics/timeseries?interval=day",
        "Get time series analytics"
    ))
    
    tests.append(test_endpoint(
        "GET",
        f"/campaigns/automation/campaigns/{TEST_CAMPAIGN_ID}/analytics/funnel",
        "Get conversion funnel"
    ))
    
    tests.append(test_endpoint(
        "GET",
        f"/campaigns/automation/campaigns/{TEST_CAMPAIGN_ID}/analytics/by-segment?segment_by=industry",
        "Get segment analysis"
    ))
    
    tests.append(test_endpoint(
        "GET",
        f"/campaigns/automation/campaigns/{TEST_CAMPAIGN_ID}/analytics/engagement-heatmap",
        "Get engagement heatmap"
    ))
    
    # SUMMARY
    print(f"\n\n{Colors.BLUE}{'='*70}{Colors.END}")
    print(f"{Colors.GREEN}TEST SUMMARY{Colors.END}")
    print(f"{Colors.BLUE}{'='*70}{Colors.END}")
    
    passed = sum(tests)
    total = len(tests)
    
    print(f"\nTotal Tests: {total}")
    print(f"Passed: {Colors.GREEN}{passed}{Colors.END}")
    print(f"Failed: {Colors.RED}{total - passed}{Colors.END}")
    
    if passed == total:
        print(f"\n{Colors.GREEN}✓ All endpoints responding!{Colors.END}")
    elif passed > 0:
        print(f"\n{Colors.YELLOW}⚠ Some endpoints responding (check if server is running){Colors.END}")
    else:
        print(f"\n{Colors.RED}✗ Server not responding. Make sure FastAPI is running at {BASE_URL}{Colors.END}")
    
    print(f"\n{Colors.BLUE}{'='*70}{Colors.END}\n")
    
    return passed == total

if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
