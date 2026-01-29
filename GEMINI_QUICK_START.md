# Gemini Mail Segregation - Quick Start Guide

## 🚀 Quick Setup (5 minutes)

### Step 1: Configure Gemini API Key

Add to your `.env` file:
```bash
GEMINI_API_KEY=your_gemini_api_key_here
```

Get your API key from: https://makersuite.google.com/app/apikey

### Step 2: Install Dependencies

```bash
# Install Python package
pip install google-generativeai

# Frontend already has required packages
```

### Step 3: Start the Server

```bash
# From backend directory
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Step 4: Access the UI

1. **Profile Settings**: `http://localhost:3000/profile/settings`
   - Manage AI prompts
   - View prompt versions
   - Test prompts

2. **Mail Operations**: `http://localhost:3000/mail/operations`
   - Segregate emails
   - Generate summaries
   - Extract contacts

---

## 📧 First Mail Segregation

### Option 1: Via UI (Recommended)

1. Navigate to **Mail Operations**
2. Click **Start Segregation**
3. Choose strategy: **Category** (default)
4. Set batch size: **100**
5. Click **Start Segregation**
6. Monitor progress in real-time

### Option 2: Via API

```bash
curl -X POST http://localhost:8000/api/mail/segregate \
  -H "Content-Type: application/json" \
  -H "Authorization: YOUR_SESSION_TOKEN" \
  -d '{
    "strategy": "category",
    "batch_size": 100,
    "force_rescan": false
  }'
```

---

## 📊 Check Results

### Segregation Stats
```bash
curl -X GET http://localhost:8000/api/mail/segregation-stats \
  -H "Authorization: YOUR_SESSION_TOKEN"
```

### View in UI
- Go to **Mail Operations** > **Segregation** tab
- See total emails, segregated count, pending count
- View segment breakdown table

---

## 💡 Key Features

### 1. Mail Segregation Strategies
- **Category**: Sales, Support, BD, Marketing, etc.
- **Sender Domain**: Group by company
- **Priority**: High/Medium/Low
- **Intent**: Purchase, Support, Info, etc.
- **Engagement**: High/Medium/Low activity
- **Custom**: Your own logic

### 2. AI-Powered Summaries
Generate intelligent summaries with:
- Key topics and themes
- Sentiment analysis
- Top senders
- Action items
- Professional summary text

### 3. Contact Extraction
Extract from emails:
- Name and email
- Phone number
- Company and title
- LinkedIn profile
- Website and social media
- Physical address

### 4. Prompt Management
- Create custom prompts
- Version control (auto-versioning)
- Test prompts before deployment
- Rollback to previous versions
- Organize with tags

---

## 🎯 Common Use Cases

### Use Case 1: Daily Email Triage
```bash
# Morning: Segregate overnight emails
curl -X POST http://localhost:8000/api/mail/segregate \
  -d '{"strategy": "priority"}'

# Get high-priority emails
curl -X POST http://localhost:8000/api/mail/summary \
  -d '{"segment_name": "High Priority"}'
```

### Use Case 2: Sales Lead Extraction
```bash
# Segregate by category
curl -X POST http://localhost:8000/api/mail/segregate \
  -d '{"strategy": "category"}'

# Extract contacts from Sales emails
curl -X POST http://localhost:8000/api/mail/extract-contacts \
  -d '{"segment_name": "Sales"}'

# Download as CSV via UI
```

### Use Case 3: Weekly Summary Report
```bash
# Generate summary for past week
curl -X POST http://localhost:8000/api/mail/summary \
  -d '{
    "date_from": "2026-01-21",
    "date_to": "2026-01-28"
  }'
```

---

## 🛠️ Troubleshooting

### Issue: "Gemini API not configured"
**Solution**: Add `GEMINI_API_KEY` to `.env` file

### Issue: No emails to segregate
**Solution**: 
1. Check `torpedo_gmail.email_metadata` collection has emails
2. Verify MongoDB connection in `.env`

### Issue: Segregation is slow
**Solution**: Reduce `batch_size` to 50

### Issue: Contact extraction returns empty
**Solution**: 
1. Check email bodies have contact info
2. Verify Gemini API key is valid

---

## 📈 Performance Tips

### 1. Optimize Batch Size
- **Small mail pool (<1000)**: batch_size = 50
- **Medium (1000-10000)**: batch_size = 100
- **Large (>10000)**: batch_size = 200

### 2. Use Appropriate Strategy
- **First run**: Use "category" for general segregation
- **Follow-up**: Use "priority" or "intent" for focused work
- **Analysis**: Use "engagement" to find active conversations

### 3. Schedule Segregation
- Run during off-peak hours
- Use smaller batches during business hours
- Consider nightly full rescan

---

## 🔐 Security Checklist

- [ ] Gemini API key in `.env` (not committed)
- [ ] Session tokens with expiration
- [ ] MongoDB with authentication
- [ ] HTTPS in production
- [ ] Rate limiting enabled
- [ ] Audit logging configured

---

## 📚 Next Steps

1. **Customize Prompts**: Go to Profile > Settings > Prompt Management
2. **Create Custom Categories**: Edit mail_segregation_agent.py
3. **Schedule Auto-Segregation**: Use cron or APScheduler
4. **Export Reports**: Use extracted data for analysis
5. **Integrate Webhooks**: Trigger actions on segregation complete

---

## 🎓 Learning Resources

### Gemini Documentation
- API Reference: https://ai.google.dev/docs
- Best Practices: https://ai.google.dev/docs/gemini_api_overview
- Prompt Engineering: https://ai.google.dev/docs/prompt_best_practices

### MongoDB Best Practices
- Indexing: Create indexes on frequently queried fields
- Aggregation: Use aggregation pipeline for complex queries
- Backup: Regular backups of segregated data

---

## 📞 Quick Commands Reference

```bash
# Segregate with category
POST /api/mail/segregate {"strategy": "category"}

# Get stats
GET /api/mail/segregation-stats

# Generate summary
POST /api/mail/summary {"segment_name": "Sales"}

# Extract contacts
POST /api/mail/extract-contacts {}

# List contacts
GET /api/mail/extracted-contacts?limit=100

# Create prompt
POST /api/prompts/create {"name": "My Prompt", "content": "..."}

# List prompts
GET /api/prompts?agent_type=mail_segregation

# Test prompt
POST /api/prompts/test {"content": "...", "test_input": "..."}
```

---

## ✅ Verification Checklist

After setup, verify:

- [ ] Can access Profile Settings page
- [ ] Can access Mail Operations page
- [ ] Can create a new prompt
- [ ] Can start mail segregation
- [ ] Can view segregation stats
- [ ] Can generate mail summary
- [ ] Can extract and view contacts
- [ ] API endpoints respond with 200 status

---

## 🎉 Success Indicators

You're ready when you see:

1. ✅ Mail Operations router included (backend console)
2. ✅ Prompt Management router included (backend console)
3. ✅ Segregation stats showing progress
4. ✅ Emails moving to segregated collections
5. ✅ Summaries generating successfully
6. ✅ Contacts being extracted

---

## 💬 Need Help?

1. Check full documentation: `GEMINI_MAIL_SEGREGATION_GUIDE.md`
2. Review API errors in browser console (F12)
3. Check backend logs for detailed errors
4. Verify .env configuration
5. Test Gemini API key separately

---

**Happy Segregating! 🚀**
