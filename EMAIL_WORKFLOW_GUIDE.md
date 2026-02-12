# Email Campaign Workflow - Quick Start Guide

## ✅ Setup Complete!

Your email campaign system is fully configured and ready to use.

## 📋 What's Been Set Up

### Backend (Port 8000)
- ✅ Email Campaigns Router (`/email-campaigns/*`)
- ✅ Bulk email sending API with template rendering
- ✅ Digital signature injection from user profile
- ✅ Jinja2 template variables: `{{contact.name}}`, `{{sender.name}}`, etc.

### Frontend (Port 5173)
- ✅ AI Database page with lead selection
- ✅ "🔄 Create Workflow" button in selection bar
- ✅ Workflow Builder with template dropdown
- ✅ Email sending integration

### Database
- ✅ 2 Email Templates:
  - Introductory Mail-1 (Outreach)
  - Follow-up Mail (Follow-up)
- ✅ User Profile with Email Signature
- ✅ 6 Sample Leads in `leads_enriched` collection

## 🚀 How to Use

### Step 1: Select Leads
1. Navigate to AI Database page: http://localhost:5173/admin/sales/campaign/ai-leads
2. Use checkboxes to select leads you want to email
3. You'll see a purple "🔄 Create Workflow" button appear

### Step 2: Build Workflow
1. Click "🔄 Create Workflow"
2. You'll be redirected to Workflow Builder
3. The selected leads will be loaded (check "Recipients" count)

### Step 3: Choose Template
1. In the workflow step configuration, find the "Template" dropdown
2. Select either:
   - "Introductory Mail-1 - Outreach" (for first contact)
   - "Follow-up Mail - Follow-up" (for subsequent emails)

### Step 4: Send Emails
1. Review the workflow configuration
2. Click "Launch Workflow" button
3. Confirm the send action
4. Emails will be sent to all selected leads!

## 📧 Email Template Variables

Templates automatically populate with:
- `{{contact.name}}` - Full name
- `{{contact.first_name}}` - First name only
- `{{contact.email}}` - Email address
- `{{contact.title}}` - Job title
- `{{contact.company}}` - Company name
- `{{sender.name}}` - Your full name
- `{{sender.email}}` - Your email
- `{{sender.title}}` - Your job title
- `{{sender.company}}` - Your company name
- `{{sender.signature}}` - Your HTML email signature

## 🔧 Technical Details

### API Endpoints
- `GET /email-campaigns/templates` - List all templates
- `GET /email-campaigns/signature` - Get user signature
- `POST /email-campaigns/send-bulk` - Send emails to leads
  ```json
  {
    "lead_ids": ["id1", "id2"],
    "template_id": "template_id",
    "subject": "Optional custom subject"
  }
  ```
- `GET /email-campaigns/history` - View campaign history

### Database Collections
- `templates` - Email templates with Jinja2 variables
- `users` - User profiles with `email_signature` field
- `leads_enriched` - AI-enriched leads from database
- `email_campaigns` - Campaign history and statistics

## ⚙️ Configuration

### Current Settings
- **Email Mode**: Simulated (no actual emails sent)
- **SMTP**: Not configured (emails are logged to console)

### To Send Real Emails
Add to `backend/.env`:
```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
```

## 🎨 Customization

### Add New Templates
```python
from pymongo import MongoClient
client = MongoClient("mongodb://localhost:27017/")
db = client["email_automation"]

db.templates.insert_one({
    "name": "Your Template Name",
    "category": "Outreach|Follow-up|Meeting",
    "subject": "Your subject with {{variables}}",
    "body": "<p>HTML body with {{contact.first_name}}</p>"
})
```

### Update User Signature
1. Edit `setup_email_system.py`
2. Customize the HTML signature
3. Run: `python setup_email_system.py`

## 📊 Workflow Features

### Current Implementation
- ✅ Lead selection from AI Database
- ✅ Template selection dropdown
- ✅ Immediate email sending
- ✅ Success/failure tracking

### Future Enhancements (Not Yet Implemented)
- ⏳ Multi-step sequences with delays
- ⏳ Conditional branching based on opens/clicks
- ⏳ Email tracking (opens, clicks)
- ⏳ A/B testing templates
- ⏳ Scheduled sending

## 🐛 Troubleshooting

### No templates showing in dropdown
- Run: `python setup_email_system.py`

### Workflow shows "0 recipients"
- Make sure you selected leads in AI Database first
- Click "🔄 Create Workflow" button (not navigate directly)

### "No user found" error
- Run: `python create_admin_user.py`

### Backend not responding
- Check if backend is running on port 8000
- Run: `cd backend; python main.py`

## 📝 Files Modified/Created

### Backend
- `backend/routers/email_campaigns.py` (NEW)
- `backend/main.py` (MODIFIED - added router)

### Frontend
- `Campaign_platform/src/pages/sales/campaign/Workflow.jsx` (MODIFIED)
- `Campaign_platform/src/pages/sales/campaign/AILeads.jsx` (MODIFIED)

### Database Scripts
- `setup_email_system.py` - Setup templates and signature
- `create_admin_user.py` - Create user profile
- `verify_email_setup.py` - Verify configuration

## 🎉 Success!

Your email campaign workflow is ready. Select some leads and send your first campaign!
