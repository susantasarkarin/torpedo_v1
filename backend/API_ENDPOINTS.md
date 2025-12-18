# API Endpoints Documentation

All APIs are served from your FastAPI backend running on port **8000** (default).

**Base URL:** `http://your-server-ip:8000` or `http://your-domain.com:8000`

---

## 📚 Automatic API Documentation

FastAPI automatically generates interactive API documentation:

- **Swagger UI:** `http://your-server-ip:8000/docs`
- **ReDoc:** `http://your-server-ip:8000/redoc`
- **OpenAPI Schema:** `http://your-server-ip:8000/openapi.json`

**Try it out:** Visit `/docs` to see all endpoints and test them directly in the browser!

---

## 🔐 Authentication Endpoints

### Login
```
POST /login/
Content-Type: application/json

Body:
{
  "username": "admin",
  "password": "password123"
}

Response:
{
  "message": "Login successful",
  "username": "admin",
  "session_id": "ImFkbWluIg...",
  "role": "admin"
}
```

### Logout
```
POST /logout/
Headers:
  Authorization: <session_id>
```

**Note:** Most endpoints require `Authorization` header with the session_id from login.

---

## 📊 Email Campaign APIs (Email Automation)

### Lists
- `POST /create-list/` - Create a new contact list
- `GET /lists/` - Get all lists (requires auth)
- `DELETE /delete-list/{list_id}` - Delete a list

### Contacts
- `POST /upload-csv/` - Upload contacts via CSV
- `GET /contacts/{list_identifier}` - Get contacts for a list

### Templates
- `POST /templates/` - Save an email template
- `GET /templates/` - Get all templates (requires auth)
- `PUT /templates/{template_id}` - Update a template
- `DELETE /templates/{template_id}` - Delete a template

### Send Emails
- `POST /send-emails/` - Send campaign emails

### Reports
- `GET /reports/` - Get campaign reports (requires auth)

### Tracking
- `GET /track/open?c={campaign_id}&e={email}` - Email open tracking pixel
- `GET /track/click?c={campaign_id}&e={email}&url={url}` - Click tracking redirect

---

## 👥 Operations APIs

### Clients
- `POST /clients/` - Create a client
- `GET /clients/` - Get all clients (requires auth)
- `PUT /clients/{client_id}` - Update a client
- `DELETE /clients/{client_id}` - Delete a client

### Vendors
- `POST /vendors/` - Create a vendor
- `GET /vendors/` - Get all vendors (requires auth)
- `PUT /vendors/{vendor_id}` - Update a vendor
- `DELETE /vendors/{vendor_id}` - Delete a vendor

### Projects
- `POST /projects/` - Create a project
- `GET /projects/` - Get all projects (requires auth)
- `PUT /projects/{project_id}` - Update a project
- `DELETE /projects/{project_id}` - Delete a project

---

## 🚦 Traffic Flow APIs (Survey Tracking)

These endpoints were converted from Flask to FastAPI and are now in `routers/traffic.py`.

### Store URL Parameters
```
POST /api/store
Content-Type: application/json

Body:
{
  "url_params": {...},
  "survey_id": "...",
  "other_data": "..."
}

Response:
{
  "id": "507f1f77bcf86cd799439011"
}
```

### Survey Callbacks (GET - redirects)
- `GET /surveycomplete?rid={record_id}` - Survey completed callback
- `GET /surveyterminate?rid={record_id}` - Survey terminated callback
- `GET /surveyquotafull?rid={record_id}` - Survey quota full callback

### Health Check
```
GET /api/health

Response:
{
  "status": "ok",
  "service": "traffic-flow"
}
```

---

## 📝 Example Usage

### Using cURL

```bash
# Login
curl -X POST "http://localhost:8000/login/" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password123"}'

# Get lists (with auth)
curl -X GET "http://localhost:8000/lists/" \
  -H "Authorization: YOUR_SESSION_ID"

# Store URL parameters
curl -X POST "http://localhost:8000/api/store" \
  -H "Content-Type: application/json" \
  -d '{"url_params": {"id": "123"}, "survey_id": "test"}'
```

### Using JavaScript/Fetch

```javascript
// Login
const response = await fetch('http://localhost:8000/login/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'admin', password: 'password123' })
});
const { session_id } = await response.json();

// Get lists (with auth)
const listsResponse = await fetch('http://localhost:8000/lists/', {
  headers: {
    'Authorization': session_id,
    'Content-Type': 'application/json'
  }
});
const { lists } = await listsResponse.json();

// Store URL parameters (traffic flow)
const storeResponse = await fetch('http://localhost:8000/api/store', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    url_params: { id: '123' },
    survey_id: 'test'
  })
});
const { id } = await storeResponse.json();
```

### Using Python Requests

```python
import requests

BASE_URL = "http://localhost:8000"

# Login
response = requests.post(f"{BASE_URL}/login/", json={
    "username": "admin",
    "password": "password123"
})
session_id = response.json()["session_id"]

# Get lists (with auth)
response = requests.get(
    f"{BASE_URL}/lists/",
    headers={"Authorization": session_id}
)
lists = response.json()["lists"]

# Store URL parameters
response = requests.post(
    f"{BASE_URL}/api/store",
    json={"url_params": {"id": "123"}, "survey_id": "test"}
)
record_id = response.json()["id"]
```

---

## 🔍 Quick Reference

### Base URLs by Environment

**Local Development:**
- `http://localhost:8000`
- `http://127.0.0.1:8000`

**Production:**
- `http://35.202.82.122:8000` (your current server)
- Or your custom domain: `https://api.yourdomain.com`

### Important Notes

1. **Session-based Auth:** Most endpoints require the `Authorization` header with session_id from `/login/`

2. **Traffic Flow APIs:** 
   - No authentication required (public endpoints)
   - Used for survey tracking callbacks
   - Store data in `traffic_flow_db` database

3. **Email Campaign APIs:**
   - Protected by session authentication
   - Store data in `email_automation` database

4. **CORS:** Configured in `main.py` - make sure your frontend origin is in `CORS_ORIGINS`

---

## 🚀 Best Way to Explore APIs

**Visit:** `http://your-server-ip:8000/docs`

FastAPI automatically provides:
- ✅ All endpoints listed
- ✅ Interactive testing interface
- ✅ Request/response examples
- ✅ Schema documentation
- ✅ Try it out feature (test directly from browser)

This is the easiest way to see and test all your APIs!

