"""
End-to-End Testing Suite for Phase 2-4 Features
Tests all integrated components: classified_gmail, email_patterns, company_cache
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
API_BASE = os.getenv("API_BASE", "http://localhost:9944")
TEST_SESSION_ID = os.getenv("TEST_SESSION_ID", "test_session_123")

# Test data
TEST_EMAILS = [
    {
        "sender": "john.smith@techcorp.com",
        "sender_name": "John Smith",
        "subject": "Project Proposal - Q1 2026",
        "body": "Hello, I'm reaching out regarding a potential partnership opportunity...",
        "segment": "CLIENT",
        "priority": 8
    },
    {
        "sender": "hr@acmeinc.com",
        "sender_name": "HR Team",
        "subject": "Job Opportunities at ACME Inc",
        "body": "We are looking for experienced professionals...",
        "segment": "RECRUITER",
        "priority": 3
    },
    {
        "sender": "vendor@supplychains.net",
        "sender_name": "Supply Chain Manager",
        "subject": "New Supplier Partnership",
        "body": "We would like to discuss our vendor services...",
        "segment": "VENDOR",
        "priority": 6
    }
]

TEST_COMPANIES = [
    {
        "company_name": "TechCorp Inc",
        "domain": "techcorp.com",
        "employees": 500,
        "revenue": "$50M - $100M",
        "industry": "Software",
        "founded": 2015,
        "type": "Private",
        "headquarters": "San Francisco, CA",
        "website": "https://techcorp.com"
    },
    {
        "company_name": "ACME Industries",
        "domain": "acmeinc.com",
        "employees": 1000,
        "revenue": "$100M - $500M",
        "industry": "Manufacturing",
        "founded": 1990,
        "type": "Public",
        "headquarters": "New York, NY",
        "website": "https://acmeinc.com"
    }
]


class E2ETestSuite:
    """End-to-end testing for phases 2-4"""
    
    def __init__(self, api_base: str = API_BASE, session_id: str = TEST_SESSION_ID):
        self.api_base = api_base
        self.session_id = session_id
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": session_id
        }
        self.results = {
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "errors": [],
            "tests": []
        }
    
    def log_test(self, name: str, passed: bool, details: str = ""):
        """Log test result"""
        self.results["total_tests"] += 1
        if passed:
            self.results["passed"] += 1
            status = "✅ PASS"
        else:
            self.results["failed"] += 1
            status = "❌ FAIL"
        
        self.results["tests"].append({
            "name": name,
            "passed": passed,
            "details": details
        })
        
        print(f"{status}: {name}")
        if details:
            print(f"       {details}")
    
    def test_classified_gmail_list(self) -> bool:
        """Test: Get list of classified emails"""
        try:
            url = f"{self.api_base}/classified-gmail/list?limit=10"
            response = requests.get(url, headers=self.headers)
            
            passed = response.status_code == 200
            data = response.json() if passed else {}
            
            self.log_test(
                "GET /classified-gmail/list",
                passed,
                f"Status: {response.status_code}, Total: {data.get('total', 'N/A')}"
            )
            return passed
        except Exception as e:
            self.log_test("GET /classified-gmail/list", False, str(e))
            return False
    
    def test_classified_gmail_stats(self) -> bool:
        """Test: Get classified gmail statistics"""
        try:
            url = f"{self.api_base}/classified-gmail/stats?days=7"
            response = requests.get(url, headers=self.headers)
            
            passed = response.status_code == 200
            data = response.json() if passed else {}
            
            self.log_test(
                "GET /classified-gmail/stats",
                passed,
                f"Status: {response.status_code}, Classified: {data.get('total_classified', 'N/A')}"
            )
            return passed
        except Exception as e:
            self.log_test("GET /classified-gmail/stats", False, str(e))
            return False
    
    def test_batch_process_emails(self) -> bool:
        """Test: Process batch of emails"""
        try:
            url = f"{self.api_base}/classified-gmail/batch/process"
            payload = {"limit": 10, "priority_only": False}
            
            response = requests.post(url, headers=self.headers, json=payload)
            
            passed = response.status_code == 200
            data = response.json() if passed else {}
            
            self.log_test(
                "POST /classified-gmail/batch/process",
                passed,
                f"Status: {response.status_code}, Processed: {data.get('processed', 'N/A')}"
            )
            return passed
        except Exception as e:
            self.log_test("POST /classified-gmail/batch/process", False, str(e))
            return False
    
    def test_email_patterns_stats(self) -> bool:
        """Test: Get email pattern statistics"""
        try:
            url = f"{self.api_base}/email-patterns/stats"
            response = requests.get(url, headers=self.headers)
            
            passed = response.status_code == 200
            data = response.json() if passed else {}
            
            self.log_test(
                "GET /email-patterns/stats",
                passed,
                f"Status: {response.status_code}, Domains: {data.get('total_domains', 'N/A')}"
            )
            return passed
        except Exception as e:
            self.log_test("GET /email-patterns/stats", False, str(e))
            return False
    
    def test_analyze_mail_pool(self) -> bool:
        """Test: Analyze mail pool for patterns"""
        try:
            url = f"{self.api_base}/email-patterns/analyze-mail-pool"
            payload = {"limit": 100, "min_samples": 3}
            
            response = requests.post(url, headers=self.headers, json=payload)
            
            passed = response.status_code == 200
            data = response.json() if passed else {}
            
            self.log_test(
                "POST /email-patterns/analyze-mail-pool",
                passed,
                f"Status: {response.status_code}, New Patterns: {data.get('new_patterns', 'N/A')}"
            )
            return passed
        except Exception as e:
            self.log_test("POST /email-patterns/analyze-mail-pool", False, str(e))
            return False
    
    def test_get_pattern(self) -> bool:
        """Test: Get email pattern for domain"""
        try:
            url = f"{self.api_base}/email-patterns/google.com"
            response = requests.get(url, headers=self.headers)
            
            passed = response.status_code == 200
            data = response.json() if passed else {}
            
            self.log_test(
                "GET /email-patterns/{domain}",
                passed,
                f"Status: {response.status_code}, Found: {data.get('found', False)}"
            )
            return passed
        except Exception as e:
            self.log_test("GET /email-patterns/{domain}", False, str(e))
            return False
    
    def test_build_email(self) -> bool:
        """Test: Build email from pattern"""
        try:
            url = f"{self.api_base}/email-patterns/build-email/google.com/John Smith"
            response = requests.get(url, headers=self.headers)
            
            passed = response.status_code == 200
            data = response.json() if passed else {}
            
            self.log_test(
                "GET /email-patterns/build-email/{domain}/{name}",
                passed,
                f"Status: {response.status_code}, Email: {data.get('email', 'N/A')}"
            )
            return passed
        except Exception as e:
            self.log_test("GET /email-patterns/build-email/{domain}/{name}", False, str(e))
            return False
    
    def test_company_cache_lookup(self) -> bool:
        """Test: Lookup company in cache"""
        try:
            url = f"{self.api_base}/company-cache/lookup"
            payload = {"company_name": "Google", "domain": "google.com"}
            
            response = requests.post(url, headers=self.headers, json=payload)
            
            passed = response.status_code == 200
            data = response.json() if passed else {}
            
            self.log_test(
                "POST /company-cache/lookup",
                passed,
                f"Status: {response.status_code}, Found: {data.get('found', False)}"
            )
            return passed
        except Exception as e:
            self.log_test("POST /company-cache/lookup", False, str(e))
            return False
    
    def test_company_cache_enrich(self) -> bool:
        """Test: Enrich and cache company data"""
        try:
            url = f"{self.api_base}/company-cache/enrich"
            payload = TEST_COMPANIES[0]
            
            response = requests.post(url, headers=self.headers, json=payload)
            
            passed = response.status_code == 200
            data = response.json() if passed else {}
            
            self.log_test(
                "POST /company-cache/enrich",
                passed,
                f"Status: {response.status_code}, Cached: {data.get('cached', False)}"
            )
            return passed
        except Exception as e:
            self.log_test("POST /company-cache/enrich", False, str(e))
            return False
    
    def test_company_cache_stats(self) -> bool:
        """Test: Get company cache statistics"""
        try:
            url = f"{self.api_base}/company-cache/stats"
            response = requests.get(url, headers=self.headers)
            
            passed = response.status_code == 200
            data = response.json() if passed else {}
            
            self.log_test(
                "GET /company-cache/stats",
                passed,
                f"Status: {response.status_code}, Cached: {data.get('total_cached', 'N/A')}"
            )
            return passed
        except Exception as e:
            self.log_test("GET /company-cache/stats", False, str(e))
            return False
    
    def test_company_cache_performance(self) -> bool:
        """Test: Get company cache performance metrics"""
        try:
            url = f"{self.api_base}/company-cache/performance?days=30"
            response = requests.get(url, headers=self.headers)
            
            passed = response.status_code == 200
            data = response.json() if passed else {}
            
            self.log_test(
                "GET /company-cache/performance",
                passed,
                f"Status: {response.status_code}, Enrichments: {data.get('total_enrichments', 'N/A')}"
            )
            return passed
        except Exception as e:
            self.log_test("GET /company-cache/performance", False, str(e))
            return False
    
    def run_all_tests(self) -> Dict:
        """Run all tests"""
        print("\n" + "="*60)
        print("   STARTING END-TO-END TEST SUITE")
        print("="*60 + "\n")
        
        # Phase 2 Tests
        print("Phase 2: Classified Gmail Tests")
        print("-" * 40)
        self.test_classified_gmail_stats()
        self.test_classified_gmail_list()
        self.test_batch_process_emails()
        
        print("\nPhase 3: Email Patterns Tests")
        print("-" * 40)
        self.test_email_patterns_stats()
        self.test_analyze_mail_pool()
        self.test_get_pattern()
        self.test_build_email()
        
        print("\nPhase 3: Company Cache Tests")
        print("-" * 40)
        self.test_company_cache_lookup()
        self.test_company_cache_enrich()
        self.test_company_cache_stats()
        self.test_company_cache_performance()
        
        # Summary
        print("\n" + "="*60)
        print("   TEST RESULTS SUMMARY")
        print("="*60)
        print(f"Total Tests: {self.results['total_tests']}")
        print(f"✅ Passed: {self.results['passed']}")
        print(f"❌ Failed: {self.results['failed']}")
        print(f"Success Rate: {round(self.results['passed']/self.results['total_tests']*100, 1)}%")
        print("="*60 + "\n")
        
        return self.results
    
    def get_report(self) -> str:
        """Generate HTML report"""
        passed = self.results['passed']
        total = self.results['total_tests']
        success_rate = (passed / total * 100) if total > 0 else 0
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>E2E Test Report - Campaign Platform Phases 2-4</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
                .header {{ background: #2196F3; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
                .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }}
                .stat-card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
                .stat-value {{ font-size: 28px; font-weight: bold; color: #2196F3; }}
                .stat-label {{ color: #666; margin-top: 5px; }}
                .test-list {{ background: white; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
                .test-item {{ padding: 15px; border-bottom: 1px solid #eee; }}
                .test-item:last-child {{ border-bottom: none; }}
                .passed {{ color: #4CAF50; font-weight: bold; }}
                .failed {{ color: #f44336; font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Campaign Platform E2E Test Report</h1>
                <p>Phases 2-4: Classified Gmail, Email Patterns, Company Cache</p>
                <p>Generated: {datetime.utcnow().isoformat()}</p>
            </div>
            
            <div class="summary">
                <div class="stat-card">
                    <div class="stat-value">{total}</div>
                    <div class="stat-label">Total Tests</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" style="color: #4CAF50;">{passed}</div>
                    <div class="stat-label">Passed</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" style="color: #f44336;">{total - passed}</div>
                    <div class="stat-label">Failed</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{round(success_rate, 1)}%</div>
                    <div class="stat-label">Success Rate</div>
                </div>
            </div>
            
            <div class="test-list">
                <h3>Test Results</h3>
        """
        
        for test in self.results['tests']:
            status_class = "passed" if test['passed'] else "failed"
            status_text = "✅ PASSED" if test['passed'] else "❌ FAILED"
            
            html += f"""
                <div class="test-item">
                    <div class="{status_class}">{status_text}</div>
                    <div><strong>{test['name']}</strong></div>
                    {f"<div>{test['details']}</div>" if test['details'] else ""}
                </div>
            """
        
        html += """
            </div>
        </body>
        </html>
        """
        
        return html


def main():
    """Run test suite"""
    suite = E2ETestSuite()
    results = suite.run_all_tests()
    
    # Save report
    report = suite.get_report()
    with open("e2e_test_report.html", "w") as f:
        f.write(report)
    
    print(f"Report saved to e2e_test_report.html")
    
    # Return exit code based on success
    return 0 if results['failed'] == 0 else 1


if __name__ == "__main__":
    exit(main())
