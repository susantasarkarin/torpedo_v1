"""Compare VM vs localhost ingestion.py"""
import difflib

with open('backend/leads/ingestion.py') as f:
    local_lines = f.readlines()

with open('backend/leads/ingestion_vm.py') as f:
    vm_lines = f.readlines()

print(f"Local file: {len(local_lines)} lines")
print(f"VM file: {len(vm_lines)} lines")

# Count meaningful differences
diff = list(difflib.unified_diff(vm_lines, local_lines, lineterm='', fromfile='VM', tofile='LOCAL'))
adds = len([d for d in diff if d.startswith('+') and not d.startswith('+++')])
removes = len([d for d in diff if d.startswith('-') and not d.startswith('---')])

print(f"\nDifferences: +{adds} lines in LOCAL, -{removes} lines from VM")

# Show first 50 diff lines
print("\nFirst differences:")
for line in diff[:50]:
    print(line[:120])
