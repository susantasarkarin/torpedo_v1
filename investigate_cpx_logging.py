#!/usr/bin/env python3
"""
Investigation script for CPX postback redirect logging discrepancy
Checks:
1. Collection initialization status
2. Database state (postback logs vs callback logs)
3. Code path analysis
4. Field name consistency
"""

import re
from pathlib import Path

def analyze_collection_initialization():
    """Check if cpx_callback_logs is properly initialized and injected"""
    print("\n" + "="*70)
    print("ANALYSIS 1: Collection Initialization in main.py")
    print("="*70)
    
    main_py = Path("backend/main.py")
    content = main_py.read_text(encoding='utf-8', errors='ignore')
    
    # Find CPX callback logs initialization
    callback_init = re.search(
        r'cpx_callback_logs_collection\s*=\s*traffic_db\["cpx_callback_logs"\]',
        content
    )
    
    # Find injection into traffic router
    callback_inject = re.search(
        r'traffic_router\.set_cpx_callback_logs_collection\(cpx_callback_logs_collection\)',
        content
    )
    
    # Find postback logs initialization (for comparison)
    postback_init = re.search(
        r'cpx_postback_logs.*=\s*traffic_db\["cpx_postback_logs"\]',
        content
    )
    
    print(f"✓ CPX callback logs collection initialized: {bool(callback_init)}")
    if callback_init:
        print(f"  Location: Line {content[:callback_init.start()].count(chr(10)) + 1}")
    
    print(f"✓ CPX callback logs injected into traffic_router: {bool(callback_inject)}")
    if callback_inject:
        print(f"  Location: Line {content[:callback_inject.start()].count(chr(10)) + 1}")
    
    print(f"✓ CPX postback logs initialized: {bool(postback_init)}")
    
    return bool(callback_init and callback_inject)


def analyze_endpoint_logging():
    """Check /cpx-response endpoint logging implementation"""
    print("\n" + "="*70)
    print("ANALYSIS 2: /cpx-response Endpoint Logging Code")
    print("="*70)
    
    traffic_py = Path("backend/routers/traffic.py")
    content = traffic_py.read_text(encoding='utf-8', errors='ignore')
    
    # Find the logging code
    log_pattern = r'if cpx_callback_logs_collection is not None:\s*try:\s*cpx_callback_logs_collection\.insert_one\(log_entry\)'
    
    logging_code = re.search(log_pattern, content, re.DOTALL)
    
    print(f"✓ Logging code exists: {bool(logging_code)}")
    if logging_code:
        line_num = content[:logging_code.start()].count('\n') + 1
        print(f"  Location: Line {line_num}")
    
    # Check for error logging as well
    error_log = re.search(
        r'cpx_callback_logs_collection\.insert_one\(error_log\)',
        content
    )
    print(f"✓ Error logging code exists: {bool(error_log)}")
    
    # Find log_entry structure
    log_entry_pattern = r'log_entry\s*=\s*\{([^}]+)\}'
    log_entry = re.search(log_entry_pattern, content, re.DOTALL)
    
    if log_entry:
        fields = re.findall(r'"([^"]+)"\s*:', log_entry.group(1))
        print(f"\n  Log entry fields: {len(fields)}")
        for field in fields[:10]:
            print(f"    - {field}")
        if len(fields) > 10:
            print(f"    ... and {len(fields)-10} more")
    
    return bool(logging_code)


def analyze_postback_logging():
    """Check /cpx-postback endpoint logging to compare"""
    print("\n" + "="*70)
    print("ANALYSIS 3: /cpx-postback Endpoint (for comparison)")
    print("="*70)
    
    cpx_api = Path("backend/routers/cpx_api.py")
    if not cpx_api.exists():
        print("⚠️ cpx_api.py not found")
        return False
    
    content = cpx_api.read_text(encoding='utf-8', errors='ignore')
    
    # Find postback logging
    postback_log = re.search(
        r'def _log_postback\([^)]+\):|cpx_postback_logs_collection\.insert_one\(',
        content
    )
    
    print(f"✓ Postback logging function/code exists: {bool(postback_log)}")
    
    # Find subid field in logging
    subid_log = re.search(r'"subid"\s*:\s*subid', content)
    print(f"✓ Postback logs 'subid' field: {bool(subid_log)}")
    
    return bool(postback_log)


def analyze_field_name_consistency():
    """Check if field names match between postback logging and callback lookup"""
    print("\n" + "="*70)
    print("ANALYSIS 4: Field Name Consistency (Critical Check)")
    print("="*70)
    
    # Check postback logging
    cpx_api = Path("backend/routers/cpx_api.py")
    if cpx_api.exists():
        content = cpx_api.read_text(encoding='utf-8', errors='ignore')
        
        # Find what field name is used for logging the SFWID
        postback_subid = re.search(r'"subid"\s*:\s*subid', content)
        if postback_subid:
            print("✓ Postback logs use field name: 'subid'")
        else:
            print("⚠️ Could not find 'subid' field in postback logging")
    
    # Check callback lookup
    traffic_py = Path("backend/routers/traffic.py")
    content = traffic_py.read_text(encoding='utf-8', errors='ignore')
    
    # Find postback lookup query
    lookup_pattern = r'cpx_postback_logs_collection\.find_one\(\{\s*"([^"]+)"\s*:\s*decoded_sfwid'
    lookup = re.search(lookup_pattern, content)
    
    if lookup:
        field_name = lookup.group(1)
        print(f"✓ Callback lookup queries by field: '{field_name}'")
        
        if field_name == "subid":
            print("  ✅ FIELD NAMES MATCH! (/cpx-response queries by 'subid')")
        else:
            print(f"  ⚠️ FIELD NAME MISMATCH! Expected 'subid', but looking for '{field_name}'")
    else:
        print("⚠️ Could not find postback lookup query in /cpx-response handler")
    
    return True


def analyze_redirect_flow():
    """Analyze the redirect flow to understand where logging happens"""
    print("\n" + "="*70)
    print("ANALYSIS 5: Redirect Flow & Logging Sequence")
    print("="*70)
    
    traffic_py = Path("backend/routers/traffic.py")
    content = traffic_py.read_text(encoding='utf-8', errors='ignore')
    
    # Find the handler function
    handler_match = re.search(r'@.*?router\.get\("/cpx-response".*?\)\s*(?:async\s+)?def\s+(\w+)', content, re.DOTALL)
    
    if handler_match:
        func_name = handler_match.group(1)
        print(f"✓ Handler function found: {func_name}")
    
    # Check flow order
    flow_checks = [
        ("Postback verification", r'cpx_postback_logs_collection\.find_one\('),
        ("Traffic record lookup", r'url_parameters_collection\.find_one\('),
        ("Vendor lookup", r'vendors_collection\.find_one\('),
        ("Traffic record update", r'url_parameters_collection\.update_one\(|traffic_service\.update_traffic_status'),
        ("Callback logging", r'cpx_callback_logs_collection\.insert_one\(log_entry\)'),
        ("Redirect response", r'RedirectResponse\(url=vendor_redirect_url\)')
    ]
    
    print("\n  Flow sequence:")
    for step_name, pattern in flow_checks:
        found = bool(re.search(pattern, content))
        status = "✓" if found else "⚠️"
        print(f"  {status} {step_name}")
    
    return True


def check_global_variable_injection():
    """Check how collections are injected as globals"""
    print("\n" + "="*70)
    print("ANALYSIS 6: Global Variable Injection Pattern")
    print("="*70)
    
    traffic_py = Path("backend/routers/traffic.py")
    content = traffic_py.read_text(encoding='utf-8', errors='ignore')
    
    # Check for global declarations
    globals_declared = re.findall(
        r'global\s+(\w+)',
        content
    )
    
    print(f"✓ Global variables declared in traffic.py: {len(globals_declared)}")
    for var in globals_declared[:5]:
        print(f"  - {var}")
    if len(globals_declared) > 5:
        print(f"  ... and {len(globals_declared)-5} more")
    
    # Check for setter methods in TrafficRouter
    traffic_router_file = Path("backend/routers/traffic_router.py")
    if traffic_router_file.exists():
        router_content = traffic_router_file.read_text(encoding='utf-8', errors='ignore')
        
        setters = re.findall(r'def set_(\w+)\(self', router_content)
        print(f"\n✓ TrafficRouter setter methods: {len(setters)}")
        
        if 'cpx_callback_logs_collection' in router_content:
            print("  ✓ cpx_callback_logs_collection setter found")
        else:
            print("  ⚠️ cpx_callback_logs_collection setter NOT found")
    
    return True


def main():
    print("\n" + "="*70)
    print("CPX POSTBACK REDIRECT LOGGING INVESTIGATION")
    print("="*70)
    
    results = {
        "Initialization": analyze_collection_initialization(),
        "Endpoint Logging": analyze_endpoint_logging(),
        "Postback Logging": analyze_postback_logging(),
        "Field Consistency": analyze_field_name_consistency(),
        "Redirect Flow": analyze_redirect_flow(),
        "Global Variables": check_global_variable_injection(),
    }
    
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    for analysis, result in results.items():
        status = "✓" if result else "⚠️"
        print(f"{status} {analysis}")
    
    print("\n" + "="*70)
    print("NEXT STEPS")
    print("="*70)
    print("""
1. If collection initialization passed:
   - Check if MongoDB is running and accessible
   - Verify database collections exist in traffic_flow_db
   
2. If endpoint logging code exists:
   - Check production logs to see if /cpx-response is being called
   - Look for "Logged CPX callback" messages in logs
   
3. If field names match:
   - Verify postback records actually have the 'subid' field populated
   - Check if SFWID encoding/decoding is correct
   
4. If redirect flow is complete:
   - Run end-to-end test with real CPX user redirect
   - Monitor logs and database in real-time
    """)


if __name__ == "__main__":
    main()
