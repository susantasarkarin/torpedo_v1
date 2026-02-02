/**
 * EXAMPLE: Node.js/Express Backend for Campaign Platform
 * 
 * This is a minimal example showing how your Python FastAPI backend
 * can be converted to Node.js/Express
 * 
 * To run this example:
 * 1. npm init -y
 * 2. npm install express mongoose dotenv cors
 * 3. Create a .env file with MONGO_URI
 * 4. node nodejs-backend-example.js
 */

const express = require('express');
const mongoose = require('mongoose');
const cors = require('cors');
const dotenv = require('dotenv');

dotenv.config();

const app = express();
const PORT = process.env.PORT || 8000;

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// MongoDB Connection (equivalent to your database.py)
const connectDB = async () => {
  try {
    await mongoose.connect(process.env.MONGO_URI || 'mongodb://localhost:27017/campaign_platform');
    console.log('✅ MongoDB connected successfully');
  } catch (error) {
    console.error('❌ MongoDB connection error:', error);
    process.exit(1);
  }
};

// Campaign Schema (equivalent to Pydantic model)
const campaignSchema = new mongoose.Schema({
  name: { type: String, required: true },
  description: String,
  status: { 
    type: String, 
    enum: ['draft', 'active', 'paused', 'completed'],
    default: 'draft'
  },
  target_audience: [String],
  budget: Number,
  user_id: { type: mongoose.Schema.Types.ObjectId, required: true },
  created_at: { type: Date, default: Date.now },
  updated_at: { type: Date, default: Date.now }
});

const Campaign = mongoose.model('Campaign', campaignSchema);

// ==================== ROUTES ====================

// Health Check (like your FastAPI health endpoint)
app.get('/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    timestamp: new Date().toISOString(),
    service: 'campaign-platform-nodejs'
  });
});

// Get all campaigns
app.get('/api/campaigns', async (req, res) => {
  try {
    const { status, limit = 50, skip = 0 } = req.query;
    
    const query = {};
    if (status) query.status = status;
    
    const campaigns = await Campaign.find(query)
      .limit(parseInt(limit))
      .skip(parseInt(skip))
      .sort({ created_at: -1 });
    
    const total = await Campaign.countDocuments(query);
    
    res.json({
      campaigns,
      total,
      page: Math.floor(skip / limit) + 1
    });
  } catch (error) {
    console.error('Error:', error);
    res.status(500).json({ error: error.message });
  }
});

// Create campaign
app.post('/api/campaigns', async (req, res) => {
  try {
    const { name, description, target_audience, budget } = req.body;
    
    if (!name) {
      return res.status(422).json({ detail: 'Campaign name is required' });
    }
    
    const campaign = new Campaign({
      name,
      description,
      target_audience: target_audience || [],
      budget: budget || 0,
      user_id: new mongoose.Types.ObjectId(),
      status: 'draft'
    });
    
    await campaign.save();
    res.status(201).json(campaign);
  } catch (error) {
    console.error('Error:', error);
    res.status(500).json({ error: error.message });
  }
});

// Start server
const startServer = async () => {
  await connectDB();
  
  app.listen(PORT, () => {
    console.log(`🚀 Server running on http://localhost:${PORT}`);
    console.log(`📊 API: http://localhost:${PORT}/api/campaigns`);
    console.log(`💚 Health: http://localhost:${PORT}/health`);
  });
};

startServer();

module.exports = app;
