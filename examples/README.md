# Node.js Backend Examples

This directory contains working examples of how to convert the Campaign Platform's Python/FastAPI backend to Node.js/Express.

## Files

- **nodejs-backend-example.js** - A complete, runnable Express.js server showing how to:
  - Connect to MongoDB (same database as Python backend)
  - Define schemas (equivalent to Pydantic models)
  - Create REST API endpoints
  - Handle CRUD operations
  - Error handling

- **package.json** - Node.js dependencies needed to run the example

## Quick Start

1. **Install dependencies:**
   ```bash
   cd examples
   npm install
   ```

2. **Set up environment:**
   ```bash
   # Create .env file
   echo "MONGO_URI=mongodb://localhost:27017/campaign_platform" > .env
   echo "PORT=8000" >> .env
   ```

3. **Run the server:**
   ```bash
   npm start
   ```

   Or with auto-reload during development:
   ```bash
   npm run dev
   ```

4. **Test the endpoints:**
   ```bash
   # Health check
   curl http://localhost:8000/health

   # Create a campaign
   curl -X POST http://localhost:8000/api/campaigns \
     -H "Content-Type: application/json" \
     -d '{"name": "Test Campaign", "description": "A test campaign"}'

   # Get all campaigns
   curl http://localhost:8000/api/campaigns
   ```

## API Endpoints

The example implements these endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/campaigns` | List all campaigns |
| POST | `/api/campaigns` | Create new campaign |

## Comparison with Python Backend

### Python (FastAPI)
```python
@router.get("/campaigns")
async def get_campaigns():
    campaigns = db.campaigns.find()
    return list(campaigns)
```

### Node.js (Express)
```javascript
app.get('/api/campaigns', async (req, res) => {
  const campaigns = await Campaign.find();
  res.json(campaigns);
});
```

## Next Steps

1. Review the [Node.js Conversion Guide](../NODEJS_CONVERSION_GUIDE.md) for comprehensive information
2. Experiment with this example code
3. Add more endpoints as needed
4. Consider TypeScript for better type safety
5. Add authentication middleware
6. Implement background jobs

## Notes

- This example uses the **same MongoDB database** as your Python backend
- The API structure matches your FastAPI endpoints
- Error handling follows similar patterns
- Can run alongside Python backend during migration

## Questions?

Refer to the main [Node.js Conversion Guide](../NODEJS_CONVERSION_GUIDE.md) for detailed explanations.
