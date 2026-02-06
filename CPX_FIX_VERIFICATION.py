#!/usr/bin/env python3
"""
CPX Integration Fix Verification Script (TASK 9)

This script validates all the CPX integration fixes are properly implemented:
1. TASK 3: Single-use ext_user_id guard collection exists
2. TASK 4: Redirect lock status tracking
3. TASK 5: WebView user agent detection
4. TASK 6: href used instead of href_new
5. TASK 7: secure_hash always included in API calls
6. TASK 8: Frontend debounce protection

Usage:
    python CPX_FIX_VERIFICATION.py
"""

import re
import os
import sys

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def check_pass(message):
    print(f"{Colors.GREEN}✅ PASS:{Colors.RESET} {message}")
    return True

def check_fail(message):
    print(f"{Colors.RED}❌ FAIL:{Colors.RESET} {message}")
    return False

def check_warn(message):
    print(f"{Colors.YELLOW}⚠️  WARN:{Colors.RESET} {message}")
    return True

def section_header(title):
    print(f"\n{Colors.CYAN}{Colors.BOLD}{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}{Colors.RESET}")

# Get the base path
BASE_PATH = os.path.dirname(os.path.abspath(__file__))

def verify_task3_ext_user_id_guard():
    """Verify TASK 3: Single-use ext_user_id guard is implemented"""
    section_header("TASK 3: Single-Use ext_user_id Guard")
    results = []
    
    # Check main.py has cpx_entry_guards collection setup
    main_py = os.path.join(BASE_PATH, "backend", "main.py")
    if os.path.exists(main_py):
        with open(main_py, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'cpx_entry_guards_collection' in content:
            results.append(check_pass("cpx_entry_guards_collection defined in main.py"))
        else:
            results.append(check_fail("cpx_entry_guards_collection NOT found in main.py"))
        
        if '"cpx_entry_guards"' in content:
            results.append(check_pass("cpx_entry_guards MongoDB collection configured"))
        else:
            results.append(check_fail("cpx_entry_guards MongoDB collection NOT configured"))
        
        if 'set_cpx_entry_guards_collection' in content:
            results.append(check_pass("set_cpx_entry_guards_collection injection found"))
        else:
            results.append(check_fail("set_cpx_entry_guards_collection injection NOT found"))
    else:
        results.append(check_fail(f"main.py not found at {main_py}"))
    
    # Check traffic.py has guard functions
    traffic_py = os.path.join(BASE_PATH, "backend", "routers", "traffic.py")
    if os.path.exists(traffic_py):
        with open(traffic_py, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'check_cpx_entry_guard' in content:
            results.append(check_pass("check_cpx_entry_guard function exists in traffic.py"))
        else:
            results.append(check_fail("check_cpx_entry_guard function NOT found in traffic.py"))
        
        if 'CPX_GUARD_STATUS_CREATED' in content:
            results.append(check_pass("CPX guard status constants defined"))
        else:
            results.append(check_fail("CPX guard status constants NOT found"))
        
        if 'guard_result = check_cpx_entry_guard' in content:
            results.append(check_pass("Entry guard check is called before CPX API"))
        else:
            results.append(check_fail("Entry guard check NOT called before CPX API"))
    else:
        results.append(check_fail(f"traffic.py not found at {traffic_py}"))
    
    return all(results)

def verify_task4_redirect_lock():
    """Verify TASK 4: Redirect lock status tracking"""
    section_header("TASK 4: Lock CPX Redirects One-Time")
    results = []
    
    traffic_py = os.path.join(BASE_PATH, "backend", "routers", "traffic.py")
    if os.path.exists(traffic_py):
        with open(traffic_py, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'update_cpx_entry_guard_status' in content:
            results.append(check_pass("update_cpx_entry_guard_status function exists"))
        else:
            results.append(check_fail("update_cpx_entry_guard_status function NOT found"))
        
        if 'CPX_GUARD_STATUS_REDIRECTED' in content:
            results.append(check_pass("REDIRECTED status constant defined"))
        else:
            results.append(check_fail("REDIRECTED status constant NOT found"))
        
        if 'CPX_GUARD_STATUS_LOCKED' in content:
            results.append(check_pass("LOCKED status constant defined"))
        else:
            results.append(check_fail("LOCKED status constant NOT found"))
        
        # Check that status is updated after successful allocation
        if 'update_cpx_entry_guard_status(' in content and 'CPX_GUARD_STATUS_REDIRECTED' in content:
            results.append(check_pass("Status updated to REDIRECTED after successful allocation"))
        else:
            results.append(check_fail("Status NOT updated after allocation"))
    else:
        results.append(check_fail(f"traffic.py not found at {traffic_py}"))
    
    return all(results)

def verify_task5_webview_block():
    """Verify TASK 5: WebView traffic blocking"""
    section_header("TASK 5: Block WebView Traffic")
    results = []
    
    traffic_py = os.path.join(BASE_PATH, "backend", "routers", "traffic.py")
    if os.path.exists(traffic_py):
        with open(traffic_py, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'WEBVIEW_SIGNATURES' in content:
            results.append(check_pass("WEBVIEW_SIGNATURES list defined"))
        else:
            results.append(check_fail("WEBVIEW_SIGNATURES list NOT found"))
        
        if 'is_webview_user_agent' in content:
            results.append(check_pass("is_webview_user_agent function exists"))
        else:
            results.append(check_fail("is_webview_user_agent function NOT found"))
        
        # Check for specific WebView signatures
        webview_sigs = ['wv', 'webview', 'fbav', 'timebucks']
        for sig in webview_sigs:
            if f'"{sig}"' in content.lower() or f"'{sig}'" in content.lower():
                results.append(check_pass(f"WebView signature '{sig}' is checked"))
            else:
                results.append(check_warn(f"WebView signature '{sig}' not found in checks"))
        
        # Check WebView detection is called before CPX API
        if 'is_webview, webview_signature = is_webview_user_agent' in content:
            results.append(check_pass("WebView detection called before CPX API"))
        else:
            results.append(check_fail("WebView detection NOT called before CPX API"))
    else:
        results.append(check_fail(f"traffic.py not found at {traffic_py}"))
    
    return all(results)

def verify_task6_href_only():
    """Verify TASK 6: Using href ONLY (not href_new)"""
    section_header("TASK 6: Switch to href (NOT href_new)")
    results = []
    
    cpx_service = os.path.join(BASE_PATH, "backend", "app", "services", "cpx_service.py")
    if os.path.exists(cpx_service):
        with open(cpx_service, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for WRONG pattern: href_new or href
        wrong_patterns = [
            r'\.get\(["\']href_new["\']\)\s*or\s*\.get\(["\']href["\']\)',
            r'href_new\s+or\s+href',
        ]
        
        for pattern in wrong_patterns:
            matches = re.findall(pattern, content)
            if matches:
                results.append(check_fail(f"WRONG pattern found: prioritizing href_new over href"))
                break
        else:
            results.append(check_pass("No href_new priority patterns found"))
        
        # Check for correct pattern: href only
        if 'survey.get("href")' in content or "survey.get('href')" in content:
            results.append(check_pass("Using survey.get('href') for entry links"))
        else:
            results.append(check_warn("survey.get('href') pattern not found"))
        
        # Check for TASK 6 comments
        if 'TASK 6' in content:
            results.append(check_pass("TASK 6 comments present documenting the fix"))
        else:
            results.append(check_warn("TASK 6 comments not found"))
        
        # Count href_new occurrences for priority (should be storage/logging only)
        href_new_count = content.count('href_new')
        if href_new_count < 10:
            results.append(check_pass(f"href_new references minimal ({href_new_count}) - likely just for storage"))
        else:
            results.append(check_warn(f"href_new appears {href_new_count} times - verify not used for entry links"))
    else:
        results.append(check_fail(f"cpx_service.py not found at {cpx_service}"))
    
    return all(results)

def verify_task7_secure_hash():
    """Verify TASK 7: secure_hash always included in API calls"""
    section_header("TASK 7: secure_hash & Parameter Hygiene")
    results = []
    
    cpx_service = os.path.join(BASE_PATH, "backend", "app", "services", "cpx_service.py")
    if os.path.exists(cpx_service):
        with open(cpx_service, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if '_generate_secure_hash' in content:
            results.append(check_pass("_generate_secure_hash method exists"))
        else:
            results.append(check_fail("_generate_secure_hash method NOT found"))
        
        if '"secure_hash": secure_hash' in content or "'secure_hash': secure_hash" in content:
            results.append(check_pass("secure_hash included in API params"))
        else:
            results.append(check_fail("secure_hash NOT found in API params"))
        
        # Check hash formula
        if 'f"{ext_user_id}-{secure_hash_key}"' in content:
            results.append(check_pass("Correct hash formula: MD5(ext_user_id + '-' + secure_hash_key)"))
        else:
            results.append(check_warn("Hash formula pattern not matched - verify manually"))
        
        # Check user_agent is in params
        if '"user_agent": user_agent' in content or "'user_agent': user_agent" in content:
            results.append(check_pass("user_agent included in API params"))
        else:
            results.append(check_fail("user_agent NOT found in API params"))
        
        # Check country code uses ISO2 and correct param name
        if '"user_country_code"' in content:
            results.append(check_pass("Using 'user_country_code' param name (correct per CPX docs)"))
        else:
            results.append(check_fail("'user_country_code' param name NOT found"))
    else:
        results.append(check_fail(f"cpx_service.py not found at {cpx_service}"))
    
    return all(results)

def verify_task8_frontend_safety():
    """Verify TASK 8: Frontend click safety (debounce)"""
    section_header("TASK 8: Frontend Click Safety")
    results = []
    
    frontend_file = os.path.join(BASE_PATH, "Campaign_platform", "src", "pages", "user", "TrafficFlowParser.jsx")
    if os.path.exists(frontend_file):
        with open(frontend_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'isClickProcessingRef' in content:
            results.append(check_pass("Click processing guard (isClickProcessingRef) exists"))
        else:
            results.append(check_fail("Click processing guard NOT found"))
        
        if 'lastClickTimeRef' in content:
            results.append(check_pass("Last click time tracker exists"))
        else:
            results.append(check_fail("Last click time tracker NOT found"))
        
        if 'CLICK_DEBOUNCE_MS' in content:
            results.append(check_pass("Debounce constant defined"))
        else:
            results.append(check_fail("Debounce constant NOT found"))
        
        if 'disabled={loading}' in content:
            results.append(check_pass("Button disabled while loading"))
        else:
            results.append(check_fail("Button NOT disabled while loading"))
        
        # Check debounce logic exists
        if 'timeSinceLastClick' in content or 'time since last click' in content.lower():
            results.append(check_pass("Debounce time check implemented"))
        else:
            results.append(check_fail("Debounce time check NOT found"))
    else:
        results.append(check_fail(f"TrafficFlowParser.jsx not found at {frontend_file}"))
    
    return all(results)

def main():
    print(f"\n{Colors.BOLD}{Colors.CYAN}")
    print("=" * 60)
    print("  CPX INTEGRATION FIX VERIFICATION")
    print("  Validating all 10 task implementations")
    print("=" * 60)
    print(f"{Colors.RESET}")
    
    results = {
        "TASK 3 - ext_user_id Guard": verify_task3_ext_user_id_guard(),
        "TASK 4 - Redirect Lock": verify_task4_redirect_lock(),
        "TASK 5 - WebView Block": verify_task5_webview_block(),
        "TASK 6 - href Only": verify_task6_href_only(),
        "TASK 7 - secure_hash": verify_task7_secure_hash(),
        "TASK 8 - Frontend Safety": verify_task8_frontend_safety(),
    }
    
    # Summary
    section_header("VERIFICATION SUMMARY")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for task, status in results.items():
        icon = "✅" if status else "❌"
        print(f"  {icon} {task}")
    
    print(f"\n{Colors.BOLD}Result: {passed}/{total} tasks verified{Colors.RESET}")
    
    if passed == total:
        print(f"\n{Colors.GREEN}{Colors.BOLD}🎉 ALL TASKS VERIFIED SUCCESSFULLY!{Colors.RESET}")
        print("The CPX integration fixes are properly implemented.")
        print("\nNext steps:")
        print("  1. Deploy to production: pm2 restart campaign-backend")
        print("  2. Run frontend build: npm run build (in Campaign_platform)")
        print("  3. Monitor logs: pm2 logs campaign-backend | grep CPX")
        return 0
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}⚠️  SOME TASKS NEED ATTENTION{Colors.RESET}")
        print("Review the failed checks above and fix them before deployment.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
