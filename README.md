# Campaign Platform

A comprehensive SaaS platform for managing business operations, finance, sales, and marketing campaigns. Built with React (Vite) frontend and FastAPI backend with MongoDB.

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
- **Survey Pool** - Survey management with filtering (LOI, Payout, Country)
- **Traffic Flow** - Traffic assignment and management

### Sales Module
- **Campaigns** - Email campaign management
- **Contacts** - Contact list management with statistics
- **Leads** - Lead tracking and management
- **RFQ** - Request for quotation handling
- **Templates** - Email template management

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

Create a `.env` file based on `.env.example`:
```env
MONGO_URI=mongodb://localhost:27017
```

Start the server:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
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
│   │   │   └── sales/         # Sales module pages
│   │   ├── hooks/             # Custom React hooks
│   │   ├── utils/             # Utility functions
│   │   └── styles/            # Global styles
│   └── public/                # Static assets
│
├── backend/                   # FastAPI Backend
│   ├── routers/
│   │   ├── finance.py        # Finance CRUD endpoints
│   │   └── traffic.py        # Traffic management
│   ├── app/
│   │   ├── routers/          # Additional routers
│   │   └── services/         # Business logic services
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
