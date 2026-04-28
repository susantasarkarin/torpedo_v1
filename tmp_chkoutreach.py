import subprocess, json

result = subprocess.run(
    ['curl', '-s', 'http://localhost:8000/api/cold-outreach/campaigns',
     '-H', 'Authorization: test'],
    capture_output=True, text=True, timeout=10
)
try:
    d = json.loads(result.stdout)
    print("basket_counts:", d.get('basket_counts', {}))
    print("total_leads:", d.get('total_leads', 0))
    print("num_campaigns:", len(d.get('campaigns', [])))
except Exception as e:
    print("Error:", e)
    print("Raw:", result.stdout[:500])
