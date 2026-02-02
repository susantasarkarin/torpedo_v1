# Python to Node.js Conversion Examples

This document shows side-by-side comparisons of common patterns in the Campaign Platform.

## Table of Contents
- [Database Connection](#database-connection)
- [Model/Schema Definition](#modelschema-definition)
- [REST API Endpoints](#rest-api-endpoints)
- [Authentication](#authentication)
- [Error Handling](#error-handling)
- [Background Jobs](#background-jobs)
- [File Uploads](#file-uploads)
- [Environment Variables](#environment-variables)

---

## Database Connection

### Python (database.py)
```python
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

class DatabaseManager:
    _instance = None
    _client = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._client is None:
            mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
            self._client = MongoClient(mongo_uri)
    
    def get_database(self, name):
        return self._client[name]
    
    def get_collection(self, db_name, collection_name):
        return self._client[db_name][collection_name]

# Usage
db_manager = DatabaseManager()
db = db_manager.get_database("campaign_platform")
campaigns = db["campaigns"]
```

### Node.js (database.js)
```javascript
const mongoose = require('mongoose');
const dotenv = require('dotenv');

dotenv.config();

class DatabaseManager {
  static instance = null;
  static client = null;
  
  static getInstance() {
    if (!this.instance) {
      this.instance = new DatabaseManager();
    }
    return this.instance;
  }
  
  async connect() {
    if (!DatabaseManager.client) {
      const mongoUri = process.env.MONGO_URI || 'mongodb://localhost:27017/';
      DatabaseManager.client = await mongoose.connect(mongoUri);
    }
    return DatabaseManager.client;
  }
  
  getDatabase(name) {
    return mongoose.connection.useDb(name);
  }
  
  getCollection(dbName, collectionName) {
    const db = this.getDatabase(dbName);
    return db.collection(collectionName);
  }
}

// Usage
const dbManager = DatabaseManager.getInstance();
await dbManager.connect();
const db = dbManager.getDatabase('campaign_platform');
const campaigns = db.collection('campaigns');
```

---

## Model/Schema Definition

### Python (Pydantic)
```python
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
from datetime import datetime

class Campaign(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    name: str
    description: Optional[str] = None
    status: str = "draft"
    target_audience: List[str] = []
    budget: float = 0.0
    user_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "name": "Summer Campaign",
                "description": "Q3 marketing campaign",
                "budget": 5000.0
            }
        }
```

### Node.js (Mongoose)
```javascript
const mongoose = require('mongoose');

const campaignSchema = new mongoose.Schema({
  name: {
    type: String,
    required: [true, 'Campaign name is required'],
    trim: true,
    maxlength: 100
  },
  description: {
    type: String,
    trim: true
  },
  status: {
    type: String,
    enum: ['draft', 'active', 'paused', 'completed'],
    default: 'draft'
  },
  target_audience: [{
    type: String
  }],
  budget: {
    type: Number,
    default: 0.0,
    min: 0
  },
  user_id: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'User',
    required: true
  },
  created_at: {
    type: Date,
    default: Date.now
  },
  updated_at: {
    type: Date,
    default: Date.now
  }
}, {
  timestamps: true, // Automatically manage created_at/updated_at
  toJSON: { virtuals: true },
  toObject: { virtuals: true }
});

// Indexes
campaignSchema.index({ user_id: 1, status: 1 });
campaignSchema.index({ created_at: -1 });

const Campaign = mongoose.model('Campaign', campaignSchema);

module.exports = Campaign;
```

---

## REST API Endpoints

### Python (FastAPI)
```python
from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional
from bson import ObjectId

router = APIRouter()

@router.get("/campaigns")
async def get_campaigns(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    skip: int = Query(0, ge=0)
):
    query = {}
    if status:
        query["status"] = status
    
    campaigns = list(
        db.campaigns.find(query)
        .skip(skip)
        .limit(limit)
        .sort("created_at", -1)
    )
    
    total = db.campaigns.count_documents(query)
    
    return {
        "campaigns": campaigns,
        "total": total,
        "page": skip // limit + 1,
        "pages": (total + limit - 1) // limit
    }

@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str):
    try:
        campaign = db.campaigns.find_one({"_id": ObjectId(campaign_id)})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        return campaign
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/campaigns")
async def create_campaign(campaign: Campaign):
    campaign_dict = campaign.dict(by_alias=True, exclude_unset=True)
    result = db.campaigns.insert_one(campaign_dict)
    campaign_dict["_id"] = str(result.inserted_id)
    return campaign_dict

@router.put("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: str, campaign: Campaign):
    campaign_dict = campaign.dict(by_alias=True, exclude_unset=True)
    result = db.campaigns.update_one(
        {"_id": ObjectId(campaign_id)},
        {"$set": campaign_dict}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    return {"message": "Campaign updated"}

@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str):
    result = db.campaigns.delete_one({"_id": ObjectId(campaign_id)})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    return {"message": "Campaign deleted"}
```

### Node.js (Express)
```javascript
const express = require('express');
const Campaign = require('../models/Campaign');

const router = express.Router();

// GET /campaigns
router.get('/campaigns', async (req, res) => {
  try {
    const { status, limit = 50, skip = 0 } = req.query;
    
    const query = {};
    if (status) query.status = status;
    
    const campaigns = await Campaign.find(query)
      .skip(parseInt(skip))
      .limit(parseInt(limit))
      .sort({ created_at: -1 });
    
    const total = await Campaign.countDocuments(query);
    
    res.json({
      campaigns,
      total,
      page: Math.floor(skip / limit) + 1,
      pages: Math.ceil(total / limit)
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// GET /campaigns/:id
router.get('/campaigns/:id', async (req, res) => {
  try {
    const campaign = await Campaign.findById(req.params.id);
    
    if (!campaign) {
      return res.status(404).json({ detail: 'Campaign not found' });
    }
    
    res.json(campaign);
  } catch (error) {
    if (error.kind === 'ObjectId') {
      return res.status(400).json({ detail: 'Invalid campaign ID' });
    }
    res.status(500).json({ error: error.message });
  }
});

// POST /campaigns
router.post('/campaigns', async (req, res) => {
  try {
    const campaign = new Campaign(req.body);
    await campaign.save();
    res.status(201).json(campaign);
  } catch (error) {
    if (error.name === 'ValidationError') {
      return res.status(422).json({ errors: error.errors });
    }
    res.status(500).json({ error: error.message });
  }
});

// PUT /campaigns/:id
router.put('/campaigns/:id', async (req, res) => {
  try {
    const campaign = await Campaign.findByIdAndUpdate(
      req.params.id,
      { ...req.body, updated_at: Date.now() },
      { new: true, runValidators: true }
    );
    
    if (!campaign) {
      return res.status(404).json({ detail: 'Campaign not found' });
    }
    
    res.json(campaign);
  } catch (error) {
    if (error.name === 'ValidationError') {
      return res.status(422).json({ errors: error.errors });
    }
    res.status(500).json({ error: error.message });
  }
});

// DELETE /campaigns/:id
router.delete('/campaigns/:id', async (req, res) => {
  try {
    const campaign = await Campaign.findByIdAndDelete(req.params.id);
    
    if (!campaign) {
      return res.status(404).json({ detail: 'Campaign not found' });
    }
    
    res.json({ message: 'Campaign deleted' });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

module.exports = router;
```

---

## Authentication

### Python (FastAPI)
```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise credentials_exception
    return user

@router.post("/login")
async def login(username: str, password: str):
    user = db.users.find_one({"email": username})
    if not user or not verify_password(password, user["password"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    access_token = create_access_token(data={"sub": str(user["_id"])})
    return {"access_token": access_token, "token_type": "bearer"}
```

### Node.js (Express + JWT)
```javascript
const jwt = require('jsonwebtoken');
const bcrypt = require('bcrypt');
const User = require('../models/User');

const SECRET_KEY = process.env.SECRET_KEY;
const ACCESS_TOKEN_EXPIRE = '24h';

// Hash password
async function hashPassword(password) {
  return await bcrypt.hash(password, 10);
}

// Verify password
async function verifyPassword(plainPassword, hashedPassword) {
  return await bcrypt.compare(plainPassword, hashedPassword);
}

// Create access token
function createAccessToken(data) {
  return jwt.sign(data, SECRET_KEY, { 
    expiresIn: ACCESS_TOKEN_EXPIRE 
  });
}

// Authentication middleware
const authMiddleware = async (req, res, next) => {
  try {
    const authHeader = req.headers.authorization;
    
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      return res.status(401).json({ 
        detail: 'No authorization token provided' 
      });
    }
    
    const token = authHeader.substring(7);
    const payload = jwt.verify(token, SECRET_KEY);
    
    const user = await User.findById(payload.sub);
    if (!user) {
      return res.status(401).json({ 
        detail: 'User not found' 
      });
    }
    
    req.user = user;
    next();
  } catch (error) {
    if (error.name === 'JsonWebTokenError') {
      return res.status(401).json({ 
        detail: 'Invalid token' 
      });
    }
    if (error.name === 'TokenExpiredError') {
      return res.status(401).json({ 
        detail: 'Token expired' 
      });
    }
    res.status(500).json({ error: error.message });
  }
};

// Login endpoint
router.post('/login', async (req, res) => {
  try {
    const { username, password } = req.body;
    
    const user = await User.findOne({ email: username });
    
    if (!user || !(await verifyPassword(password, user.password))) {
      return res.status(401).json({ 
        detail: 'Incorrect username or password' 
      });
    }
    
    const accessToken = createAccessToken({ sub: user._id.toString() });
    
    res.json({
      access_token: accessToken,
      token_type: 'bearer'
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Protected route example
router.get('/profile', authMiddleware, (req, res) => {
  res.json(req.user);
});

module.exports = { authMiddleware, hashPassword, verifyPassword, createAccessToken };
```

---

## Error Handling

### Python (FastAPI)
```python
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "body": exc.body
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "message": str(exc)
        }
    )

class CampaignNotFoundError(Exception):
    pass

@app.exception_handler(CampaignNotFoundError)
async def campaign_not_found_handler(request: Request, exc: CampaignNotFoundError):
    return JSONResponse(
        status_code=404,
        content={"detail": str(exc)}
    )
```

### Node.js (Express)
```javascript
// Custom error classes
class CampaignNotFoundError extends Error {
  constructor(message) {
    super(message);
    this.name = 'CampaignNotFoundError';
    this.statusCode = 404;
  }
}

class ValidationError extends Error {
  constructor(message, errors) {
    super(message);
    this.name = 'ValidationError';
    this.statusCode = 422;
    this.errors = errors;
  }
}

// Error handling middleware (must be last)
app.use((err, req, res, next) => {
  console.error('Error:', err);
  
  // Mongoose validation error
  if (err.name === 'ValidationError') {
    return res.status(422).json({
      detail: err.errors,
      body: req.body
    });
  }
  
  // Custom errors
  if (err.statusCode) {
    return res.status(err.statusCode).json({
      detail: err.message,
      ...(err.errors && { errors: err.errors })
    });
  }
  
  // JWT errors
  if (err.name === 'JsonWebTokenError' || err.name === 'TokenExpiredError') {
    return res.status(401).json({
      detail: 'Authentication failed',
      message: err.message
    });
  }
  
  // MongoDB errors
  if (err.name === 'MongoError' && err.code === 11000) {
    return res.status(409).json({
      detail: 'Duplicate key error',
      field: Object.keys(err.keyPattern)[0]
    });
  }
  
  // Default error
  res.status(500).json({
    detail: 'Internal server error',
    message: err.message
  });
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({
    detail: 'Endpoint not found',
    path: req.path
  });
});
```

---

## Background Jobs

### Python (APScheduler)
```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import atexit

scheduler = BackgroundScheduler()

def cleanup_old_data():
    print("Running cleanup job...")
    cutoff_date = datetime.utcnow() - timedelta(days=30)
    result = db.campaigns.delete_many({
        "status": "completed",
        "created_at": {"$lt": cutoff_date}
    })
    print(f"Deleted {result.deleted_count} old campaigns")

def send_daily_report():
    print("Sending daily report...")
    # Report logic here

# Schedule jobs
scheduler.add_job(
    func=cleanup_old_data,
    trigger=IntervalTrigger(hours=24),
    id='cleanup_job',
    name='Cleanup old data',
    replace_existing=True
)

scheduler.add_job(
    func=send_daily_report,
    trigger='cron',
    hour=9,
    minute=0,
    id='daily_report',
    name='Daily report'
)

scheduler.start()
atexit.register(lambda: scheduler.shutdown())
```

### Node.js (node-cron + Bull)
```javascript
const cron = require('node-cron');
const Queue = require('bull');
const mongoose = require('mongoose');

// Using node-cron for scheduled tasks
cron.schedule('0 */24 * * *', async () => {
  console.log('Running cleanup job...');
  
  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - 30);
  
  const result = await Campaign.deleteMany({
    status: 'completed',
    created_at: { $lt: cutoffDate }
  });
  
  console.log(`Deleted ${result.deletedCount} old campaigns`);
});

cron.schedule('0 9 * * *', async () => {
  console.log('Sending daily report...');
  // Report logic here
});

// Using Bull for job queue (requires Redis)
const emailQueue = new Queue('email-processing', {
  redis: {
    host: process.env.REDIS_HOST || 'localhost',
    port: process.env.REDIS_PORT || 6379
  }
});

// Add job to queue
async function queueCampaignEmails(campaignId) {
  await emailQueue.add('send-campaign', {
    campaignId,
    createdAt: new Date()
  }, {
    attempts: 3,
    backoff: {
      type: 'exponential',
      delay: 2000
    }
  });
}

// Process jobs
emailQueue.process('send-campaign', async (job) => {
  console.log(`Processing campaign: ${job.data.campaignId}`);
  
  // Send emails logic here
  
  return { success: true, emailsSent: 100 };
});

// Job event handlers
emailQueue.on('completed', (job, result) => {
  console.log(`Job ${job.id} completed:`, result);
});

emailQueue.on('failed', (job, err) => {
  console.error(`Job ${job.id} failed:`, err);
});

// Graceful shutdown
process.on('SIGTERM', async () => {
  await emailQueue.close();
  process.exit(0);
});
```

---

## File Uploads

### Python (FastAPI)
```python
from fastapi import File, UploadFile
import shutil
from pathlib import Path

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        file_path = UPLOAD_DIR / file.filename
        
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        return {
            "filename": file.filename,
            "size": file_path.stat().st_size,
            "path": str(file_path)
        }
    finally:
        file.file.close()

@router.post("/upload-multiple")
async def upload_multiple(files: List[UploadFile] = File(...)):
    uploaded_files = []
    
    for file in files:
        file_path = UPLOAD_DIR / file.filename
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        uploaded_files.append({
            "filename": file.filename,
            "size": file_path.stat().st_size
        })
    
    return {"files": uploaded_files}
```

### Node.js (Express + Multer)
```javascript
const multer = require('multer');
const path = require('path');
const fs = require('fs');

const UPLOAD_DIR = 'uploads';

// Ensure upload directory exists
if (!fs.existsSync(UPLOAD_DIR)) {
  fs.mkdirSync(UPLOAD_DIR, { recursive: true });
}

// Configure storage
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    cb(null, UPLOAD_DIR);
  },
  filename: (req, file, cb) => {
    const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
    cb(null, uniqueSuffix + '-' + file.originalname);
  }
});

// File filter
const fileFilter = (req, file, cb) => {
  const allowedTypes = ['image/jpeg', 'image/png', 'application/pdf'];
  
  if (allowedTypes.includes(file.mimetype)) {
    cb(null, true);
  } else {
    cb(new Error('Invalid file type'), false);
  }
};

const upload = multer({
  storage: storage,
  fileFilter: fileFilter,
  limits: {
    fileSize: 5 * 1024 * 1024 // 5MB
  }
});

// Single file upload
router.post('/upload', upload.single('file'), (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ detail: 'No file uploaded' });
    }
    
    res.json({
      filename: req.file.originalname,
      size: req.file.size,
      path: req.file.path,
      mimetype: req.file.mimetype
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Multiple files upload
router.post('/upload-multiple', upload.array('files', 10), (req, res) => {
  try {
    if (!req.files || req.files.length === 0) {
      return res.status(400).json({ detail: 'No files uploaded' });
    }
    
    const uploadedFiles = req.files.map(file => ({
      filename: file.originalname,
      size: file.size,
      path: file.path,
      mimetype: file.mimetype
    }));
    
    res.json({ files: uploadedFiles });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Error handling
app.use((error, req, res, next) => {
  if (error instanceof multer.MulterError) {
    if (error.code === 'LIMIT_FILE_SIZE') {
      return res.status(400).json({ detail: 'File too large' });
    }
    return res.status(400).json({ detail: error.message });
  }
  next(error);
});
```

---

## Environment Variables

### Python (.env)
```python
# .env file
MONGO_URI=mongodb://localhost:27017/campaign_platform
SECRET_KEY=your-secret-key-here
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
REDIS_HOST=localhost
REDIS_PORT=6379
```

```python
# config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    mongo_uri: str
    secret_key: str
    openai_api_key: str
    gemini_api_key: str
    redis_host: str = "localhost"
    redis_port: int = 6379
    
    class Config:
        env_file = ".env"

settings = Settings()
```

### Node.js (.env)
```javascript
// .env file (same format)
MONGO_URI=mongodb://localhost:27017/campaign_platform
SECRET_KEY=your-secret-key-here
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
REDIS_HOST=localhost
REDIS_PORT=6379
```

```javascript
// config.js
require('dotenv').config();

const config = {
  mongoUri: process.env.MONGO_URI,
  secretKey: process.env.SECRET_KEY,
  openaiApiKey: process.env.OPENAI_API_KEY,
  geminiApiKey: process.env.GEMINI_API_KEY,
  redisHost: process.env.REDIS_HOST || 'localhost',
  redisPort: parseInt(process.env.REDIS_PORT) || 6379,
  port: parseInt(process.env.PORT) || 8000,
  nodeEnv: process.env.NODE_ENV || 'development'
};

// Validate required variables
const required = ['mongoUri', 'secretKey'];
for (const key of required) {
  if (!config[key]) {
    throw new Error(`Missing required environment variable: ${key}`);
  }
}

module.exports = config;
```

---

## Summary

This guide shows that:
1. ✅ Most Python patterns have direct Node.js equivalents
2. ✅ MongoDB works identically with both
3. ✅ API structure translates well
4. ✅ Authentication, file uploads, jobs all have mature Node.js solutions

The main differences are:
- Python uses `async/await` with `asyncio`, Node.js uses native Promises
- Python has Pydantic for validation, Node.js uses Mongoose schemas or Zod
- Python uses APScheduler, Node.js uses node-cron or Bull
- Syntax differences but similar concepts

**Next Steps:**
1. Review these examples
2. Try converting one small module
3. Test with your existing MongoDB database
4. Expand gradually
