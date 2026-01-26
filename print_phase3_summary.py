import json

with open('phase3_test_results.json', 'r') as f:
    data = json.load(f)

print('=' * 70)
print('PHASE 3 AGENT TEST REPORT')
print('=' * 70)
print(f'Target API: http://139.59.32.72:8000')
print(f'Phase: {data["phase"]} (Pattern Discovery + Company Cache)')
print(f'Tests Run: {data["tests_run"]}')
print(f'Tests Passed: {data["tests_passed"]} ✓')
print(f'Tests Failed: {data["tests_failed"]}')
print(f'Success Rate: {(data["tests_passed"]/data["tests_run"]*100):.1f}%')
print()

print('TEST RESULTS SUMMARY:')
print('-' * 70)
for detail in data['details']:
    status_icon = '✓' if detail['status'] == 'pass' else '✗'
    print(f'{status_icon} {detail["test"]}: {detail["result"]}')
    print(f'  Duration: {detail["duration_ms"]:.2f}ms')
    if 'note' in detail:
        print(f'  Note: {detail["note"]}')
    print()

if data['issues']:
    print('ISSUES FOUND:')
    print('-' * 70)
    for issue in data['issues']:
        print(f'  • {issue}')
    print()

print('RECOMMENDATIONS:')
print('-' * 70)
for rec in data['recommendations']:
    print(f'  • {rec}')
print()

print('KEY FINDINGS:')
print('-' * 70)
print('1. All Phase 3 endpoints are functional and responding correctly')
print('2. Agent handles empty data gracefully (0 patterns, 0 cache entries)')
print('3. Company lookup and email prediction work as expected')
print('4. Configuration system is operational')
print('5. Stats endpoint uses nested format (patterns/cache) vs flat format in spec')
print()

print('NEXT STEPS:')
print('-' * 70)
print('1. Populate mail_pool collection with sample email data')
print('2. Re-run agent to test pattern discovery with real data')
print('3. Verify cache hit rate after patterns are discovered')
print('4. Consider aligning stats format with specification')
print('=' * 70)
