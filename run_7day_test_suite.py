#!/usr/bin/env python
"""
Comprehensive 7-Day Change Test Suite
Automatically tests all changes made in the past 7 days for both Backend and Frontend
"""

import os
import sys
import subprocess
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

# Get the root directory
ROOT_DIR = Path(__file__).parent.absolute()
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "Campaign_platform"

class TestRunner:
    def __init__(self):
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "backend": {
                "unit_tests": {"total": 0, "passed": 0, "failed": 0, "errors": []},
                "integration_tests": {"total": 0, "passed": 0, "failed": 0, "errors": []},
                "manual_tests": {"total": 0, "passed": 0, "failed": 0, "errors": []}
            },
            "frontend": {
                "build_test": {"passed": False, "errors": []},
                "lint_test": {"passed": False, "errors": []}
            },
            "summary": {}
        }
        self.backend_python = sys.executable if hasattr(sys, 'base_prefix') else "python"
        
    def run_command(self, cmd: List[str], cwd: Path = None, verbose: bool = True) -> tuple[bool, str]:
        """Run a command and return success status and output"""
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd or ROOT_DIR,
                capture_output=True,
                text=True,
                timeout=300
            )
            if verbose:
                print(f"{'✓' if result.returncode == 0 else '✗'} {' '.join(cmd)}")
                if result.stdout:
                    print(result.stdout[:500])  # Print first 500 chars
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            error = f"Command timed out: {' '.join(cmd)}"
            print(f"✗ {error}")
            return False, error
        except Exception as e:
            error = f"Error running command: {str(e)}"
            print(f"✗ {error}")
            return False, error

    def test_backend(self):
        """Test backend changes"""
        print("\n" + "="*70)
        print("BACKEND TESTING")
        print("="*70)
        
        # Test 1: Check if Python dependencies are installed
        print("\n1. Checking Backend Dependencies...")
        success, output = self.run_command(
            [sys.executable, "-m", "pip", "check"],
            cwd=BACKEND_DIR
        )
        
        if not success:
            print("⚠️ Some dependencies may have issues:")
            print(output[:300])
        
        # Test 2: Run Phase 3 Agent Tests
        print("\n2. Running Phase 3 Agent Tests...")
        phase3_test_file = ROOT_DIR / "test_phase3_agent.py"
        if phase3_test_file.exists():
            success, output = self.run_command(
                [sys.executable, str(phase3_test_file)],
                verbose=False
            )
            self.results["backend"]["integration_tests"]["total"] += 1
            if success:
                self.results["backend"]["integration_tests"]["passed"] += 1
            else:
                self.results["backend"]["integration_tests"]["failed"] += 1
                self.results["backend"]["integration_tests"]["errors"].append("Phase 3 agent test failed")
        
        # Test 3: Run Phase 4 Agent Tests
        print("\n3. Running Phase 4 Agent Tests...")
        phase4_test_file = ROOT_DIR / "test_phase4_agent.py"
        if phase4_test_file.exists():
            success, output = self.run_command(
                [sys.executable, str(phase4_test_file)],
                verbose=False
            )
            self.results["backend"]["integration_tests"]["total"] += 1
            if success:
                self.results["backend"]["integration_tests"]["passed"] += 1
            else:
                self.results["backend"]["integration_tests"]["failed"] += 1
                self.results["backend"]["integration_tests"]["errors"].append("Phase 4 agent test failed")
        
        # Test 4: Run E2E Phase 2-4 Tests
        print("\n4. Running E2E Phase 2-4 Tests...")
        e2e_test_file = ROOT_DIR / "test_e2e_phases_2_4.py"
        if e2e_test_file.exists():
            success, output = self.run_command(
                [sys.executable, str(e2e_test_file)],
                verbose=False
            )
            self.results["backend"]["integration_tests"]["total"] += 1
            if success:
                self.results["backend"]["integration_tests"]["passed"] += 1
            else:
                self.results["backend"]["integration_tests"]["failed"] += 1
                self.results["backend"]["integration_tests"]["errors"].append("E2E Phase 2-4 test failed")
        
        # Test 5: Syntax check on modified backend files
        print("\n5. Checking Python Syntax for Backend Changes...")
        backend_python_files = [
            BACKEND_DIR / "main.py",
            BACKEND_DIR / "background_job_scheduler.py",
            BACKEND_DIR / "email_import_filtered.py",
            BACKEND_DIR / "leads" / "multi_agent_router.py",
            BACKEND_DIR / "leads" / "gemini_enrichment.py",
            BACKEND_DIR / "routers" / "classified_gmail.py",
            BACKEND_DIR / "routers" / "settings.py",
            BACKEND_DIR / "routers" / "company_cache.py",
            BACKEND_DIR / "routers" / "email_patterns.py"
        ]
        
        syntax_errors = []
        for py_file in backend_python_files:
            if py_file.exists():
                success, output = self.run_command(
                    [sys.executable, "-m", "py_compile", str(py_file)],
                    verbose=False
                )
                self.results["backend"]["unit_tests"]["total"] += 1
                if success:
                    self.results["backend"]["unit_tests"]["passed"] += 1
                else:
                    self.results["backend"]["unit_tests"]["failed"] += 1
                    syntax_errors.append(f"{py_file.name}: {output}")
        
        if syntax_errors:
            self.results["backend"]["unit_tests"]["errors"].extend(syntax_errors)
        
        print(f"✓ Syntax check completed: {self.results['backend']['unit_tests']['passed']}/{self.results['backend']['unit_tests']['total']} files OK")
        
    def test_frontend(self):
        """Test frontend changes"""
        print("\n" + "="*70)
        print("FRONTEND TESTING")
        print("="*70)
        
        if not FRONTEND_DIR.exists():
            print("⚠️ Frontend directory not found")
            return
        
        # Test 1: Install dependencies
        print("\n1. Installing Frontend Dependencies...")
        if (FRONTEND_DIR / "package.json").exists():
            success, output = self.run_command(
                ["npm", "install"],
                cwd=FRONTEND_DIR,
                verbose=False
            )
            if not success:
                print("⚠️ npm install had issues (this may be normal if node_modules exists)")
        
        # Test 2: Build test
        print("\n2. Running Frontend Build Test...")
        success, output = self.run_command(
            ["npm", "run", "build"],
            cwd=FRONTEND_DIR,
            verbose=False
        )
        self.results["frontend"]["build_test"]["passed"] = success
        if not success:
            self.results["frontend"]["build_test"]["errors"].append(output[-500:] if output else "Build failed")
            print(f"✗ Build test failed")
        else:
            print(f"✓ Build test passed")
        
        # Test 3: Linting (if eslint is configured)
        print("\n3. Running Frontend Linting...")
        if (FRONTEND_DIR / "eslint.config.js").exists():
            success, output = self.run_command(
                ["npm", "run", "lint"],
                cwd=FRONTEND_DIR,
                verbose=False
            )
            self.results["frontend"]["lint_test"]["passed"] = success
            if not success:
                self.results["frontend"]["lint_test"]["errors"].append(output[-500:] if output else "Lint failed")
                print(f"✗ Linting test had warnings")
            else:
                print(f"✓ Linting passed")
        
        # Test 4: Check for common issues in React components
        print("\n4. Checking React Component Structure...")
        jsx_files = [
            FRONTEND_DIR / "src" / "pages" / "sales" / "ClassifiedGmail.jsx",
            FRONTEND_DIR / "src" / "App.jsx"
        ]
        
        component_errors = []
        for jsx_file in jsx_files:
            if jsx_file.exists():
                try:
                    with open(jsx_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Basic checks
                        if 'import React' in content or 'from "react"' in content or 'react' in content:
                            if 'export' in content:
                                print(f"✓ {jsx_file.name}: Valid React component structure")
                            else:
                                component_errors.append(f"{jsx_file.name}: Missing export statement")
                        else:
                            component_errors.append(f"{jsx_file.name}: Missing React import")
                except Exception as e:
                    component_errors.append(f"{jsx_file.name}: {str(e)}")
        
        if component_errors:
            self.results["frontend"]["build_test"]["errors"].extend(component_errors)

    def generate_report(self):
        """Generate test report"""
        print("\n" + "="*70)
        print("TEST SUMMARY REPORT")
        print("="*70)
        
        # Backend summary
        backend_unit = self.results["backend"]["unit_tests"]
        backend_int = self.results["backend"]["integration_tests"]
        
        backend_total = backend_unit["total"] + backend_int["total"]
        backend_passed = backend_unit["passed"] + backend_int["passed"]
        backend_failed = backend_unit["failed"] + backend_int["failed"]
        
        print(f"\n📦 BACKEND TESTS:")
        print(f"  Unit Tests:        {backend_unit['passed']}/{backend_unit['total']} passed")
        print(f"  Integration Tests: {backend_int['passed']}/{backend_int['total']} passed")
        print(f"  Total:             {backend_passed}/{backend_total} passed")
        
        if backend_unit["errors"]:
            print(f"  Errors: {len(backend_unit['errors'])} syntax errors detected")
        
        # Frontend summary
        print(f"\n🎨 FRONTEND TESTS:")
        print(f"  Build Test:  {'✓ PASSED' if self.results['frontend']['build_test']['passed'] else '✗ FAILED'}")
        print(f"  Lint Test:   {'✓ PASSED' if self.results['frontend']['lint_test']['passed'] else '✗ FAILED'}")
        
        # Overall summary
        total_critical = backend_total + 2  # +2 for build and lint
        total_passed = backend_passed + sum([1 for test in [self.results['frontend']['build_test']['passed'], 
                                                             self.results['frontend']['lint_test']['passed']] if test])
        
        self.results["summary"] = {
            "total_tests": total_critical,
            "passed": total_passed,
            "failed": total_critical - total_passed,
            "success_rate": f"{(total_passed/total_critical*100):.1f}%" if total_critical > 0 else "0%"
        }
        
        print(f"\n{'='*70}")
        print(f"🎯 OVERALL RESULTS: {total_passed}/{total_critical} tests passed ({self.results['summary']['success_rate']})")
        print(f"{'='*70}")
        
        # Save results
        report_file = ROOT_DIR / f"test_results_7day_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        
        print(f"\n📊 Full report saved to: {report_file}")
        
        return self.results

def main():
    """Run all tests"""
    print(f"Starting 7-Day Change Test Suite at {datetime.now().isoformat()}")
    print(f"Root Directory: {ROOT_DIR}")
    
    runner = TestRunner()
    
    try:
        runner.test_backend()
        runner.test_frontend()
        results = runner.generate_report()
        
        # Exit with appropriate code
        if results["summary"]["failed"] > 0:
            sys.exit(1)
        else:
            sys.exit(0)
    
    except Exception as e:
        print(f"\n❌ Error running tests: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
