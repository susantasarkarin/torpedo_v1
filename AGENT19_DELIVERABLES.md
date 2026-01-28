# AGENT 19 - DELIVERABLES GUIDE
## Advanced Analytics, Reporting, and Executive Dashboard

**Complete implementation guide for Phase 3 analytics features**

---

## 📦 DELIVERABLE INVENTORY

### Backend Modules (4 files, 2,282 lines)

1. **backend/analytics/report_builder.py** (625 lines)
2. **backend/analytics/cohort_analysis.py** (582 lines)
3. **backend/analytics/funnel.py** (634 lines)
4. **backend/analytics/export.py** (441 lines)

### Frontend Components (2 files, 1,000 lines)

5. **frontend/src/pages/sales/ExecutiveDashboard.jsx** (476 lines)
6. **frontend/src/pages/analytics/Reports.jsx** (524 lines)

### API Routes (1 file, 489 lines)

7. **backend/routes/analytics_routes.py** (489 lines)

### Documentation (4 files)

8. **AGENT19_COMPLETION_REPORT.md**
9. **AGENT19_DELIVERABLES.md** (this file)
10. **AGENT19_QUICKREF.md**
11. **AGENT19_EXECUTION_SUMMARY.md**

---

## 🔧 INSTALLATION GUIDE

### 1. Backend Setup

#### Install Dependencies

```bash
pip install pandas reportlab xlsxwriter apscheduler python-dateutil
```

#### Create Analytics Directory

```bash
mkdir -p backend/analytics
```

#### Copy Backend Files

```bash
# Copy all analytics modules
cp report_builder.py backend/analytics/
cp cohort_analysis.py backend/analytics/
cp funnel.py backend/analytics/
cp export.py backend/analytics/
```

#### Update Main Application

```python
# In backend/app.py or main.py
from routes.analytics_routes import analytics_bp

app.register_blueprint(analytics_bp)
```

### 2. Frontend Setup

#### Install Dependencies

```bash
cd frontend
npm install @mui/material @mui/icons-material @mui/x-date-pickers
npm install recharts date-fns axios
```

#### Create Page Directories

```bash
mkdir -p frontend/src/pages/sales
mkdir -p frontend/src/pages/analytics
```

#### Copy Frontend Files

```bash
cp ExecutiveDashboard.jsx frontend/src/pages/sales/
cp Reports.jsx frontend/src/pages/analytics/
```

#### Update Router

```javascript
// In frontend/src/App.jsx or routes.js
import ExecutiveDashboard from './pages/sales/ExecutiveDashboard';
import Reports from './pages/analytics/Reports';

// Add routes
<Route path="/dashboard/executive" element={<ExecutiveDashboard />} />
<Route path="/analytics/reports" element={<Reports />} />
```

### 3. Database Setup

#### Create Indexes

```javascript
// In MongoDB shell or migration script
db.reports.createIndex({ "report_id": 1 }, { unique: true });
db.reports.createIndex({ "created_at": -1 });
db.scheduled_reports.createIndex({ "job_id": 1 }, { unique: true });
db.cohorts.createIndex({ "cohort_id": 1 }, { unique: true });
db.funnels.createIndex({ "funnel_id": 1 }, { unique: true });
```

---

## 📘 FEATURE GUIDES

### Report Builder

#### Creating a Custom Report

**Backend Usage**:

```python
from analytics.report_builder import report_builder

# Build report
report = report_builder.build_report(
    metrics=[
        'total_leads',
        'open_rate',
        'reply_rate',
        'meetings_booked',
        'revenue_generated'
    ],
    filters={
        'industry': 'Technology',
        'seniority': 'Director'
    },
    date_range=(
        datetime(2026, 1, 1),
        datetime(2026, 1, 31)
    ),
    group_by='week'
)

print(f"Report ID: {report['report_id']}")
print(f"KPIs: {report['kpis']}")
```

**API Request**:

```bash
curl -X POST http://localhost:5000/api/analytics/build-report \
  -H "Content-Type: application/json" \
  -d '{
    "metrics": ["open_rate", "reply_rate", "meetings_booked"],
    "filters": {"industry": "Technology"},
    "date_range": ["2026-01-01T00:00:00Z", "2026-01-31T23:59:59Z"],
    "group_by": "week"
  }'
```

**Frontend Usage**:

```javascript
// In Reports.jsx
const handleBuildReport = async () => {
  const response = await axios.post('/api/analytics/build-report', {
    metrics: selectedMetrics,
    filters: selectedFilters,
    date_range: [dateRange.start.toISOString(), dateRange.end.toISOString()],
    group_by: groupBy
  });
  
  console.log('Report created:', response.data);
};
```

#### Scheduling Recurring Reports

**Backend Usage**:

```python
# Schedule weekly report
job_id = report_builder.schedule_report(
    report_config={
        'metrics': ['open_rate', 'reply_rate'],
        'filters': {}
    },
    frequency='weekly',
    recipients=['executive@company.com', 'manager@company.com'],
    format='pdf'
)

print(f"Scheduled job: {job_id}")
```

**API Request**:

```bash
curl -X POST http://localhost:5000/api/analytics/schedule-report \
  -H "Content-Type: application/json" \
  -d '{
    "report_config": {
      "metrics": ["open_rate", "reply_rate"]
    },
    "frequency": "weekly",
    "recipients": ["exec@company.com"],
    "format": "pdf"
  }'
```

#### Exporting Reports

**Backend Usage**:

```python
# Export as PDF
pdf_bytes = report_builder.export_report('report_id_123', 'pdf')

# Save to file
with open('report.pdf', 'wb') as f:
    f.write(pdf_bytes)
```

**API Request**:

```bash
# Download PDF
curl http://localhost:5000/api/analytics/export-report/report_id_123?format=pdf \
  --output report.pdf

# Download Excel
curl http://localhost:5000/api/analytics/export-report/report_id_123?format=excel \
  --output report.xlsx
```

---

### Cohort Analysis

#### Creating a Cohort

**Backend Usage**:

```python
from analytics.cohort_analysis import cohort_analyzer

# Create cohort for Q1 2026 imports
cohort_id = cohort_analyzer.create_cohort(
    cohort_name="Q1 2026 Imports",
    criteria={
        'created_at': {
            '$gte': datetime(2026, 1, 1),
            '$lt': datetime(2026, 4, 1)
        }
    },
    cohort_type='import_date'
)

print(f"Cohort created: {cohort_id}")
```

**API Request**:

```bash
curl -X POST http://localhost:5000/api/analytics/cohorts \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Q1 2026 Imports",
    "criteria": {
      "created_at": {
        "$gte": "2026-01-01T00:00:00Z",
        "$lt": "2026-04-01T00:00:00Z"
      }
    },
    "type": "import_date"
  }'
```

#### Comparing Cohorts

**Backend Usage**:

```python
# Compare two cohorts
comparison = cohort_analyzer.compare_cohorts([
    'cohort_id_1',
    'cohort_id_2'
])

for cohort in comparison['cohorts']:
    print(f"{cohort['name']}: {cohort['metrics']['reply_rate']}% reply rate")

print(f"Insights: {comparison['insights']}")
```

**API Request**:

```bash
curl -X POST http://localhost:5000/api/analytics/cohorts/compare \
  -H "Content-Type: application/json" \
  -d '{
    "cohort_ids": ["cohort_id_1", "cohort_id_2"]
  }'
```

#### Tracking Retention

**Backend Usage**:

```python
# Get 12-week retention data
retention = cohort_analyzer.get_cohort_retention(
    cohort_id='cohort_id_123',
    period='week',
    num_periods=12
)

for period in retention['periods']:
    print(f"Week {period['period_number']}: {period['retention_rate']}% retained")
```

**API Request**:

```bash
curl http://localhost:5000/api/analytics/cohorts/cohort_id_123/retention?period=week&num_periods=12
```

#### Auto-Creating Cohorts

**Backend Usage**:

```python
# Auto-create monthly cohorts
cohort_ids = cohort_analyzer.auto_create_cohorts('import_date')
print(f"Created {len(cohort_ids)} cohorts")

# Auto-create industry cohorts
cohort_ids = cohort_analyzer.auto_create_cohorts('industry')
```

**API Request**:

```bash
curl -X POST http://localhost:5000/api/analytics/cohorts/auto-create \
  -H "Content-Type: application/json" \
  -d '{"type": "import_date"}'
```

---

### Funnel Analysis

#### Creating a Funnel

**Backend Usage**:

```python
from analytics.funnel import funnel_analyzer

# Define custom funnel
funnel_id = funnel_analyzer.define_funnel(
    funnel_name="Sales Pipeline",
    stages=[
        'Lead Created',
        'First Contact',
        'Demo Scheduled',
        'Proposal Sent',
        'Closed Won'
    ],
    funnel_type='custom'
)

print(f"Funnel created: {funnel_id}")
```

**API Request**:

```bash
curl -X POST http://localhost:5000/api/analytics/funnels \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sales Pipeline",
    "stages": [
      "Lead Created",
      "First Contact",
      "Demo Scheduled",
      "Proposal Sent",
      "Closed Won"
    ],
    "type": "custom"
  }'
```

#### Analyzing a Funnel

**Backend Usage**:

```python
# Analyze funnel for date range
analysis = funnel_analyzer.analyze_funnel(
    funnel_id='funnel_id_123',
    date_range=(
        datetime(2026, 1, 1),
        datetime(2026, 1, 31)
    ),
    filters={'industry': 'Technology'}
)

# View results
print(f"Overall conversion: {analysis['summary']['overall_conversion_rate']}%")

for stage in analysis['stages']:
    print(f"{stage['stage_name']}: {stage['count']} ({stage['conversion_rate']}%)")
```

**API Request**:

```bash
curl -X POST http://localhost:5000/api/analytics/funnels/funnel_id_123/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "date_range": ["2026-01-01T00:00:00Z", "2026-01-31T23:59:59Z"],
    "filters": {"industry": "Technology"}
  }'
```

#### Identifying Drop-offs

**Backend Usage**:

```python
# Get stages with >30% drop-off
drop_offs = funnel_analyzer.get_drop_off_points(
    funnel_id='funnel_id_123',
    threshold=30.0
)

for drop_off in drop_offs:
    print(f"{drop_off['stage_name']}: {drop_off['drop_off_percentage']}% drop-off")
    print(f"Severity: {drop_off['severity']}")
    print(f"Suggestions: {drop_off['suggestions']}")
```

**API Request**:

```bash
curl http://localhost:5000/api/analytics/funnels/funnel_id_123/drop-offs?threshold=30
```

#### Creating Default Funnels

**Backend Usage**:

```python
# Create all default funnel templates
funnel_ids = funnel_analyzer.create_default_funnels()
print(f"Created {len(funnel_ids)} default funnels")
```

**API Request**:

```bash
curl -X POST http://localhost:5000/api/analytics/funnels/create-defaults
```

---

### Executive Dashboard

#### Loading Dashboard Data

**Frontend Usage**:

```javascript
// In ExecutiveDashboard.jsx
const loadDashboardData = async () => {
  const response = await axios.get('/api/analytics/executive-dashboard', {
    params: { days: 30 }
  });
  
  setDashboardData(response.data.kpis);
  setTrendData(response.data.trends);
  setCampaignLeaderboard(response.data.top_campaigns);
  setGoalTracking(response.data.goals);
};
```

**API Request**:

```bash
# Get 30-day dashboard
curl http://localhost:5000/api/analytics/executive-dashboard?days=30

# Get 90-day dashboard
curl http://localhost:5000/api/analytics/executive-dashboard?days=90
```

#### Exporting Dashboard

**Frontend Usage**:

```javascript
const handleExport = async (format) => {
  const response = await axios.get('/api/analytics/export-dashboard', {
    params: { format, days: 30 },
    responseType: 'blob'
  });
  
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', `dashboard.${format}`);
  link.click();
};
```

**API Request**:

```bash
# Export as PDF
curl http://localhost:5000/api/analytics/export-dashboard?format=pdf&days=30 \
  --output dashboard.pdf

# Export as Excel
curl http://localhost:5000/api/analytics/export-dashboard?format=excel&days=30 \
  --output dashboard.xlsx
```

---

## 🔍 CONFIGURATION

### Report Builder Configuration

```python
# In report_builder.py

# Available metrics (can be extended)
AVAILABLE_METRICS = [
    'total_leads',
    'total_campaigns',
    'emails_sent',
    # ... add more
]

# Available filters
AVAILABLE_FILTERS = [
    'campaign_type',
    'industry',
    'seniority',
    # ... add more
]
```

### Scheduler Configuration

```python
# Configure scheduler timezone and settings
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler(
    timezone='UTC',
    job_defaults={
        'coalesce': False,
        'max_instances': 3
    }
)
scheduler.start()
```

### Export Configuration

```python
# In export.py

# PDF page size
from reportlab.lib.pagesizes import letter, A4

# Use A4 for international
doc = SimpleDocTemplate(buffer, pagesize=A4)

# Custom colors
BRAND_COLOR = colors.HexColor('#4472C4')
```

---

## 🎨 CUSTOMIZATION GUIDE

### Adding New Metrics

1. **Define metric in report_builder.py**:

```python
AVAILABLE_METRICS.append('new_metric_name')
```

2. **Add calculation method**:

```python
def _get_new_metric(self, query: Dict) -> float:
    # Calculate metric
    result = db.collection.aggregate([...])
    return result
```

3. **Add to build_report**:

```python
if 'new_metric_name' in metrics:
    kpis['new_metric_name'] = self._get_new_metric(query)
```

### Adding New Cohort Types

1. **Add to COHORT_TYPES**:

```python
COHORT_TYPES = [
    # ... existing types
    'new_cohort_type'
]
```

2. **Implement auto-creation**:

```python
elif cohort_type == 'new_cohort_type':
    # Logic to create cohorts
    values = db.leads.distinct('new_field')
    for value in values:
        cohort_id = self.create_cohort(
            cohort_name=f"New Type: {value}",
            criteria={'new_field': value},
            cohort_type='new_cohort_type'
        )
```

### Adding New Funnel Stages

1. **Define stage condition**:

```python
STAGE_CONDITIONS = {
    # ... existing conditions
    'New Stage': {
        'collection': 'leads',
        'field': 'new_status',
        'value': 'stage_value'
    }
}
```

2. **Add to default funnels**:

```python
DEFAULT_FUNNELS = {
    'new_funnel': [
        'Stage 1',
        'Stage 2',
        'New Stage',
        'Final Stage'
    ]
}
```

### Customizing Dashboard KPIs

1. **Update Executive Dashboard component**:

```javascript
// Add new KPI card
<Grid item xs={12} sm={6} md={3}>
  <KPICard
    title="New Metric"
    value={dashboardData?.new_metric || 0}
    change={dashboardData?.new_metric_change || 0}
    icon={<CustomIcon />}
    color="#CustomColor"
    format="number"
  />
</Grid>
```

2. **Update API endpoint**:

```python
@analytics_bp.route('/executive-dashboard')
def get_executive_dashboard():
    # ... existing code
    kpis['new_metric'] = calculate_new_metric()
```

---

## 🧪 TESTING GUIDE

### Unit Tests

```python
# test_report_builder.py
import unittest
from analytics.report_builder import report_builder

class TestReportBuilder(unittest.TestCase):
    def test_build_report(self):
        report = report_builder.build_report(
            metrics=['total_leads'],
            filters={},
            date_range=(start, end)
        )
        self.assertIn('report_id', report)
        self.assertIn('kpis', report)
    
    def test_invalid_metrics(self):
        with self.assertRaises(ValueError):
            report_builder.build_report(
                metrics=['invalid_metric'],
                filters={},
                date_range=(start, end)
            )
```

### Integration Tests

```python
# test_analytics_api.py
import unittest
from app import app

class TestAnalyticsAPI(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
    
    def test_build_report_endpoint(self):
        response = self.client.post('/api/analytics/build-report', json={
            'metrics': ['total_leads'],
            'filters': {},
            'date_range': ['2026-01-01T00:00:00Z', '2026-01-31T23:59:59Z']
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('report_id', data)
```

### Frontend Tests

```javascript
// ExecutiveDashboard.test.js
import { render, screen } from '@testing-library/react';
import ExecutiveDashboard from './ExecutiveDashboard';

test('renders dashboard title', () => {
  render(<ExecutiveDashboard />);
  const titleElement = screen.getByText(/Executive Dashboard/i);
  expect(titleElement).toBeInTheDocument();
});

test('loads KPI cards', async () => {
  render(<ExecutiveDashboard />);
  // Wait for data to load
  const leadCard = await screen.findByText(/Total Leads/i);
  expect(leadCard).toBeInTheDocument();
});
```

---

## 📊 MONITORING & LOGGING

### Enable Logging

```python
# In each module
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)
```

### Monitor Scheduled Jobs

```python
# Check running jobs
from analytics.report_builder import report_builder

jobs = report_builder.scheduler.get_jobs()
for job in jobs:
    print(f"Job: {job.id}, Next run: {job.next_run_time}")
```

### Track Analytics Usage

```python
# Log analytics queries
@analytics_bp.before_request
def log_request():
    logger.info(f"Analytics request: {request.path} - {request.method}")
```

---

## 🚨 TROUBLESHOOTING

### Common Issues

**Issue**: Scheduler not running
```python
# Solution: Check if scheduler is started
from analytics.report_builder import report_builder
if not report_builder.scheduler.running:
    report_builder.scheduler.start()
```

**Issue**: PDF generation fails
```python
# Solution: Install reportlab fonts
pip install reportlab
# Verify installation
from reportlab.pdfgen import canvas
```

**Issue**: Excel export error
```python
# Solution: Check xlsxwriter version
pip install --upgrade xlsxwriter
```

**Issue**: Charts not rendering
```javascript
// Solution: Check recharts installation
npm install recharts --save
```

---

## 📚 REFERENCE

### API Endpoint Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/analytics/build-report` | POST | Generate custom report |
| `/api/analytics/export-report/<id>` | GET | Export report |
| `/api/analytics/cohorts` | POST | Create cohort |
| `/api/analytics/cohorts/compare` | POST | Compare cohorts |
| `/api/analytics/funnels/<id>/analyze` | POST | Analyze funnel |
| `/api/analytics/executive-dashboard` | GET | Get dashboard data |

### Metric Categories

**Volume**: total_leads, total_campaigns, emails_sent  
**Engagement**: opens, clicks, replies  
**Conversion**: meetings_booked, conversion_rate  
**Revenue**: revenue_generated, avg_deal_size, pipeline_value, roi  
**Efficiency**: cost_per_lead, cost_per_meeting  
**Rates**: open_rate, click_rate, reply_rate, meeting_rate

---

## ✅ DEPLOYMENT CHECKLIST

- [ ] Install backend dependencies
- [ ] Install frontend dependencies
- [ ] Create database indexes
- [ ] Configure scheduler
- [ ] Set up email delivery
- [ ] Update API routes
- [ ] Add frontend routes
- [ ] Configure CORS
- [ ] Set up logging
- [ ] Test all endpoints
- [ ] Deploy to production

---

**For additional support, refer to**:
- AGENT19_COMPLETION_REPORT.md (overview)
- AGENT19_QUICKREF.md (quick commands)
- AGENT19_EXECUTION_SUMMARY.md (technical details)
