# Torpedo Campaign Platform

AI-powered cold outreach platform with lead management, survey integrations, and email automation.

## 📁 Project Structure

```
.
├── backend/              # FastAPI backend application
│   ├── app/             # Core application modules
│   ├── routers/         # API route handlers
│   ├── scripts/         # Backend utility scripts
│   └── ...
├── frontend/            # React frontend application
│   └── src/            # React components and pages
├── Campaign_platform/   # Alternative frontend build
├── docs/               # 📚 Documentation
│   ├── deployment/     # Deployment guides
│   ├── integrations/   # Integration docs (CINT, CPX)
│   └── email/         # Email system docs
├── scripts/           # 🛠️ Utility scripts by domain
│   ├── cint/         # CINT survey scripts
│   ├── entry_links/  # Entry link management
│   ├── surveys/      # Survey operations
│   ├── leads/        # Lead management
│   ├── db/           # Database utilities
│   ├── email/        # Email utilities
│   ├── admin/        # Admin scripts
│   └── diagnostics/  # Troubleshooting tools
├── deploy/           # 🚀 Deployment assets
│   ├── scripts/      # Deployment automation
│   └── configs/      # Server configuration templates
├── ai_outreach/      # AI outreach modules
├── gmail_automation/ # Gmail automation tools
├── models/          # Data models
├── vm_config/       # VM configuration
└── logs/           # Application logs

## 🚀 Quick Start

### 1. Environment Setup
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 2. Install Dependencies
```powershell
.\deploy\scripts\install_dependencies.ps1
```

### 3. Start Services
```powershell
.\deploy\scripts\start_services.ps1
```

### 4. Deploy to VM (Optional)
```powershell
.\deploy\scripts\deploy_to_vm.ps1
```

## 📖 Documentation

- **Deployment**: See [docs/deployment/](docs/deployment/)
- **CINT Integration**: See [docs/integrations/cint/](docs/integrations/cint/)
- **Email Setup**: See [docs/email/](docs/email/)

## 🛠️ Common Scripts

```bash
# Check CINT status
python scripts/cint/check_cint_status.py

# Test email system
python scripts/email/test_smtp.py

# Create admin user
python scripts/admin/create_admin_user.py

# Verify entry links
python scripts/entry_links/check_entry_links.py
```

## 🏗️ Architecture

- **Backend**: Python FastAPI with MongoDB
- **Frontend**: React with Vite
- **Integrations**: CINT, CPX survey platforms
- **Email**: SMTP with Gmail automation
- **Deployment**: PowerShell/Bash scripts for VM deployment

## 🔧 Development

### Backend
```bash
cd backend
source venv/bin/activate  # or venv\Scripts\activate on Windows
uvicorn main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## 📝 Notes

- All temporary files (tmpclaude-*, __pycache__) are now gitignored
- Utility scripts have been organized by domain under `/scripts/`
- Documentation is centralized under `/docs/`
- Deployment assets are under `/deploy/`

## 🤝 Contributing

When adding new scripts or documentation:
- Place utility scripts in appropriate `/scripts/` subdirectory
- Add documentation to relevant `/docs/` section
- Update respective README.md files

## 📄 License

[Your License Here]
