import subprocess, re

result = subprocess.run(
    ['grep', '-i', r'LeadClassif\|sync_to_enrich\|rule.based.*classif\|_run_lead_classif', 
     '/var/log/torpedo_backend.log'],
    capture_output=True, text=True
)
lines = result.stdout.strip().split('\n')
print('\n'.join(lines[-30:]))
