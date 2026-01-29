# Gemini AI Mail Segregation System - Implementation Guide

## Overview

This system provides a comprehensive solution for email management using 7 Gemini AI agents to:
1. **Segregate emails** in the mail_pool by category, domain, priority, intent, or engagement
2. **Generate AI-powered summaries** of email segments
3. **Extract contact information** from email bodies
4. **Manage AI prompts** through a user-friendly interface in profile settings

---

## Architecture

### Backend Components

#### 1. Mail Segregation Agent (`backend/agents/mail_segregation_agent.py`)
- **Purpose**: Core AI agent using Gemini to intelligently categorize and process emails
- **Key Features**:
  - Multiple segregation strategies (category, sender_domain, priority, intent, engagement, custom)
  - Batch processing with configurable batch sizes
  - Default categories: Sales, Support, Business Development, Recruitment, Marketing, Administrative, Follow-up, Other
  - Contact extraction from email bodies
  - AI-powered summary generation

#### 2. Mail Operations Router (`backend/routers/mail_operations.py`)
- **Purpose**: REST API endpoints for mail operations
- **Endpoints**:
  - `POST /api/mail/segregate` - Segregate all emails with specified strategy
  - `GET /api/mail/segregation-stats` - Get segregation progress statistics
  - `POST /api/mail/extract-contacts` - Extract contacts from emails
  - `POST /api/mail/summary` - Generate email segment summary
  - `GET /api/mail/extracted-contacts` - List extracted contacts

#### 3. Prompt Management Router (`backend/routers/prompt_management.py`)
- **Purpose**: Manage AI agent prompts with version control
- **Endpoints**:
  - `POST /api/prompts/create` - Create new prompt
  - `GET /api/prompts` - List all prompts with filtering
  - `GET /api/prompts/{id}` - Get single prompt
  - `PUT /api/prompts/{id}` - Update prompt (creates new version)
  - `DELETE /api/prompts/{id}` - Soft delete prompt
  - `GET /api/prompts/{id}/versions` - List prompt versions
  - `POST /api/prompts/{id}/rollback/{version}` - Rollback to previous version
  - `POST /api/prompts/test` - Test prompt with sample input

### Frontend Components

#### 1. Profile Settings Page (`frontend/src/pages/ProfileSettings.jsx`)
- **Purpose**: User interface for managing profile and AI prompts
- **Features**:
  - Two-tab interface: Prompt Management and Profile Settings
  - Create, edit, and delete prompts
  - View version history and rollback
  - Test prompts with sample data
  - Active/inactive toggle for prompts
  - Agent type selection

#### 2. Mail Operations Page (`frontend/src/pages/MailOperations.jsx`)
- **Purpose**: Interface for mail segregation, summaries, and contact extraction
- **Features**:
  - Three-tab interface: Segregation, Summaries, Contacts
  - Real-time segregation statistics
  - Interactive segregation configuration
  - Mail summary generation with filters
  - Contact extraction and CSV export
  - Progress tracking with visual indicators

### Database Collections

#### MongoDB Collections Created:

1. **mail_pool.segregated_emails** - Segregated email data
2. **mail_pool.categories** - Email category definitions
3. **mail_pool.summaries** - Generated email summaries
4. **mail_pool.extracted_contacts** - Extracted contact information
5. **prompt_management.prompts** - AI agent prompts
6. **prompt_management.versions** - Prompt version history
7. **prompt_management.templates** - Prompt templates

---

## Installation & Setup

### 1. Environment Variables

Add to your `.env` file:

```bash
# Gemini API Key (required)
GEMINI_API_KEY=your_gemini_api_key_here

# MongoDB Connection
MONGO_URI=mongodb://localhost:27017/

# API Base URL
API_BASE=http://localhost:8000
```

### 2. Install Dependencies

```bash
# Backend dependencies
cd backend
pip install google-generativeai pymongo

# Frontend dependencies
cd frontend
npm install @mui/material @emotion/react @emotion/styled @mui/icons-material
```

### 3. Register Routes

The new routers are already integrated into `backend/main.py`:
- Mail Operations: `/api/mail/*`
- Prompt Management: `/api/prompts/*`

### 4. Add Frontend Routes

Add to your React router configuration:

```jsx
import ProfileSettings from './pages/ProfileSettings';
import MailOperations from './pages/MailOperations';

// In your routes
<Route path="/profile/settings" element={<ProfileSettings />} />
<Route path="/mail/operations" element={<MailOperations />} />
```

---

## Usage Guide

### Mail Segregation

#### Via API:

```bash
# Start segregation with category strategy
curl -X POST http://localhost:8000/api/mail/segregate \
  -H "Content-Type: application/json" \
  -H "Authorization: YOUR_SESSION_TOKEN" \
  -d '{
    "strategy": "category",
    "batch_size": 100,
    "force_rescan": false
  }'

# Get segregation statistics
curl -X GET http://localhost:8000/api/mail/segregation-stats \
  -H "Authorization: YOUR_SESSION_TOKEN"
```

#### Via UI:
1. Navigate to **Mail Operations** page
2. Go to **Segregation** tab
3. Click **Start Segregation**
4. Select strategy and configure options
5. Click **Start Segregation** to begin
6. Monitor progress in real-time

### Mail Summaries

#### Via API:

```bash
# Generate summary for a segment
curl -X POST http://localhost:8000/api/mail/summary \
  -H "Content-Type: application/json" \
  -H "Authorization: YOUR_SESSION_TOKEN" \
  -d '{
    "segment_name": "Sales",
    "date_from": "2026-01-01",
    "date_to": "2026-01-28"
  }'
```

#### Via UI:
1. Navigate to **Mail Operations** page
2. Go to **Summaries** tab
3. Click **Generate Summary**
4. (Optional) Filter by segment and date range
5. View generated summary with:
   - Key topics
   - Action items
   - Top senders
   - Sentiment distribution

### Contact Extraction

#### Via API:

```bash
# Extract contacts from all emails
curl -X POST http://localhost:8000/api/mail/extract-contacts \
  -H "Content-Type: application/json" \
  -H "Authorization: YOUR_SESSION_TOKEN" \
  -d '{
    "batch_size": 50
  }'

# Get extracted contacts
curl -X GET http://localhost:8000/api/mail/extracted-contacts?limit=50 \
  -H "Authorization: YOUR_SESSION_TOKEN"
```

#### Via UI:
1. Navigate to **Mail Operations** page
2. Go to **Contacts** tab
3. Click **Load Contacts**
4. View extracted contacts in table
5. Click **Download as CSV** to export

### Prompt Management

#### Via API:

```bash
# Create new prompt
curl -X POST http://localhost:8000/api/prompts/create \
  -H "Content-Type: application/json" \
  -H "Authorization: YOUR_SESSION_TOKEN" \
  -d '{
    "name": "Email Categorization v2",
    "description": "Improved categorization prompt",
    "content": "Analyze this email and categorize it...",
    "agent_type": "mail_segregation",
    "is_active": true,
    "tags": ["email", "categorization"]
  }'

# List prompts
curl -X GET http://localhost:8000/api/prompts?agent_type=mail_segregation \
  -H "Authorization: YOUR_SESSION_TOKEN"

# Update prompt (creates new version)
curl -X PUT http://localhost:8000/api/prompts/PROMPT_ID \
  -H "Content-Type: application/json" \
  -H "Authorization: YOUR_SESSION_TOKEN" \
  -d '{
    "content": "Updated prompt content..."
  }'

# Test prompt
curl -X POST http://localhost:8000/api/prompts/test \
  -H "Content-Type: application/json" \
  -H "Authorization: YOUR_SESSION_TOKEN" \
  -d '{
    "content": "Your prompt here",
    "test_input": "Test email subject and body",
    "agent_type": "mail_segregation"
  }'
```

#### Via UI:
1. Navigate to **Profile > Settings**
2. Go to **Prompt Management** tab
3. Click **New Prompt** to create
4. Fill in prompt details:
   - Name and description
   - Agent type
   - Prompt content
   - Active status
5. Click **Edit** icon to modify existing prompts
6. Click **History** icon to view versions
7. Use **Rollback** to revert to previous version

---

## Segregation Strategies

### 1. Category (Default)
Categorizes emails into business categories:
- Sales
- Support
- Business Development
- Recruitment
- Marketing
- Administrative
- Follow-up
- Other

### 2. Sender Domain
Groups emails by sender's company domain for account-based analysis.

### 3. Priority
Classifies emails by priority level (high, medium, low) based on:
- Urgency indicators
- Sender importance
- Content analysis

### 4. Intent
Determines business intent:
- Purchase/sales inquiry
- Support request
- Information seeking
- Partnership proposal
- Job application

### 5. Engagement
Analyzes engagement level:
- High engagement (active conversation)
- Medium engagement (occasional reply)
- Low engagement (no replies)

### 6. Custom
Uses custom Gemini prompts for specialized segmentation logic.

---

## Data Models

### ExtractedContact
```python
{
    "name": "John Doe",
    "email": "john@example.com",
    "phone": "+1-555-0123",
    "company": "Acme Corp",
    "title": "VP of Sales",
    "linkedin": "https://linkedin.com/in/johndoe",
    "website": "https://example.com",
    "address": "123 Main St, City, State",
    "social_handles": {
        "twitter": "@johndoe",
        "instagram": "@johndoe"
    },
    "source_email_id": "email_id_123",
    "extracted_at": "2026-01-28T10:30:00Z"
}
```

### MailSegmentSummary
```python
{
    "segment_id": "summary_123",
    "segment_name": "Sales",
    "total_emails": 150,
    "date_range": ["2026-01-01", "2026-01-28"],
    "key_topics": ["pricing", "demo requests", "partnerships"],
    "sentiment_distribution": {
        "positive": 60,
        "neutral": 80,
        "negative": 10
    },
    "top_senders": [
        ["john@example.com", 15],
        ["jane@company.com", 12]
    ],
    "action_items": [
        "Follow up on 5 pending demo requests",
        "Review pricing proposals"
    ],
    "summary_text": "Overall positive sales activity...",
    "created_at": "2026-01-28T10:30:00Z"
}
```

### Prompt
```python
{
    "id": "prompt_123",
    "name": "Email Categorization",
    "description": "Categorize emails into business types",
    "content": "Analyze this email and categorize...",
    "agent_type": "mail_segregation",
    "is_active": true,
    "tags": ["email", "categorization"],
    "parameters": {},
    "version": 2,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-28T10:30:00Z"
}
```

---

## Performance Considerations

### Batch Processing
- Default batch size: 100 emails
- Configurable per request
- Processes emails in parallel where possible
- Progress tracking via stats endpoint

### Caching
- Segregation stats cached for 10 seconds
- Reduces database load during heavy processing
- Auto-refresh on segregation completion

### Rate Limiting
- Gemini API rate limits apply
- Implement exponential backoff for failures
- Monitor API usage in Gemini console

---

## Monitoring & Troubleshooting

### Check Segregation Progress
```bash
curl -X GET http://localhost:8000/api/mail/segregation-stats \
  -H "Authorization: YOUR_SESSION_TOKEN"
```

Response:
```json
{
    "total_emails": 10000,
    "segregated_emails": 7500,
    "pending_emails": 2500,
    "segregation_percentage": 75,
    "segment_breakdown": [
        {"_id": "Sales", "count": 3000},
        {"_id": "Support", "count": 2500}
    ]
}
```

### Common Issues

#### 1. Gemini API Key Not Configured
**Error**: "Gemini API not configured"
**Solution**: Add `GEMINI_API_KEY` to `.env` file

#### 2. MongoDB Connection Failed
**Error**: "Failed to connect to MongoDB"
**Solution**: Check `MONGO_URI` in `.env` and ensure MongoDB is running

#### 3. Segregation Timeout
**Error**: Request timeout during segregation
**Solution**: Reduce batch_size to 50 or lower

#### 4. No Emails to Segregate
**Response**: `total_emails: 0`
**Solution**: Check mail_pool has emails in `torpedo_gmail.email_metadata`

---

## Future Enhancements

### Planned Features
1. **Multi-language support** - Detect and handle emails in multiple languages
2. **Custom categories** - Allow users to define their own categories
3. **Auto-scheduling** - Schedule automatic segregation runs
4. **Email threading** - Group related emails into conversations
5. **Sentiment trends** - Track sentiment changes over time
6. **Advanced filtering** - More granular email filtering options
7. **Export reports** - Export segregation reports to PDF/Excel
8. **Webhook integration** - Trigger actions on segregation completion

### Agent Scaling
Currently supports single Gemini instance. Future versions will support:
- Multiple Gemini agents working in parallel
- Load balancing across agents
- Agent specialization (e.g., sales-focused agent, support-focused agent)
- Agent performance monitoring and optimization

---

## API Reference

### Mail Operations

#### POST /api/mail/segregate
**Request Body:**
```json
{
    "strategy": "category",
    "batch_size": 100,
    "force_rescan": false
}
```

**Response:**
```json
{
    "success": true,
    "total_emails": 10000,
    "processed": 10000,
    "failed": 0,
    "strategy": "category",
    "segment_summaries": [...],
    "timestamp": "2026-01-28T10:30:00Z"
}
```

#### GET /api/mail/segregation-stats
**Response:**
```json
{
    "total_emails": 10000,
    "segregated_emails": 7500,
    "pending_emails": 2500,
    "segregation_percentage": 75.0,
    "segment_breakdown": [
        {"_id": "Sales", "count": 3000},
        {"_id": "Support", "count": 2500}
    ],
    "timestamp": "2026-01-28T10:30:00Z"
}
```

#### POST /api/mail/extract-contacts
**Request Body:**
```json
{
    "email_id": "email_123",  // Optional
    "segment_name": "Sales",  // Optional
    "batch_size": 50
}
```

**Response:**
```json
{
    "success": true,
    "total_processed": 50,
    "extracted": 45,
    "failed": 5,
    "timestamp": "2026-01-28T10:30:00Z"
}
```

#### POST /api/mail/summary
**Request Body:**
```json
{
    "segment_name": "Sales",
    "date_from": "2026-01-01",
    "date_to": "2026-01-28"
}
```

**Response:**
```json
{
    "success": true,
    "segment_id": "summary_123",
    "segment_name": "Sales",
    "total_emails": 150,
    "key_topics": ["pricing", "demo"],
    "sentiment_distribution": {"positive": 60, "neutral": 80, "negative": 10},
    "top_senders": [["john@example.com", 15]],
    "action_items": ["Follow up on demos"],
    "summary_text": "Overall positive activity...",
    "created_at": "2026-01-28T10:30:00Z"
}
```

#### GET /api/mail/extracted-contacts
**Query Parameters:**
- `limit` (default: 50)
- `skip` (default: 0)
- `company` (optional filter)

**Response:**
```json
{
    "success": true,
    "total": 100,
    "contacts": [
        {
            "id": "contact_123",
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "+1-555-0123",
            "company": "Acme Corp",
            "title": "VP Sales",
            "linkedin": "https://linkedin.com/in/johndoe",
            "website": "https://example.com",
            "address": "123 Main St",
            "social_handles": {},
            "extracted_at": "2026-01-28T10:30:00Z"
        }
    ]
}
```

### Prompt Management

#### POST /api/prompts/create
**Request Body:**
```json
{
    "name": "Email Categorization",
    "description": "Categorize business emails",
    "content": "Analyze this email and...",
    "agent_type": "mail_segregation",
    "is_active": true,
    "tags": ["email"],
    "parameters": {}
}
```

**Response:**
```json
{
    "success": true,
    "prompt": {
        "id": "prompt_123",
        "name": "Email Categorization",
        "version": 1,
        ...
    }
}
```

#### GET /api/prompts
**Query Parameters:**
- `agent_type` (optional)
- `active_only` (default: false)
- `tag` (optional)
- `limit` (default: 50)
- `skip` (default: 0)

**Response:**
```json
{
    "success": true,
    "total": 10,
    "prompts": [...]
}
```

#### PUT /api/prompts/{prompt_id}
**Request Body:**
```json
{
    "content": "Updated prompt content...",
    "is_active": true
}
```

**Response:**
```json
{
    "success": true,
    "prompt": {...},
    "version_created": true
}
```

#### GET /api/prompts/{prompt_id}/versions
**Response:**
```json
{
    "success": true,
    "versions": [
        {
            "version": 2,
            "content": "...",
            "parameters": {},
            "created_at": "2026-01-28T10:30:00Z",
            "created_by": "user_123",
            "notes": "Updated version"
        }
    ]
}
```

#### POST /api/prompts/{prompt_id}/rollback/{version}
**Response:**
```json
{
    "success": true,
    "message": "Rolled back to version 1",
    "prompt": {...},
    "new_version": 3
}
```

#### POST /api/prompts/test
**Request Body:**
```json
{
    "content": "Your prompt here",
    "test_input": "Test email content",
    "agent_type": "mail_segregation"
}
```

**Response:**
```json
{
    "success": true,
    "agent_type": "mail_segregation",
    "input": "Test email content",
    "output": "Gemini response...",
    "tested_at": "2026-01-28T10:30:00Z"
}
```

---

## Security Considerations

### API Authentication
- All endpoints require `Authorization` header with session token
- Session tokens stored in `localStorage`
- Implement token expiration and refresh

### Data Privacy
- Contact information encrypted at rest (recommended)
- PII data handling compliance (GDPR, CCPA)
- Audit logging for data access

### Prompt Security
- Validate prompt content for injection attacks
- Sanitize user input in prompts
- Rate limit prompt testing endpoint

---

## Support & Contact

For issues, questions, or feature requests:
1. Check this documentation
2. Review error logs in backend console
3. Monitor Gemini API usage in Google Cloud Console
4. Check MongoDB connection and collections

---

## Changelog

### Version 1.0.0 (2026-01-28)
- Initial release
- 7 Gemini AI agents for mail segregation
- Mail summary generation
- Contact extraction from email bodies
- Prompt management with version control
- Profile settings UI
- Mail operations UI
- Complete API documentation

---

## License

This implementation is part of the Campaign Platform project.
