# Backend Integration Guide

This folder contains reference documentation for integrating with the Torpedo CRM backend.

**Note:** The CRM backend already has all required routers and scripts:
- `backend/routers/marketing.py` - CMS management
- `backend/routers/public_website.py` - Public API for websites  
- `backend/routers/seo_monitoring.py` - SEO analysis
- `backend/scripts/seed_surveyfieldwork.py` - Content seeding

## Quick Start

### 1. Run the Seed Script

Seed the database with Survey Fieldwork content:

```bash
cd "D:\Code\03. Projects\01. torpedo wip\02. 20 dec\campaign_platform-main\campaign_platform-main"
python -m backend.scripts.seed_surveyfieldwork
```

This will populate MongoDB `marketing_db` with:
- Website configuration
- Navigation (header & footer)
- Home page with all sections
- 3 blog posts
- Initial SEO tracking records

### 2. Start the Backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 3. Configure the Website

Set the API URL in `.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_DOMAIN=surveyfieldwork.com
```

## API Endpoints

### Public Website API (read-only, no auth)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/website/config` | GET | Website settings, scripts, navigation |
| `/api/website/page/{slug}` | GET | Page content by slug |
| `/api/website/blog` | GET | List published blog posts |
| `/api/website/blog/{slug}` | GET | Single blog post |
| `/api/website/sitemap` | GET | Sitemap data for SEO |

### Marketing CMS API (requires auth)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/marketing/websites/` | GET/POST | Website CRUD |
| `/marketing/websites/{id}` | GET/PUT/DELETE | Single website |
| `/marketing/websites/{id}/pages/` | GET/POST | Page CRUD |
| `/marketing/websites/{id}/blog/` | GET/POST | Blog post CRUD |
| `/marketing/websites/{id}/navigation/` | GET/PUT | Navigation |
| `/marketing/media/` | GET/POST | Media library |

### SEO Monitoring API (for AI agents)
  "og_image": "/path/to/image.jpg",
  "canonical_url": "https://..."
}
```

## AI SEO Monitoring

The SEO monitoring system provides:

### 1. Real-time Analysis
- Title length and keyword placement
- Meta description optimization
- Content depth and keyword density
- Heading structure (H1, H2, H3)
- Readability scoring

### 2. Issue Tracking
- **Critical**: Missing H1, no focus keyword
- **Warning**: Content too thin, keyword stuffing
- **Info**: Missing CTA, long sentences

### 3. AI Recommendations
Integrates with Gemini/OpenAI to provide:
- Content optimization suggestions
- Title/description rewrites
- Related keyword suggestions
- Competitor gap analysis

### 4. Trend Tracking
- Weekly score snapshots
- Issue count over time
- Keyword ranking changes

## API Examples

### Analyze Content
```bash
curl -X POST http://localhost:8000/api/seo/analyze/content \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Your page content here...",
    "focus_keyword": "market research",
    "target_keywords": ["survey", "data collection"]
  }'
```

### Get Website Report
```bash
curl http://localhost:8000/api/seo/report/WEBSITE_ID
```

### AI Optimization
```bash
curl -X POST http://localhost:8000/api/seo/ai/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Current content...",
    "focus_keyword": "market research",
    "target_audience": "business professionals"
  }'
```

## Environment Variables

Add to your `.env`:

```env
# MongoDB
MONGODB_URI=mongodb://localhost:27017

# AI Providers (for SEO optimization)
GEMINI_API_KEY=your_gemini_key
OPENAI_API_KEY=your_openai_key_fallback
```

## CRM Integration

Once integrated, content can be managed from:

**CRM > Marketing > Websites**
- Edit website settings
- Update navigation
- Manage pages and sections
- View SEO scores

**CRM > Marketing > Blog**
- Create/edit blog posts
- SEO metadata for each post
- Category and tag management

**CRM > Marketing > SEO Dashboard** (new)
- Overall website score
- Page-by-page analysis
- Trending issues
- AI recommendations

## Troubleshooting

### MongoDB Connection Issues
```bash
# Check MongoDB is running
mongosh --eval "db.adminCommand('ping')"

# Verify database exists
mongosh marketing_db --eval "show collections"
```

### Missing Content
```bash
# Re-run seed script
python seed_website_content.py
```

### API Not Responding
```bash
# Check router is registered
curl http://localhost:8000/docs | grep seo
```
