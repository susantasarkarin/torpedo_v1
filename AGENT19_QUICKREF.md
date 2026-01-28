# AGENT 19 - QUICK REFERENCE
## Advanced Analytics & Reporting - Command Cheat Sheet

---

## 🚀 QUICK START

### Backend Setup
```bash
pip install pandas reportlab xlsxwriter apscheduler python-dateutil
mkdir -p backend/analytics
# Copy analytics modules
```

### Frontend Setup
```bash
npm install @mui/material @mui/icons-material @mui/x-date-pickers recharts
mkdir -p frontend/src/pages/sales frontend/src/pages/analytics
# Copy React components
```

---

## 📊 REPORT BUILDER

### Build Report
```python
from analytics.report_builder import report_builder

report = report_builder.build_report(
    metrics=['open_rate', 'reply_rate', 'meetings_booked'],
    filters={'industry': 'Technology'},
    date_range=(start_date, end_date),
    group_by='week'
)
```

### Schedule Report
```python
job_id = report_builder.schedule_report(
    report_config={'metrics': [...], 'filters': {}},
    frequency='weekly',  # daily, weekly, monthly, quarterly
    recipients=['exec@company.com'],
    format='pdf'  # pdf, csv, excel
)
```

### Export Report
```python
pdf_bytes = report_builder.export_report('report_id', 'pdf')
excel_bytes = report_builder.export_report('report_id', 'excel')
csv_bytes = report_builder.export_report('report_id', 'csv')
```

### List Reports
```python
reports = report_builder.get_scheduled_reports(user_id='optional')
```

### Cancel Schedule
```python
success = report_builder.cancel_scheduled_report('job_id')
```

---

## 👥 COHORT ANALYSIS

### Create Cohort
```python
from analytics.cohort_analysis import cohort_analyzer

cohort_id = cohort_analyzer.create_cohort(
    cohort_name="Q1 2026 Imports",
    criteria={'created_at': {'$gte': start, '$lt': end}},
    cohort_type='import_date'  # import_date, lead_source, industry, etc.
)
```

### Compare Cohorts
```python
comparison = cohort_analyzer.compare_cohorts([
    'cohort_id_1',
    'cohort_id_2',
    'cohort_id_3'
])
# Returns: cohorts, metrics, insights
```

### Get Retention
```python
retention = cohort_analyzer.get_cohort_retention(
    cohort_id='cohort_123',
    period='week',  # day, week, month
    num_periods=12
)
```

### Get Performance
```python
performance = cohort_analyzer.get_cohort_performance('cohort_id')
# Returns: metrics, performance_grade (A-F)
```

### List Cohorts
```python
cohorts = cohort_analyzer.list_cohorts(cohort_type='import_date')
```

### Auto-Create
```python
cohort_ids = cohort_analyzer.auto_create_cohorts('import_date')
# Creates cohorts for each month
```

---

## 🔄 FUNNEL ANALYSIS

### Define Funnel
```python
from analytics.funnel import funnel_analyzer

funnel_id = funnel_analyzer.define_funnel(
    funnel_name="Email Outreach",
    stages=['Sent', 'Opened', 'Clicked', 'Replied', 'Meeting'],
    funnel_type='email_outreach'
)
```

### Analyze Funnel
```python
analysis = funnel_analyzer.analyze_funnel(
    funnel_id='funnel_123',
    date_range=(start_date, end_date),
    filters={'industry': 'Tech'}
)
# Returns: stages, conversion_rates, bottlenecks, recommendations
```

### Get Drop-offs
```python
drop_offs = funnel_analyzer.get_drop_off_points(
    funnel_id='funnel_123',
    threshold=30.0  # % threshold
)
# Returns: stages with high drop-off, suggestions
```

### Compare Funnels
```python
comparison = funnel_analyzer.compare_funnels(
    funnel_ids=['funnel_1', 'funnel_2'],
    date_range=(start, end)
)
```

### Get Trends
```python
trends = funnel_analyzer.get_funnel_trends(
    funnel_id='funnel_123',
    num_periods=12,
    period='week'
)
```

### Create Defaults
```python
funnel_ids = funnel_analyzer.create_default_funnels()
# Creates: email_outreach, lead_lifecycle, campaign
```

---

## 📄 EXPORT MODULE

### Export PDF
```python
from analytics.export import export_pdf

pdf_bytes = export_pdf(report_data)
with open('report.pdf', 'wb') as f:
    f.write(pdf_bytes)
```

### Export Excel
```python
from analytics.export import export_excel

excel_bytes = export_excel(report_data)
with open('report.xlsx', 'wb') as f:
    f.write(excel_bytes)
```

---

## 🌐 API ENDPOINTS

### Report Builder

```bash
# Build report
POST /api/analytics/build-report
Body: {
  "metrics": ["open_rate", "reply_rate"],
  "filters": {"industry": "Tech"},
  "date_range": ["2026-01-01T00:00:00Z", "2026-01-31T23:59:59Z"],
  "group_by": "week"
}

# Schedule report
POST /api/analytics/schedule-report
Body: {
  "report_config": {...},
  "frequency": "weekly",
  "recipients": ["user@example.com"],
  "format": "pdf"
}

# Export report
GET /api/analytics/export-report/:id?format=pdf

# List reports
GET /api/analytics/reports

# List scheduled
GET /api/analytics/scheduled-reports

# Cancel schedule
DELETE /api/analytics/scheduled-reports/:job_id
```

### Cohort Analysis

```bash
# Create cohort
POST /api/analytics/cohorts
Body: {
  "name": "Q1 2026",
  "criteria": {"created_at": {"$gte": "..."}},
  "type": "import_date"
}

# List cohorts
GET /api/analytics/cohorts?type=import_date

# Get performance
GET /api/analytics/cohorts/:id

# Compare cohorts
POST /api/analytics/cohorts/compare
Body: {"cohort_ids": ["id1", "id2"]}

# Get retention
GET /api/analytics/cohorts/:id/retention?period=week&num_periods=12

# Auto-create
POST /api/analytics/cohorts/auto-create
Body: {"type": "import_date"}

# Delete cohort
DELETE /api/analytics/cohorts/:id
```

### Funnel Analysis

```bash
# Create funnel
POST /api/analytics/funnels
Body: {
  "name": "Sales Pipeline",
  "stages": ["Lead", "Contact", "Demo", "Closed"],
  "type": "custom"
}

# List funnels
GET /api/analytics/funnels?type=custom

# Analyze funnel
POST /api/analytics/funnels/:id/analyze
Body: {
  "date_range": ["2026-01-01T00:00:00Z", "2026-01-31T23:59:59Z"],
  "filters": {"industry": "Tech"}
}

# Get drop-offs
GET /api/analytics/funnels/:id/drop-offs?threshold=30

# Compare funnels
POST /api/analytics/funnels/compare
Body: {
  "funnel_ids": ["id1", "id2"],
  "date_range": ["...", "..."]
}

# Get trends
GET /api/analytics/funnels/:id/trends?num_periods=12&period=week

# Create defaults
POST /api/analytics/funnels/create-defaults

# Delete funnel
DELETE /api/analytics/funnels/:id
```

### Executive Dashboard

```bash
# Get dashboard
GET /api/analytics/executive-dashboard?days=30

# Export dashboard
GET /api/analytics/export-dashboard?format=pdf&days=30
```

---

## ⚛️ FRONTEND USAGE

### Executive Dashboard

```javascript
import ExecutiveDashboard from './pages/sales/ExecutiveDashboard';

// In router
<Route path="/dashboard/executive" element={<ExecutiveDashboard />} />

// Load data
const loadDashboardData = async () => {
  const response = await axios.get('/api/analytics/executive-dashboard', {
    params: { days: 30 }
  });
  setDashboardData(response.data);
};
```

### Reports Page

```javascript
import Reports from './pages/analytics/Reports';

// In router
<Route path="/analytics/reports" element={<Reports />} />

// Build report
const handleBuildReport = async () => {
  const response = await axios.post('/api/analytics/build-report', {
    metrics: selectedMetrics,
    filters: selectedFilters,
    date_range: [start, end],
    group_by: 'week'
  });
};
```

---

## 📊 AVAILABLE METRICS (19)

**Volume**: total_leads, total_campaigns, emails_sent  
**Engagement**: opens, clicks, replies  
**Conversion**: meetings_booked  
**Rates**: open_rate, click_rate, reply_rate, meeting_rate, bounce_rate, unsubscribe_rate, conversion_rate  
**Revenue**: revenue_generated, avg_deal_size, pipeline_value, roi  
**Efficiency**: cost_per_lead, cost_per_meeting

---

## 🎯 FILTERS (10)

campaign_type, industry, seniority, lead_source, campaign_id, team_member, lead_status, email_status, company_size, location

---

## 🔄 COHORT TYPES (7)

import_date, lead_source, campaign_type, industry, seniority, company_size, location, custom

---

## 📈 FUNNEL TYPES (3 + custom)

**email_outreach**: Email Sent → Opened → Clicked → Reply → Meeting → Closed  
**lead_lifecycle**: Lead Created → Contact → Engaged → Qualified → Proposal → Negotiation → Won  
**campaign**: Launched → Contacted → Responses → Opportunities → Revenue

---

## 🕒 SCHEDULE FREQUENCIES

- **daily**: Every day at 8:00 AM
- **weekly**: Every Monday at 8:00 AM
- **monthly**: 1st of month at 8:00 AM
- **quarterly**: Jan/Apr/Jul/Oct 1st at 8:00 AM

---

## 📤 EXPORT FORMATS

- **pdf**: Professional report with charts
- **excel**: Multi-sheet workbook with formatting
- **csv**: Raw data for analysis

---

## 🎨 DASHBOARD FEATURES

- 8 real-time KPI cards
- Time range selector (7/30/90/365 days)
- Multi-line trend chart
- Pie chart for distribution
- Campaign leaderboard table
- Goal progress bars
- PDF/Excel export

---

## 🔧 CONFIGURATION

### Scheduler
```python
# In report_builder.py
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.start()
```

### Database Indexes
```javascript
db.reports.createIndex({ "report_id": 1 }, { unique: true });
db.cohorts.createIndex({ "cohort_id": 1 }, { unique: true });
db.funnels.createIndex({ "funnel_id": 1 }, { unique: true });
```

---

## 🧪 TESTING

### Unit Test
```python
import unittest
from analytics.report_builder import report_builder

class TestReportBuilder(unittest.TestCase):
    def test_build_report(self):
        report = report_builder.build_report([...])
        self.assertIn('report_id', report)
```

### API Test
```bash
# Test build report
curl -X POST http://localhost:5000/api/analytics/build-report \
  -H "Content-Type: application/json" \
  -d '{"metrics": ["total_leads"], "filters": {}, "date_range": [...]}'
```

---

## 🐛 TROUBLESHOOTING

### Scheduler not running
```python
from analytics.report_builder import report_builder
if not report_builder.scheduler.running:
    report_builder.scheduler.start()
```

### PDF generation fails
```bash
pip install --upgrade reportlab
```

### Excel export error
```bash
pip install --upgrade xlsxwriter
```

### Frontend chart issues
```bash
npm install recharts --save
```

---

## 📚 FILE LOCATIONS

**Backend**:
- `backend/analytics/report_builder.py` (625 lines)
- `backend/analytics/cohort_analysis.py` (582 lines)
- `backend/analytics/funnel.py` (634 lines)
- `backend/analytics/export.py` (441 lines)
- `backend/routes/analytics_routes.py` (489 lines)

**Frontend**:
- `frontend/src/pages/sales/ExecutiveDashboard.jsx` (476 lines)
- `frontend/src/pages/analytics/Reports.jsx` (524 lines)

**Docs**:
- `AGENT19_COMPLETION_REPORT.md`
- `AGENT19_DELIVERABLES.md`
- `AGENT19_QUICKREF.md` (this file)
- `AGENT19_EXECUTION_SUMMARY.md`

---

## ⚡ ONE-LINERS

```python
# Quick report
report_builder.build_report(['open_rate'], {}, (start, end))

# Quick cohort
cohort_analyzer.create_cohort("Test", {}, 'custom')

# Quick funnel
funnel_analyzer.define_funnel("Test", ['A', 'B', 'C'], None, 'custom')

# Quick export
export_pdf({'title': 'Test', 'kpis': {}})
```

---

## 🎯 COMMON WORKFLOWS

### 1. Generate Monthly Report
```python
report = report_builder.build_report(
    metrics=['open_rate', 'reply_rate', 'revenue_generated'],
    filters={},
    date_range=(first_of_month, last_of_month),
    group_by='week'
)
pdf = report_builder.export_report(report['report_id'], 'pdf')
```

### 2. Compare Lead Sources
```python
cohort_analyzer.auto_create_cohorts('lead_source')
cohorts = cohort_analyzer.list_cohorts(cohort_type='lead_source')
comparison = cohort_analyzer.compare_cohorts([c['cohort_id'] for c in cohorts])
```

### 3. Analyze Campaign Funnel
```python
funnel_id = funnel_analyzer.define_funnel(
    "Campaign Flow",
    ['Sent', 'Opened', 'Replied', 'Meeting', 'Closed'],
    None,
    'campaign'
)
analysis = funnel_analyzer.analyze_funnel(funnel_id)
drop_offs = funnel_analyzer.get_drop_off_points(funnel_id, 25.0)
```

---

**Quick access to full documentation**:
- Overview: AGENT19_COMPLETION_REPORT.md
- Detailed Guide: AGENT19_DELIVERABLES.md
- Technical Details: AGENT19_EXECUTION_SUMMARY.md
