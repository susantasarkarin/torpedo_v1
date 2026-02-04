# AI Assistant Prompt: Python to Node.js + n8n Migration Guide

**Purpose:** This is a comprehensive prompt you can provide to AI assistants (ChatGPT, Claude, GitHub Copilot, etc.) to guide them in helping you migrate the Campaign Platform from Python/FastAPI to Node.js/Express + n8n.

---

## Master Prompt for AI Assistants

Copy and paste this prompt to your AI assistant when starting the migration:

```
I am migrating a Campaign Platform application from Python/FastAPI to Node.js/Express + n8n. 
I need your help to guide this migration systematically.

# PROJECT CONTEXT

## Current Architecture
- **Backend:** Python 3.x with FastAPI framework
- **Frontend:** React 18.3 with Vite (keeping as-is)
- **Database:** MongoDB (keeping as-is)
- **Cache:** Redis (keeping as-is)
- **Automation:** 100+ Python scripts for workflows and scheduled jobs
- **Website:** Next.js (will migrate to PHP separately)

## Current Codebase Stats
- 664 total files (350 Python backend, 200 React, 100+ scripts)
- 61,000+ lines of code
- Key features: Campaign management, lead management, email automation, survey integration

## Target Architecture
- **Backend:** Node.js 20+ with Express.js framework
- **Frontend:** React 18.3 with Vite (unchanged)
- **Database:** MongoDB with Mongoose ODM (unchanged)
- **Cache:** Redis (unchanged)
- **Automation:** n8n workflows (replacing Python scripts)
- **Language:** TypeScript for type safety

## Migration Goals
1. Convert Python/FastAPI backend to Node.js/Express with TypeScript
2. Migrate 100+ Python automation scripts to n8n visual workflows
3. Maintain 100% feature parity
4. Ensure zero data loss
5. Minimize downtime during transition

# PYTHON BACKEND STRUCTURE TO MIGRATE

## Directory Structure
```
backend/
├── main.py                    # FastAPI application entry
├── database.py                # MongoDB connection singleton
├── auth.py                    # Password hashing, verification
├── utils.py                   # URL validation, utilities
├── session_store.py           # Redis session management
├── schemas.py                 # Pydantic models
├── routers/                   # API route handlers
│   ├── traffic.py            # Traffic management endpoints
│   ├── cpx_api.py            # CPX Research integration
│   ├── users.py              # User management
│   └── [other routers]
├── services/                  # Business logic
│   ├── cpx_service.py        # CPX Research service
│   ├── cint_service.py       # Cint integration
│   ├── traffic_service.py    # Traffic routing logic
│   └── [other services]
├── agents/                    # AI agent implementations
├── campaigns/                 # Campaign management
├── leads/                     # Lead management
├── email_sync/                # Email synchronization
├── workflows/                 # Workflow definitions
└── tasks/                     # Background tasks
```

## Key Technologies Used
- **FastAPI:** ASGI web framework
- **PyMongo:** MongoDB driver
- **Pydantic:** Data validation
- **APScheduler:** Scheduled jobs
- **Redis-py:** Redis client
- **CORS Middleware:** Cross-origin requests
- **JWT/Sessions:** Authentication

## External Integrations
1. **CPX Research API** - Survey platform integration
2. **Cint API** - Survey platform integration
3. **Gmail/Google Workspace APIs** - Email automation
4. **OpenAI API** - AI-powered lead classification
5. **Google Gemini API** - AI provider
6. **Anthropic Claude API** - AI provider
7. **Google Custom Search API** - Lead enrichment

# MIGRATION STRATEGY

## Phase 1: Project Setup (Week 1)
Create new Node.js project structure alongside existing Python backend:

```
campaign-platform-node/
├── package.json              # Dependencies
├── tsconfig.json             # TypeScript config
├── .env.example              # Environment variables
├── src/
│   ├── server.ts            # Express app entry
│   ├── config/
│   │   └── database.ts      # MongoDB connection
│   ├── models/              # Mongoose models
│   ├── routes/              # Express routes
│   ├── services/            # Business logic
│   ├── middleware/          # Express middleware
│   ├── utils/               # Utilities
│   └── types/               # TypeScript types
├── tests/                   # Jest tests
└── dist/                    # Compiled JavaScript
```

**Tasks for AI:**
- Help set up package.json with required dependencies
- Configure TypeScript with strict mode
- Set up Express.js server with middleware
- Configure Mongoose for MongoDB
- Set up Redis client for sessions
- Create folder structure

## Phase 2: Database Models (Week 2)
Convert Pydantic models to Mongoose schemas:

**Python Example (schemas.py):**
```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class LeadSchema(BaseModel):
    email: str
    name: Optional[str] = None
    status: str = "new"
    created_at: datetime
    updated_at: datetime
```

**Node.js Target (models/Lead.ts):**
```typescript
import mongoose, { Document, Schema } from 'mongoose';

interface ILead extends Document {
  email: string;
  name?: string;
  status: string;
  createdAt: Date;
  updatedAt: Date;
}

const LeadSchema = new Schema<ILead>({
  email: { type: String, required: true, unique: true },
  name: { type: String },
  status: { type: String, default: 'new' },
}, { timestamps: true });

export default mongoose.model<ILead>('Lead', LeadSchema);
```

**Tasks for AI:**
- Convert all Pydantic models to Mongoose schemas
- Ensure field types match (String, Number, Date, Boolean, ObjectId)
- Add indexes where appropriate
- Handle validation rules
- Preserve relationships between models

## Phase 3: Core APIs (Weeks 3-6)

### 3.1 Authentication & User Management

**Python Example (routers/users.py):**
```python
from fastapi import APIRouter, HTTPException, Depends
from passlib.context import CryptContext

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"])

@router.post("/api/auth/login")
async def login(email: str, password: str):
    user = await db.users.find_one({"email": email})
    if not user or not pwd_context.verify(password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    session_token = create_session(user["_id"])
    return {"token": session_token, "user": user}
```

**Node.js Target (routes/auth.ts):**
```typescript
import express from 'express';
import bcrypt from 'bcrypt';
import User from '../models/User';
import { createSession } from '../utils/session';

const router = express.Router();

router.post('/api/auth/login', async (req, res) => {
  try {
    const { email, password } = req.body;
    
    const user = await User.findOne({ email });
    if (!user || !await bcrypt.compare(password, user.password)) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }
    
    const token = await createSession(user._id);
    res.json({ token, user });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

export default router;
```

**Tasks for AI:**
- Convert all FastAPI routes to Express routes
- Handle async/await patterns
- Implement proper error handling
- Convert HTTPException to Express error responses
- Migrate authentication middleware
- Convert dependency injection to Express middleware

### 3.2 Lead Management APIs

**Python Pattern:**
```python
@router.get("/api/leads")
async def get_leads(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None
):
    query = {}
    if status:
        query["status"] = status
    
    leads = await db.leads.find(query).skip(skip).limit(limit).to_list(length=limit)
    total = await db.leads.count_documents(query)
    
    return {
        "leads": leads,
        "total": total,
        "page": skip // limit + 1
    }
```

**Node.js Pattern:**
```typescript
router.get('/api/leads', async (req, res) => {
  try {
    const { skip = 0, limit = 50, status } = req.query;
    
    const query: any = {};
    if (status) query.status = status;
    
    const [leads, total] = await Promise.all([
      Lead.find(query).skip(Number(skip)).limit(Number(limit)),
      Lead.countDocuments(query)
    ]);
    
    res.json({
      leads,
      total,
      page: Math.floor(Number(skip) / Number(limit)) + 1
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});
```

**Tasks for AI:**
- Convert all CRUD operations
- Handle query parameters properly
- Implement pagination consistently
- Add input validation (using Joi or Zod)
- Convert ObjectId handling
- Maintain API response structure

### 3.3 External API Integrations

**Python Pattern (services/cpx_service.py):**
```python
import httpx
from typing import Dict, Any

class CPXService:
    def __init__(self):
        self.base_url = "https://api.cpx-research.com"
        self.api_key = os.getenv("CPX_API_KEY")
    
    async def get_surveys(self, user_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/surveys",
                headers={"Authorization": f"Bearer {self.api_key}"},
                params={"user_id": user_id}
            )
            return response.json()
```

**Node.js Pattern (services/cpxService.ts):**
```typescript
import axios, { AxiosInstance } from 'axios';

class CPXService {
  private client: AxiosInstance;
  private apiKey: string;
  
  constructor() {
    this.apiKey = process.env.CPX_API_KEY || '';
    this.client = axios.create({
      baseURL: 'https://api.cpx-research.com',
      headers: {
        'Authorization': `Bearer ${this.apiKey}`
      }
    });
  }
  
  async getSurveys(userId: string) {
    try {
      const response = await this.client.get('/surveys', {
        params: { user_id: userId }
      });
      return response.data;
    } catch (error) {
      throw new Error(`CPX API error: ${error.message}`);
    }
  }
}

export default new CPXService();
```

**Tasks for AI:**
- Convert all HTTP clients (httpx → axios)
- Handle async/await properly
- Implement retry logic
- Add rate limiting
- Convert environment variable access
- Maintain error handling patterns

## Phase 4: Automation Scripts to n8n (Weeks 7-10)

This is covered in the separate workflow conversion guide. For AI assistance:

**Tasks for AI:**
- Analyze each Python script's purpose
- Map Python logic to n8n nodes
- Create workflow JSON definitions
- Handle complex conditional logic
- Implement error handling in workflows

## Phase 5: Testing (Weeks 11-12)

**Unit Tests with Jest:**
```typescript
// tests/services/leadService.test.ts
import LeadService from '../../src/services/leadService';
import Lead from '../../src/models/Lead';

jest.mock('../../src/models/Lead');

describe('LeadService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });
  
  test('should create a new lead', async () => {
    const mockLead = {
      email: 'test@example.com',
      name: 'Test User',
      status: 'new'
    };
    
    (Lead.create as jest.Mock).mockResolvedValue(mockLead);
    
    const result = await LeadService.create(mockLead);
    
    expect(result).toEqual(mockLead);
    expect(Lead.create).toHaveBeenCalledWith(mockLead);
  });
});
```

**Tasks for AI:**
- Convert Python pytest tests to Jest
- Set up test mocks properly
- Write integration tests
- Create test fixtures
- Ensure test coverage > 80%

# SPECIFIC CONVERSION PATTERNS

## Pattern 1: FastAPI Dependency Injection → Express Middleware

**Python:**
```python
from fastapi import Depends, HTTPException

async def get_current_user(token: str = Depends(oauth2_scheme)):
    user = verify_token(token)
    if not user:
        raise HTTPException(status_code=401)
    return user

@router.get("/api/profile")
async def get_profile(user = Depends(get_current_user)):
    return user
```

**Node.js:**
```typescript
// middleware/auth.ts
export const authenticate = async (req, res, next) => {
  try {
    const token = req.headers.authorization?.replace('Bearer ', '');
    const user = await verifyToken(token);
    if (!user) {
      return res.status(401).json({ error: 'Unauthorized' });
    }
    req.user = user;
    next();
  } catch (error) {
    res.status(401).json({ error: 'Unauthorized' });
  }
};

// routes/profile.ts
router.get('/api/profile', authenticate, (req, res) => {
  res.json(req.user);
});
```

## Pattern 2: Pydantic Validation → Zod/Joi

**Python:**
```python
from pydantic import BaseModel, EmailStr, validator

class CreateLeadRequest(BaseModel):
    email: EmailStr
    name: str
    
    @validator('name')
    def name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Name cannot be empty')
        return v.strip()
```

**Node.js with Zod:**
```typescript
import { z } from 'zod';

const CreateLeadSchema = z.object({
  email: z.string().email(),
  name: z.string().trim().min(1, 'Name cannot be empty')
});

// In route:
router.post('/api/leads', async (req, res) => {
  try {
    const data = CreateLeadSchema.parse(req.body);
    // Process validated data
  } catch (error) {
    res.status(400).json({ error: error.errors });
  }
});
```

## Pattern 3: APScheduler → n8n Workflows

**Python Script:**
```python
# email_classifier.py
from apscheduler.schedulers.background import BackgroundScheduler

def classify_emails():
    emails = db.emails.find({"classified": False})
    for email in emails:
        result = openai_classify(email)
        db.emails.update_one(
            {"_id": email["_id"]},
            {"$set": {"category": result, "classified": True}}
        )

scheduler = BackgroundScheduler()
scheduler.add_job(classify_emails, 'interval', hours=1)
scheduler.start()
```

**n8n Workflow (see separate guide for details):**
- Trigger: Schedule (every 1 hour)
- MongoDB Node: Find unclassified emails
- Function Node: Loop through emails
- OpenAI Node: Classify each email
- MongoDB Node: Update classification
- Error handling nodes

# KEY MODULES TO MIGRATE

## Priority 1 (Critical Path - Weeks 3-4)
1. **Authentication & User Management**
   - `backend/auth.py` → `src/services/authService.ts`
   - `backend/routers/users.py` → `src/routes/auth.ts`
   - Session management
   - Password hashing (bcrypt)

2. **Database Layer**
   - `backend/database.py` → `src/config/database.ts`
   - Connection pooling
   - Error handling

3. **Core Models**
   - `backend/schemas.py` → `src/models/*.ts`
   - User, Lead, Campaign, Survey models

## Priority 2 (Core Features - Weeks 5-6)
4. **Lead Management**
   - `backend/leads/` → `src/routes/leads.ts` + `src/services/leadService.ts`
   - CRUD operations
   - Search and filtering
   - Bulk operations

5. **Campaign Management**
   - `backend/campaigns/` → `src/routes/campaigns.ts` + `src/services/campaignService.ts`
   - Campaign creation
   - Execution logic
   - Analytics

6. **Traffic Management**
   - `backend/routers/traffic.py` → `src/routes/traffic.ts`
   - Traffic routing
   - Survey allocation
   - Response handling

## Priority 3 (Integrations - Weeks 7-8)
7. **CPX Research Integration**
   - `backend/services/cpx_service.py` → `src/services/cpxService.ts`
   - Survey inventory
   - User tracking
   - Payout calculations

8. **Cint Integration**
   - `backend/services/cint_service.py` → `src/services/cintService.ts`
   - Survey matching
   - Status callbacks
   - Analytics

9. **Email Services**
   - `backend/email_sync/` → n8n workflows + `src/services/emailService.ts`
   - Gmail API integration
   - Email parsing
   - Classification (use n8n)

## Priority 4 (AI & Automation - Weeks 9-10)
10. **AI Provider Services**
    - `backend/agents/` → `src/services/aiService.ts`
    - OpenAI integration
    - Gemini integration
    - Anthropic integration
    - Multi-provider routing

11. **Background Jobs**
    - All Python scripts → n8n workflows
    - Scheduled report generation
    - Data cleanup
    - Sync operations

# ENVIRONMENT VARIABLES MIGRATION

**Python (.env):**
```bash
MONGO_URI=mongodb://localhost:27017/
API_BASE=http://localhost:8000
SESSION_SECRET=secret-key
CPX_API_KEY=xxx
OPENAI_API_KEY=xxx
```

**Node.js (.env):**
```bash
MONGO_URI=mongodb://localhost:27017/campaign_platform
PORT=3000
NODE_ENV=development
SESSION_SECRET=secret-key
REDIS_URL=redis://localhost:6379
CPX_API_KEY=xxx
OPENAI_API_KEY=xxx
```

**Tasks for AI:**
- Map all environment variables
- Update variable names to Node.js conventions
- Add new required variables
- Document all variables in .env.example

# TESTING STRATEGY

## Unit Tests
- Test all services independently
- Mock external dependencies
- Aim for 80%+ coverage
- Use Jest framework

## Integration Tests
- Test API endpoints
- Use test database
- Test authentication flow
- Test external integrations (mocked)

## End-to-End Tests
- Test complete user flows
- Run against staging environment
- Automate with GitHub Actions

# DEPLOYMENT STRATEGY

## Parallel Running (Weeks 11-12)
1. Deploy Node.js backend to new server
2. Keep Python backend running
3. Route 10% traffic to Node.js
4. Monitor for errors
5. Gradually increase traffic
6. Keep Python as fallback

## Cutover Checklist
- [ ] All APIs tested and working
- [ ] Performance benchmarks met
- [ ] Error rates < 1%
- [ ] All integrations verified
- [ ] n8n workflows deployed
- [ ] Monitoring dashboards ready
- [ ] Rollback plan tested
- [ ] Team trained on new system

# HOW TO USE THIS PROMPT WITH AI

When working with me (your AI assistant), follow this workflow:

1. **Start each session with context:**
   "I'm migrating [specific module] from Python to Node.js. Here's the Python code: [paste code]"

2. **Ask for step-by-step conversion:**
   "Convert this Python FastAPI endpoint to Node.js Express with TypeScript"

3. **Request best practices:**
   "What's the Node.js equivalent of Python's [feature]?"

4. **Ask for complete files:**
   "Generate the complete Node.js file for this Python module"

5. **Request tests:**
   "Generate Jest tests for this converted service"

6. **Ask for troubleshooting:**
   "This converted code isn't working. Python version: [code]. Node.js version: [code]. Error: [error]"

# COMMON ISSUES & SOLUTIONS

## Issue 1: Async/Await Differences
**Python:** All database operations are async by default
**Node.js:** Must explicitly await Mongoose operations

## Issue 2: Error Handling
**Python:** Raises exceptions, caught by FastAPI
**Node.js:** Use try/catch blocks, return error responses

## Issue 3: Type Safety
**Python:** Pydantic validates at runtime
**Node.js:** TypeScript validates at compile time + runtime validation library

## Issue 4: MongoDB ObjectId
**Python:** Automatic string conversion
**Node.js:** Must explicitly handle ObjectId type

# SUCCESS METRICS

Track these during migration:
- [ ] API response time < 200ms (maintained)
- [ ] Test coverage > 80%
- [ ] Zero data loss
- [ ] All features working
- [ ] Error rate < 0.5%
- [ ] No performance degradation

# NEED HELP WITH SPECIFIC MODULE?

Ask me: "Help me migrate [module_name] from Python to Node.js. Here's the Python code: [paste code]"

I will provide:
1. Complete Node.js TypeScript code
2. Required npm packages
3. Database models needed
4. Tests for the module
5. Integration steps
```

---

## Usage Instructions

### For Each Module Migration:

1. **Copy the master prompt above** to your AI assistant

2. **Then provide module-specific context:**
```
I'm now migrating the Lead Management module. Here's the Python code:

[paste relevant Python files]

Convert this to Node.js with TypeScript, including:
- Express routes
- Mongoose models
- Service layer
- Input validation
- Error handling
- Jest tests
```

3. **Review AI output** and ask follow-up questions:
```
- "Add input validation using Zod"
- "Handle this edge case: [describe]"
- "Optimize this for performance"
- "Add proper error logging"
```

4. **Request tests:**
```
Generate comprehensive Jest tests for this module including:
- Unit tests for service layer
- Integration tests for API endpoints
- Mock external dependencies
```

### For Troubleshooting:

```
I'm getting this error when running the converted code:

Error: [paste error]

Python version that worked:
[paste Python code]

Node.js version that's failing:
[paste Node.js code]

Help me debug this.
```

---

## Quick Reference: Python to Node.js Equivalents

| Python | Node.js | Package |
|--------|---------|---------|
| FastAPI | Express | `express` |
| Pydantic | Zod | `zod` |
| PyMongo | Mongoose | `mongoose` |
| httpx | axios | `axios` |
| pytest | Jest | `jest` |
| asyncio | native async/await | built-in |
| python-dotenv | dotenv | `dotenv` |
| passlib | bcrypt | `bcrypt` |
| APScheduler | n8n | self-hosted |
| typing | TypeScript | built-in |

---

## Next Steps

1. Set up Node.js project using this prompt
2. Start with Priority 1 modules (Authentication)
3. Test each module thoroughly before moving to next
4. Use the workflow conversion guide for automation scripts
5. Run parallel systems before full cutover

**Estimated Timeline:** 10-12 weeks for complete migration

**Team Size:** 3-4 developers recommended
