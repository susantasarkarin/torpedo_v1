# Node.js Conversion Guide for Campaign Platform

## Quick Answer

**YES, you CAN convert this project to Node.js!** 

However, it's important to understand:

1. **Frontend is already JavaScript** (React + Vite) - No conversion needed
2. **Backend needs conversion** (Python FastAPI → Node.js Express/NestJS)
3. **Database stays the same** (MongoDB works with Node.js)

## Current Architecture

### Backend (Python/FastAPI)
- **Framework**: FastAPI (Python 3.x)
- **Database**: MongoDB (PyMongo driver)
- **Key Dependencies**:
  - FastAPI for REST APIs
  - PyMongo for MongoDB
  - Uvicorn for ASGI server
  - Google Generative AI (Gemini)
  - OpenAI Python SDK
  - Python-dotenv for environment variables
  - APScheduler for background jobs
  - BeautifulSoup4 for web scraping

### Frontend (Already Node.js!)
- **Framework**: React 18.3.1
- **Build Tool**: Vite 7.1.5
- **UI Components**: Radix UI
- **Styling**: Tailwind CSS
- **Routing**: React Router DOM

## Conversion Strategy

### Option 1: Full Backend Conversion to Node.js

This involves rewriting the entire Python backend in Node.js.

#### Recommended Stack
1. **Web Framework**: Express.js or NestJS
   - Express.js: Lightweight, flexible (similar to FastAPI's simplicity)
   - NestJS: Full-featured, TypeScript-first (similar to FastAPI's structure)

2. **Database Driver**: MongoDB Native Driver or Mongoose
   - `mongodb` package (official driver)
   - `mongoose` for ODM (Object-Document Mapping)

3. **Authentication**: Passport.js or JSON Web Tokens (jsonwebtoken)

4. **Environment Variables**: dotenv

5. **Background Jobs**: Bull/BullMQ, node-cron, or Agenda

6. **API Documentation**: Swagger/OpenAPI (swagger-ui-express)

### Option 2: Hybrid Approach (Recommended)

Keep the Python backend for AI/ML-heavy operations, use Node.js for specific microservices.

**Why Hybrid?**
- Python excels at AI/ML operations
- Node.js excels at real-time operations and high concurrency
- You can migrate gradually

## Dependency Mapping (Python → Node.js)

| Python Package | Node.js Equivalent | Notes |
|----------------|-------------------|-------|
| `fastapi` | `express` or `@nestjs/core` | Web framework |
| `uvicorn` | Built into Node.js/Express | Node's HTTP server |
| `pymongo` | `mongodb` or `mongoose` | MongoDB driver |
| `pydantic` | `zod` or `joi` | Data validation |
| `python-dotenv` | `dotenv` | Environment variables |
| `requests` | `axios` or `node-fetch` | HTTP client |
| `google-generativeai` | `@google/generative-ai` | Gemini AI SDK |
| `openai` | `openai` | OpenAI SDK (same package name!) |
| `beautifulsoup4` | `cheerio` or `jsdom` | Web scraping |
| `apscheduler` | `node-cron`, `bull`, or `agenda` | Job scheduling |
| `python-multipart` | `multer` | File uploads |
| `email-validator` | `validator` | Email validation |

## Step-by-Step Conversion Process

### Phase 1: Setup & Infrastructure (Week 1)

1. **Initialize Node.js Backend**
```bash
mkdir backend-nodejs
cd backend-nodejs
npm init -y
npm install express mongoose dotenv cors
npm install --save-dev typescript @types/node @types/express ts-node nodemon
```

2. **Setup TypeScript** (Recommended)
```bash
npx tsc --init
```

3. **Create Basic Express Server**
```javascript
// server.js or app.ts
import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import mongoose from 'mongoose';

dotenv.config();

const app = express();
const PORT = process.env.PORT || 8000;

app.use(cors());
app.use(express.json());

// MongoDB Connection
mongoose.connect(process.env.MONGO_URI || 'mongodb://localhost:27017/campaign_platform')
  .then(() => console.log('MongoDB connected'))
  .catch(err => console.error('MongoDB connection error:', err));

// Basic health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date() });
});

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
```

### Phase 2: Database Layer (Week 2)

Convert Python database models to Mongoose schemas.

**Python (database.py):**
```python
class DatabaseManager:
    _client = None
    
    def get_database(self, name):
        return self._client[name]
```

**Node.js (database.js):**
```javascript
import mongoose from 'mongoose';

class DatabaseManager {
  static client = null;
  
  static async connect(uri) {
    if (!this.client) {
      this.client = await mongoose.connect(uri);
    }
    return this.client;
  }
  
  static getDatabase(name) {
    return mongoose.connection.useDb(name);
  }
}

export default DatabaseManager;
```

### Phase 3: API Routes Conversion (Week 3-4)

Convert FastAPI routers to Express routers.

**Python FastAPI Router Example:**
```python
from fastapi import APIRouter, HTTPException
router = APIRouter()

@router.get("/users/{user_id}")
async def get_user(user_id: str):
    user = db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
```

**Node.js Express Router Equivalent:**
```javascript
import express from 'express';
import { ObjectId } from 'mongodb';

const router = express.Router();

router.get('/users/:userId', async (req, res) => {
  try {
    const user = await db.collection('users').findOne({
      _id: new ObjectId(req.params.userId)
    });
    
    if (!user) {
      return res.status(404).json({ detail: 'User not found' });
    }
    
    res.json(user);
  } catch (error) {
    res.status(500).json({ detail: error.message });
  }
});

export default router;
```

### Phase 4: Authentication & Middleware (Week 5)

Convert Python authentication to JWT-based Node.js authentication.

**Node.js JWT Authentication:**
```javascript
import jwt from 'jsonwebtoken';
import bcrypt from 'bcrypt';

// Middleware
export const authMiddleware = (req, res, next) => {
  const token = req.headers.authorization?.split(' ')[1];
  
  if (!token) {
    return res.status(401).json({ detail: 'No token provided' });
  }
  
  try {
    const decoded = jwt.verify(token, process.env.JWT_SECRET);
    req.user = decoded;
    next();
  } catch (error) {
    res.status(401).json({ detail: 'Invalid token' });
  }
};

// Login endpoint
router.post('/login', async (req, res) => {
  const { email, password } = req.body;
  const user = await db.collection('users').findOne({ email });
  
  if (!user || !(await bcrypt.compare(password, user.password))) {
    return res.status(401).json({ detail: 'Invalid credentials' });
  }
  
  const token = jwt.sign({ userId: user._id }, process.env.JWT_SECRET, {
    expiresIn: '24h'
  });
  
  res.json({ token, user });
});
```

### Phase 5: AI Integration (Week 6)

Convert AI/ML endpoints to use Node.js SDKs.

**OpenAI Integration:**
```javascript
import OpenAI from 'openai';

const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY
});

router.post('/classify-lead', async (req, res) => {
  try {
    const completion = await openai.chat.completions.create({
      model: 'gpt-4',
      messages: [
        { role: 'system', content: 'You are a lead classification expert.' },
        { role: 'user', content: req.body.leadData }
      ]
    });
    
    res.json({ classification: completion.choices[0].message.content });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});
```

**Google Gemini Integration:**
```javascript
import { GoogleGenerativeAI } from '@google/generative-ai';

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);

router.post('/generate-content', async (req, res) => {
  try {
    const model = genAI.getGenerativeModel({ model: 'gemini-pro' });
    const result = await model.generateContent(req.body.prompt);
    
    res.json({ content: result.response.text() });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});
```

### Phase 6: Background Jobs (Week 7)

Convert APScheduler jobs to Node.js job schedulers.

**Using Bull for background jobs:**
```javascript
import Queue from 'bull';
import Redis from 'ioredis';

const emailQueue = new Queue('email-processing', {
  redis: {
    host: process.env.REDIS_HOST || 'localhost',
    port: process.env.REDIS_PORT || 6379
  }
});

// Add job to queue
emailQueue.add('send-campaign', {
  campaignId: '123',
  recipientCount: 1000
});

// Process job
emailQueue.process('send-campaign', async (job) => {
  console.log('Processing campaign:', job.data.campaignId);
  // Your email sending logic here
});
```

**Using node-cron for scheduled tasks:**
```javascript
import cron from 'node-cron';

// Run every day at midnight
cron.schedule('0 0 * * *', async () => {
  console.log('Running daily cleanup job');
  await cleanupOldData();
});
```

### Phase 7: Testing & Deployment (Week 8+)

1. **Unit Tests**: Use Jest or Mocha
2. **Integration Tests**: Use Supertest
3. **Deployment**: Same deployment strategies work (Docker, PM2, systemd)

## File Structure Comparison

### Current Python Structure
```
backend/
├── main.py              # Main FastAPI app
├── database.py          # Database connections
├── auth.py              # Authentication
├── routers/             # API routes
│   ├── users.py
│   ├── traffic.py
│   └── ...
├── agents/              # AI agents
├── services/            # Business logic
└── requirements.txt     # Python dependencies
```

### Proposed Node.js Structure
```
backend-nodejs/
├── src/
│   ├── app.ts              # Main Express app
│   ├── server.ts           # Server entry point
│   ├── config/
│   │   ├── database.ts     # MongoDB config
│   │   └── redis.ts        # Redis config
│   ├── middleware/
│   │   ├── auth.ts         # Authentication middleware
│   │   └── errorHandler.ts
│   ├── routes/             # API routes
│   │   ├── users.ts
│   │   ├── traffic.ts
│   │   └── index.ts
│   ├── models/             # Mongoose models
│   │   ├── User.ts
│   │   └── Campaign.ts
│   ├── services/           # Business logic
│   │   ├── aiService.ts
│   │   └── emailService.ts
│   ├── jobs/               # Background jobs
│   │   └── emailJobs.ts
│   └── types/              # TypeScript types
├── tests/
├── package.json
└── tsconfig.json
```

## Example: Complete Conversion of a Simple Endpoint

### Python FastAPI (Original)
```python
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List

router = APIRouter()

class Campaign(BaseModel):
    name: str
    description: str
    target_audience: List[str]

@router.post("/campaigns")
async def create_campaign(campaign: Campaign, user = Depends(get_current_user)):
    db = get_database("campaign_platform")
    
    campaign_doc = {
        "name": campaign.name,
        "description": campaign.description,
        "target_audience": campaign.target_audience,
        "user_id": user["_id"],
        "created_at": datetime.utcnow()
    }
    
    result = db.campaigns.insert_one(campaign_doc)
    campaign_doc["_id"] = str(result.inserted_id)
    
    return campaign_doc
```

### Node.js/Express (Converted)
```typescript
import express from 'express';
import { z } from 'zod';
import { authMiddleware } from '../middleware/auth';
import { getDatabase } from '../config/database';

const router = express.Router();

// Validation schema (replaces Pydantic)
const CampaignSchema = z.object({
  name: z.string(),
  description: z.string(),
  target_audience: z.array(z.string())
});

router.post('/campaigns', authMiddleware, async (req, res) => {
  try {
    // Validate input
    const campaign = CampaignSchema.parse(req.body);
    
    const db = getDatabase('campaign_platform');
    
    const campaignDoc = {
      name: campaign.name,
      description: campaign.description,
      target_audience: campaign.target_audience,
      user_id: req.user._id,
      created_at: new Date()
    };
    
    const result = await db.collection('campaigns').insertOne(campaignDoc);
    campaignDoc._id = result.insertedId.toString();
    
    res.status(201).json(campaignDoc);
  } catch (error) {
    if (error instanceof z.ZodError) {
      res.status(422).json({ errors: error.errors });
    } else {
      res.status(500).json({ error: error.message });
    }
  }
});

export default router;
```

## Advantages of Converting to Node.js

### Benefits
1. **Single Language Stack**: JavaScript/TypeScript across frontend and backend
2. **Better Real-time Performance**: Node.js excels at WebSockets and Server-Sent Events
3. **NPM Ecosystem**: Largest package ecosystem in the world
4. **High Concurrency**: Event-driven architecture handles many connections efficiently
5. **Developer Pool**: Larger pool of JavaScript developers
6. **Type Safety**: TypeScript provides strong typing like Python type hints
7. **Easier Full-Stack Development**: Developers can work on both frontend and backend

### Challenges
1. **Python AI Libraries**: Some Python AI/ML libraries don't have Node.js equivalents
2. **Data Science Tools**: Python is stronger for data analysis (pandas, numpy)
3. **Rewriting Effort**: Significant development time required
4. **Testing**: Need to rewrite all tests
5. **Learning Curve**: Team needs Node.js expertise

## Effort Estimation

### For Your Project (~2,800 Python files)

| Phase | Estimated Time | Team Size |
|-------|----------------|-----------|
| Planning & Setup | 1 week | 2-3 developers |
| Database Layer | 2 weeks | 2 developers |
| API Routes (Core) | 3-4 weeks | 3-4 developers |
| Authentication | 1-2 weeks | 2 developers |
| AI Integration | 2-3 weeks | 2-3 developers |
| Background Jobs | 1-2 weeks | 1-2 developers |
| Testing | 2-3 weeks | 2-3 developers |
| Documentation | 1 week | 1-2 developers |
| **Total** | **3-4 months** | **Team of 3-4** |

## Recommended Approach

### For Immediate Action

**DON'T convert everything at once.** Instead:

1. **Start with a microservice**: Pick one module (e.g., traffic routing) and convert it to Node.js
2. **Run both backends in parallel**: Use a reverse proxy (Nginx) to route requests
3. **Gradually migrate**: Move endpoints one by one
4. **Keep AI/ML in Python**: If heavy AI/ML processing, keep those services in Python

### Proof of Concept (1 Week)

Create a minimal Node.js backend that:
1. Connects to your MongoDB
2. Implements 2-3 critical endpoints
3. Integrates with OpenAI/Gemini
4. Works with your existing React frontend

This helps you:
- Validate the approach
- Identify challenges early
- Estimate effort more accurately
- Get team buy-in

## Sample Package.json for Node.js Backend

```json
{
  "name": "campaign-platform-nodejs",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "nodemon --exec ts-node src/server.ts",
    "build": "tsc",
    "start": "node dist/server.js",
    "test": "jest"
  },
  "dependencies": {
    "express": "^4.18.2",
    "mongoose": "^8.0.0",
    "dotenv": "^16.3.1",
    "cors": "^2.8.5",
    "jsonwebtoken": "^9.0.2",
    "bcrypt": "^5.1.1",
    "zod": "^3.22.4",
    "openai": "^4.20.0",
    "@google/generative-ai": "^0.3.0",
    "bull": "^4.11.5",
    "node-cron": "^3.0.3",
    "axios": "^1.6.0",
    "cheerio": "^1.0.0-rc.12",
    "validator": "^13.11.0"
  },
  "devDependencies": {
    "@types/express": "^4.17.21",
    "@types/node": "^20.10.0",
    "typescript": "^5.3.2",
    "ts-node": "^10.9.1",
    "nodemon": "^3.0.2",
    "jest": "^29.7.0",
    "supertest": "^6.3.3"
  }
}
```

## Conclusion

**YES, you can convert this project to Node.js!** It's technically feasible and has many benefits, especially if you want a unified JavaScript/TypeScript stack.

**However, consider:**
- The significant development effort required (3-4 months with a team)
- Whether the benefits justify the cost
- Starting with a hybrid approach (Python for AI/ML, Node.js for web APIs)
- Building a proof of concept first

**Recommendation**: If this is a production system, do a **gradual migration** rather than a full rewrite. If it's a learning project or you're starting fresh, Node.js is an excellent choice.

## Next Steps

1. **Review this guide with your team**
2. **Decide on migration strategy** (full conversion vs. hybrid vs. microservices)
3. **Build a proof of concept** (1-2 week sprint)
4. **Create detailed migration plan** with priorities
5. **Set up CI/CD for Node.js backend**
6. **Begin with low-risk modules**

## Additional Resources

- [Express.js Documentation](https://expressjs.com/)
- [NestJS Documentation](https://nestjs.com/)
- [Mongoose Documentation](https://mongoosejs.com/)
- [Node.js Best Practices](https://github.com/goldbergyoni/nodebestpractices)
- [TypeScript Handbook](https://www.typescriptlang.org/docs/)

---

**Questions?** This guide provides a comprehensive overview. Choose the approach that best fits your timeline, budget, and goals.
