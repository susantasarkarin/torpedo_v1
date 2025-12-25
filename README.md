# Campaign Platform (Torpedo)

A comprehensive SaaS platform for managing business operations, finance, sales, survey panel management, and marketing campaigns. Built with React (Vite) frontend and FastAPI backend with MongoDB.

## 🚀 Features

### Finance Module
- **Customers Management** - Full CRUD with GST treatment, billing/shipping addresses, validation
- **Vendors Management** - Supplier management with bank details, IFSC validation
- **Invoices** - Create, edit, export invoices with line items, discounts, tax calculations
- **Bills** - Track vendor bills and payables
- **Purchase Orders** - Manage POs with vendor integration
- **Expenses** - Track business expenses with auto-categorization
- **Payments** - Record payments received and made
- **Estimates** - Create and manage project estimates
- **Reports** - Financial dashboards and analytics
- **Import/Export CSV** - Bulk import/export for all finance entities

### Operations Module
- **Projects** - Project management with mandatory field validation
- **Clients** - Client relationship management
- **Survey Pool** - CPX Research integration with:
  - Auto-fetching live surveys from CPX API
  - Filtering by LOI, Payout, Country
  - Random survey allocation to respondents
  - Entry link generation with secure hash
- **Traffic Management** - Traffic flow with SFWID tracking:
  - Unique SFWID (Survey Field Work ID) for each respondent
  - Random survey allocation from live pool
  - Vendor redirect handling with proper respondent ID mapping
  - Complete/Terminate/QuotaFull callback processing

### Sales Module
- **Campaigns** - Email campaign management
- **Contacts** - Contact list management with statistics
- **Leads** - Lead tracking and management
- **RFQ** - Request for quotation handling
- **Templates** - Email template management

### CPX Research Integration
- **Survey Fetching** - Automatic periodic fetching of CPX surveys
- **Survey Allocation** - Random allocation to respondents from survey pool
- **Callback Handling** - Complete/Terminate redirect processing
- **Vendor Integration** - Proper redirect URL construction with respondent IDs

## 🛠️ Tech Stack

### Frontend
- **React 18** with Vite
- **React Router** for navigation
- **Tailwind CSS** for styling
- **Lucide React** for icons

### Backend
- **FastAPI** (Python)
- **MongoDB** with PyMongo
- **Uvicorn** ASGI server
- **APScheduler** for scheduled tasks (CPX refresh)

## 📦 Installation

### Prerequisites
- Node.js 18+
- Python 3.9+
- MongoDB

### Frontend Setup

```bash
cd Campaign_platform
npm install
npm run dev
```

Frontend runs on: `http://localhost:5173`

### Backend Setup

```bash
cd backend
pip install -r requirements.txt
```

Create a `.env` file:
```env
MONGO_URI=mongodb://localhost:27017
FRONTEND_URL=http://localhost:5173
API_BASE=http://localhost:8000

# CPX Research Configuration
CPX_APP_ID=your_cpx_app_id
CPX_EXT_USER_ID=your_ext_user_id
CPX_SECURE_HASH_KEY=your_secure_hash_key
CPX_API_TIMEOUT=30
CPX_FETCH_LIMIT=1000
```

Start the server:
```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Backend runs on: `http://localhost:8000`

## 📁 Project Structure

```
campaign_platform/
├── Campaign_platform/          # React Frontend
│   ├── src/
│   │   ├── components/        # Reusable UI components
│   │   ├── pages/             # Page components
│   │   │   ├── finance/       # Finance module pages
│   │   │   ├── operations/    # Operations module pages
│   │   │   │   ├── surveyPool/    # Survey pool management
│   │   │   │   └── TrafficManagement.jsx  # Traffic with SFWID
│   │   │   └── sales/         # Sales module pages
│   │   ├── hooks/             # Custom React hooks
│   │   ├── utils/             # Utility functions
│   │   └── styles/            # Global styles
│   └── public/                # Static assets
│
├── backend/                   # FastAPI Backend
│   ├── routers/
│   │   ├── finance.py        # Finance CRUD endpoints
│   │   ├── traffic.py        # Traffic management & CPX callbacks
│   │   ├── settings.py       # App settings management
│   │   └── gmail.py          # Gmail integration
│   ├── app/
│   │   ├── routers/
│   │   │   ├── cpx.py        # CPX Research endpoints
│   │   │   └── survey_allocation.py  # Survey allocation logic
│   │   ├── services/
│   │   │   ├── cpx_service.py         # CPX API integration
│   │   │   ├── traffic_service.py     # Traffic management
│   │   │   └── survey_allocation_service.py
│   │   └── models/           # Pydantic models
│   └── main.py               # FastAPI application entry
│
└── README.md
```

## 🔌 API Endpoints

### Finance Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/finance/finance/customers/` | List all customers |
| POST | `/finance/finance/customers/` | Create customer |
| GET | `/finance/finance/customers/export/csv` | Export customers to CSV |
| POST | `/finance/finance/customers/import/csv` | Import customers from CSV |
| GET | `/finance/finance/vendors/` | List all vendors |
| POST | `/finance/finance/vendors/` | Create vendor |
| GET | `/finance/finance/invoices/` | List all invoices |
| POST | `/finance/finance/invoices/` | Create invoice |
| GET | `/finance/finance/invoices/export/csv` | Export invoices to CSV |
| POST | `/finance/finance/invoices/import/csv` | Import invoices from CSV |
| GET | `/finance/finance/bills/` | List all bills |
| GET | `/finance/purchase-orders/` | List purchase orders |
| GET | `/finance/expenses/` | List expenses |
| GET | `/finance/payments/received/` | List payments received |
| GET | `/finance/payments/made/` | List payments made |
| GET | `/finance/dashboard/summary` | Dashboard KPIs |

### Traffic & Survey Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/store` | Store traffic record & allocate survey |
| GET | `/cpx-response` | CPX callback handler (complete/terminate) |
| GET | `/api/traffic/list` | List traffic records with SFWID |
| GET | `/api/traffic/stats` | Traffic statistics by status |
| DELETE | `/api/traffic/delete` | Delete traffic records |

### CPX Research Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/cpx/surveys` | Get CPX surveys with filters |
| POST | `/cpx/refresh` | Manual CPX survey refresh |
| GET | `/cpx/filter-settings` | Get survey filter settings |
| POST | `/cpx/filter-settings` | Save survey filter settings |

### Vendor Management Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/vendors/` | List all vendors |
| POST | `/vendors/` | Create vendor with redirect URLs |
| PUT | `/vendors/{id}` | Update vendor |
| DELETE | `/vendors/{id}` | Delete vendor |

## 🔄 Survey Flow Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Vendor    │────▶│  Torpedo    │────▶│    CPX      │
│   Server    │     │  Platform   │     │  Research   │
└─────────────┘     └─────────────┘     └─────────────┘
      │                   │                    │
      │  1. Send RID      │                    │
      │  (Respondent ID)  │                    │
      │──────────────────▶│                    │
      │                   │                    │
      │  2. Create SFWID  │                    │
      │  & Allocate Survey│                    │
      │                   │  3. Redirect with  │
      │                   │  SFWID as ext_user │
      │                   │───────────────────▶│
      │                   │                    │
      │                   │  4. Callback with  │
      │                   │  SFWID (complete/  │
      │                   │  terminate)        │
      │                   │◀───────────────────│
      │                   │                    │
      │  5. Redirect to   │                    │
      │  vendor with RID  │                    │
      │◀──────────────────│                    │
      │                   │                    │
```

### Key Concepts

- **SFWID (Survey Field Work ID)**: Unique MongoDB `_id` assigned to each traffic record
- **RID (Respondent ID)**: Original respondent identifier from the vendor
- **Random Allocation**: Surveys are randomly selected from the live pool
- **Vendor Redirect**: On callback, the original RID is appended to vendor's redirect URL

## 🔐 Validation

### Customer/Vendor Fields
- **Email**: Standard email format validation
- **Phone**: Indian mobile format (+91, 10 digits starting with 6-9)
- **GSTIN**: 15-character alphanumeric (required for registered businesses)
- **PAN**: 10-character format (AAAAA9999A)
- **IFSC**: 11-character bank code format

### GST Treatment Options
- Registered Business - Regular
- Registered Business - Composition
- Unregistered Business
- Consumer
- Overseas

## 📊 Import/Export

All finance modules support CSV import/export:

1. **Export**: Click "Export CSV" to download all records
2. **Import**: Click "Import CSV" to upload a CSV file

### CSV Format Example (Customers)
```csv
name,customer_type,email,phone,gst_treatment,gstin,billing_address_city,billing_address_state
Acme Corp,business,acme@example.com,+919876543210,registered_regular,27AABCU9603R1ZM,Mumbai,Maharashtra
```

## 🤝 Contributing

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Commit changes: `git commit -m "Add your feature"`
3. Push to branch: `git push origin feature/your-feature`
4. Open a Pull Request

## 📄 License

This project is proprietary software. All rights reserved.

## 👥 Team

Developed by the Torpedo Team.

---

## 📝 Changelog

### v2.0.0 (December 2024)
- ✨ Added CPX Research integration for survey fetching
- ✨ Implemented random survey allocation from live pool
- ✨ Added SFWID tracking in Traffic Management
- ✨ Fixed CPX callback redirect to properly route respondents back to vendors
- 🔧 Renamed "Record ID" to "SFWID" in UI
- 🔧 Display full SFWID instead of truncated version
- 🔧 Support for base64 encoded callback parameters
