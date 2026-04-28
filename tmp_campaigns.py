import subprocess, json

result = subprocess.run(
    ['curl', '-s', 'http://localhost:8000/api/cold-outreach/campaigns',
     '-H', 'Authorization: test'],
    capture_output=True, text=True, timeout=10
)
d = json.loads(result.stdout)
for c in d.get('campaigns', []):
    print(f"business={c.get('business')} status={c.get('status')} enrolled={c.get('stats',{}).get('enrolled',0)} sent={c.get('stats',{}).get('sent',0)}")
