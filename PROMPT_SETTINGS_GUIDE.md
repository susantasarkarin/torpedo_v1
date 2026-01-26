# AI Prompts Quick Reference & Settings Guide

## 🎯 Quick Access to Prompts in Settings

### Via API

#### 1. View All Prompts
```bash
curl -H "Authorization: YOUR_SESSION_TOKEN" \
  http://localhost:9944/settings/ai-prompts
```

**Response**:
```json
{
  "success": true,
  "prompts": [
    {
      "_id": "...",
      "prompt_key": "gemini_classify_lead",
      "name": "Gemini Lead Classification",
      "description": "...",
      "model": "gemini-2.0-flash",
      "temperature": 0.3,
      "max_output_tokens": 500,
      "is_active": true,
      "system_prompt": "...",
      "user_prompt_template": "...",
      "current_version": 1,
      "versions": [
        {
          "version": 1,
          "system_prompt": "...",
          "user_prompt_template": "...",
          "created_at": "2026-01-26T10:30:00",
          "created_by": "system"
        }
      ],
      "created_at": "2026-01-26T10:30:00",
      "updated_at": "2026-01-26T10:30:00"
    }
  ],
  "total": 8
}
```

---

#### 2. Get Specific Prompt
```bash
curl -H "Authorization: YOUR_SESSION_TOKEN" \
  http://localhost:9944/settings/ai-prompts/gemini_classify_lead
```

**Response**: Single prompt object with full version history

---

#### 3. Edit a Prompt
```bash
curl -X PUT \
  -H "Authorization: YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "system_prompt": "Your new system prompt here...",
    "user_prompt_template": "Your new user template with {variables}...",
    "temperature": 0.4,
    "max_output_tokens": 600,
    "is_active": true
  }' \
  http://localhost:9944/settings/ai-prompts/gemini_classify_lead
```

**Response**:
```json
{
  "success": true,
  "message": "Prompt updated to version 2",
  "version": 2
}
```

---

#### 4. Test a Prompt (Before Saving)
```bash
curl -X POST \
  -H "Authorization: YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "system_prompt": "Your new system prompt...",
    "user_prompt_template": "Your new template...",
    "sample_lead": {
      "email": "john@techcorp.com",
      "full_name": "John Smith",
      "title": "VP Sales",
      "company": "TechCorp",
      "email_subject": "Interested in your platform",
      "email_body": "We would like to discuss your solution..."
    }
  }' \
  http://localhost:9944/settings/ai-prompts/gemini_classify_lead/test
```

**Response**:
```json
{
  "success": true,
  "sample_lead": {...},
  "formatted_user_prompt": "...",
  "ai_response": "...",
  "tokens_used": 142,
  "model": "gemini-2.0-flash"
}
```

---

#### 5. Rollback to Previous Version
```bash
curl -X POST \
  -H "Authorization: YOUR_SESSION_TOKEN" \
  http://localhost:9944/settings/ai-prompts/gemini_classify_lead/rollback/1
```

**Response**:
```json
{
  "success": true,
  "message": "Rolled back to version 1 (now version 3)",
  "new_version": 3
}
```

---

#### 6. View All Prompts Documentation
```bash
curl -H "Authorization: YOUR_SESSION_TOKEN" \
  http://localhost:9944/settings/ai-prompts-documentation
```

**Response**: Complete documentation with integration points and workflows

---

#### 7. View Prompt Usage Statistics
```bash
curl -H "Authorization: YOUR_SESSION_TOKEN" \
  "http://localhost:9944/settings/ai-prompts-usage?days=7"
```

**Response**:
```json
{
  "success": true,
  "period_days": 7,
  "gemini_usage": {
    "by_task_type": [
      {
        "task_type": "classify",
        "requests": 1250,
        "tokens_used": 187500,
        "success_rate": 98.5,
        "failures": 19
      },
      {
        "task_type": "enrich",
        "requests": 450,
        "tokens_used": 112500,
        "success_rate": 97.1,
        "failures": 13
      }
    ],
    "total_requests": 3500,
    "total_tokens": 875000,
    "cost": "$0 (FREE tier)"
  },
  "openai_usage": {
    "by_model_source": [
      {
        "model": "gpt-4o-mini",
        "source": "web_search",
        "requests": 187,
        "input_tokens": 28050,
        "output_tokens": 7850,
        "cost_usd": 12.34
      }
    ],
    "total_requests": 187,
    "total_cost_usd": 12.34
  }
}
```

---

## 📋 All Available Prompts (Prompt Keys)

### Gemini Prompts (FREE)
1. **gemini_classify_lead** - Lead categorization (CLIENT/VENDOR/RECRUITER/INTERNAL/SPAM)
2. **gemini_enrich_lead** - Infer business intelligence (skills, pain points, engagement)
3. **gemini_extract_contacts** - Extract structured contact info from emails
4. **gemini_summarize_email** - Email summarization with sentiment analysis
5. **gemini_segment_email** - Quick email categorization (fastest)

### OpenAI Prompts (PAID)
1. **lead_classification** - Original lead enrichment (being phased out)
2. **openai_web_search** - Generate web search queries with web_search_preview tool

### Perplexity Prompts (OPTIONAL)
1. **perplexity_company_discovery** - Discover target companies matching criteria

---

## 🔧 Common Prompt Modifications

### Modify Classification Categories
**Prompt**: `gemini_classify_lead`

Find this section:
```
"category": "CLIENT|VENDOR|RECRUITER|INTERNAL|SPAM"
```

Change to add your own categories:
```
"category": "PROSPECT|PARTNER|HIRING|TEAM|JUNK|QUALIFIED"
```

**Then update the rules section accordingly**

---

### Add Custom Scoring
**Prompt**: `gemini_classify_lead`

Add to output schema:
```json
{
  "category": "...",
  "confidence": 0.0-1.0,
  "custom_score": 0-100,  // Add this
  "department": "...",
  ...
}
```

**Example in system prompt**:
```
custom_score: 0-100 rating of lead quality (0=low, 100=perfect fit)
```

---

### Adjust Temperature for More Consistency
**Prompt**: Any Gemini prompt

Current: `"temperature": 0.3` (deterministic)  
For MORE variation: `"temperature": 0.7`  
For LESS variation: `"temperature": 0.1`

```bash
curl -X PUT \
  -H "Authorization: YOUR_SESSION_TOKEN" \
  -d '{"temperature": 0.1}' \
  http://localhost:9944/settings/ai-prompts/gemini_classify_lead
```

---

### Add New Custom Prompt
You can create entirely new prompts in the database:

```bash
curl -X POST \
  -H "Authorization: YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt_key": "my_custom_prompt",
    "name": "My Custom Prompt",
    "description": "What this prompt does...",
    "model": "gemini-2.0-flash",
    "temperature": 0.5,
    "max_output_tokens": 500,
    "system_prompt": "Your system instructions...",
    "user_prompt_template": "Your template with {variables}...",
    "is_active": true
  }' \
  http://localhost:9944/settings/ai-prompts
```

---

## 📊 Prompt Performance Metrics

### Expected Performance

| Prompt | Model | Avg Time | Cost | Success Rate |
|--------|-------|----------|------|--------------|
| gemini_segment_email | Gemini | 2s | $0 | 99%+ |
| gemini_extract_contacts | Gemini | 2s | $0 | 98%+ |
| gemini_summarize_email | Gemini | 2s | $0 | 97%+ |
| gemini_classify_lead | Gemini | 2-3s | $0 | 95%+ |
| gemini_enrich_lead | Gemini | 2-3s | $0 | 94%+ |
| openai_web_search | OpenAI | 3-5s | $0.001-0.003 | 98%+ |

**Total email processing time**: ~6-8 seconds | **Cost**: $0

---

## 🎯 When to Modify Prompts

### ❌ DO NOT MODIFY
- **gemini_segment_email** - Working perfectly, used for quick processing
- **gemini_extract_contacts** - Accurate contact extraction
- **openai_web_search** - Critical for web search functionality

### ✅ SAFE TO MODIFY
- **gemini_classify_lead** - Can adjust categories or confidence logic
- **gemini_enrich_lead** - Can add new enrichment fields
- **gemini_summarize_email** - Can adjust summary detail level

### ⚠️ MODIFY WITH CAUTION
- **lead_classification** - Legacy prompt, verify Gemini alternative first
- **perplexity_company_discovery** - High cost, test thoroughly

---

## 🔍 Debugging Prompt Issues

### Issue: Low Success Rate
1. Check `/settings/ai-prompts-usage` endpoint
2. Review error messages in `gemini_requests` collection
3. Reduce max_output_tokens if hitting token limits
4. Test prompt with sample data first

### Issue: Inconsistent Results
1. Lower temperature (0.1-0.3) for deterministic output
2. Add more specific rules to system prompt
3. Test with multiple sample leads

### Issue: Expensive Tokens Usage
1. Reduce max_output_tokens
2. Simplify user_prompt_template (less context)
3. Use gemini prompts instead of OpenAI

### Issue: Slow Response Time
1. Use gemini_segment_email instead of gemini_classify_lead
2. Reduce model complexity if possible
3. Check server load

---

## 🚀 Best Practices

### 1. Always Test Before Deploying
```bash
POST /settings/ai-prompts/{prompt_key}/test
```

### 2. Keep Version History
- Each update creates a new version automatically
- Can rollback anytime with version number

### 3. Monitor Costs
```bash
GET /settings/ai-prompts-usage?days=7
```

### 4. Document Changes
Add a comment when you update prompts explaining the change

### 5. Use Staging
Test new prompts on a small batch before full deployment

---

## 📞 Support

For issues with prompts:
1. Check [AI_PROMPTS_DOCUMENTATION.md](./AI_PROMPTS_DOCUMENTATION.md) for complete reference
2. View `/settings/ai-prompts-documentation` endpoint
3. Test prompt with `/settings/ai-prompts/{key}/test` endpoint
4. Review usage stats with `/settings/ai-prompts-usage` endpoint

---

**Created**: January 26, 2026  
**Status**: ✅ All 8 prompts active and optimized
