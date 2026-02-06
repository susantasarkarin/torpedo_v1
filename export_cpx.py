import json
import csv

# Load CPX response
with open('cpx_response.json', 'r', encoding='utf-8-sig') as f:
    d = json.load(f)

# Export to CSV
with open('cpx_surveys.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow([
        'survey_id', 'category', 'loi', 'payout_publisher_usd', 
        'quality_score', 'conversion_rate', 'click_to_okay_rate', 
        'type', 'href_new', 'href'
    ])
    
    for s in d['surveys']:
        w.writerow([
            s['id'],
            s.get('category', ''),
            s['loi'],
            s['payout_publisher_usd'],
            s['quality_score'],
            s['conversion_rate'],
            s['click_to_okay_rate'],
            s['type'],
            s.get('href_new', ''),
            s.get('href', '')
        ])

print(f"Exported {len(d['surveys'])} surveys to cpx_surveys.csv")
