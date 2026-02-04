# Campaign Platform

A comprehensive campaign automation and lead management platform.

## 🏗️ Architecture Transition Planning

**Considering modernization? We've created a comprehensive transition plan:**

- 📋 **[Complete Transition Plan](ARCHITECTURE_TRANSITION_PLAN.md)** - Detailed 60-page guide covering strategy, timeline, costs, and risks
- ⚡ **[Quick Reference](ARCHITECTURE_TRANSITION_QUICKREF.md)** - TL;DR summary with key decisions and options
- 📊 **[Visual Guide](ARCHITECTURE_TRANSITION_VISUAL.md)** - Diagrams, comparisons, and visual explanations

**Proposed Stack:** Node.js + MongoDB + React (app) | PHP (websites) | n8n (workflows)  
**Timeline:** 6-9 months | **Cost:** $230-250k | **Complexity Reduction:** 35-40%

See the documents above for detailed analysis, three migration options, and recommendations.

## 🤖 Agent Tools

### 🔍 Can't Find Your Agent Work?

If you completed work using GitHub Copilot or other AI agents and can't locate it on the VM:

**Quick Solution:**
```bash
./scripts/track_agent_work.sh
```

**Read the guides:**
- 📖 [Agent Work Location Guide](AGENT_WORK_LOCATION_GUIDE.md) - Quick reference
- 📋 [Agent Work Log](AGENT_WORK_LOG.md) - All agent sessions
- 📚 [Detailed Tracking Guide](.github/COPILOT_AGENTS_README.md) - Complete documentation

### 🚀 Need to Merge and Deploy?

Automated merge and deployment to VM:

**Quick Merge & Deploy:**
```bash
./scripts/merge_and_deploy_agent.sh <branch-name>
```

**Examples:**
```bash
# Standard merge and deploy
./scripts/merge_and_deploy_agent.sh copilot/feature-branch

# Quick mode (auto-confirm)
./scripts/merge_and_deploy_agent.sh copilot/feature-branch -y

# Preview mode (dry-run)
./scripts/merge_and_deploy_agent.sh copilot/feature-branch --dry-run
```

**Read the guide:**
- 📚 [Merge and Deploy Agent Guide](MERGE_DEPLOY_AGENT.md) - Complete documentation

## Quick Start

### For Development

1. **Clone the repository:**
   ```bash
   git clone https://github.com/sristi3227/campaign_platform.git
   cd campaign_platform
   ```

2. **Install dependencies:**
   ```bash
   # Backend
   pip install -r requirements.txt
   
   # Frontend
   cd Campaign_platform
   npm install
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. **Run the application:**
   ```bash
   # Backend
   cd backend
   uvicorn main:app --reload
   
   # Frontend
   cd Campaign_platform
   npm start
   ```

### For Deployment

Use the deployment script:
```bash
./deploy.sh                # Deploy everything
./deploy.sh --frontend-only  # Deploy frontend only
./deploy.sh --backend-only   # Deploy backend only
```

## Project Structure

```
campaign_platform/
├── backend/               # Python/FastAPI backend
│   ├── agents/           # AI agent implementations
│   ├── routers/          # API routes
│   └── services/         # Business logic
├── Campaign_platform/    # React frontend
├── scripts/              # Helper scripts
│   └── track_agent_work.sh  # Agent work tracking
├── .github/              # GitHub configuration
│   └── COPILOT_AGENTS_README.md  # Agent tracking guide
├── AGENT_WORK_LOG.md    # Agent work session log
└── AGENT_WORK_LOCATION_GUIDE.md  # Quick reference
```

## Key Features

- 🤖 **AI-Powered Lead Management** - Automated lead classification and enrichment
- 📧 **Email Campaign Automation** - Personalized outreach with follow-up sequences
- 📊 **Survey Integration** - CPX Research and Cint platform integration
- 🎯 **Traffic Management** - Advanced traffic allocation and routing
- 📈 **Analytics & Reporting** - Comprehensive campaign metrics
- 🔒 **Security** - Secure authentication and data protection

## Documentation

- [Campaign Automation Docs](CAMPAIGN_AUTOMATION_DOCS.md)
- [Quick Start Guide](QUICK_START.md)
- [Implementation Summary](IMPLEMENTATION_SUMMARY.md)
- [Security Summary](SECURITY_SUMMARY.md)
- [Survey Pool Fix](SURVEY_POOL_FIX_SUMMARY.md)

## Agent Work Tracking

This repository includes a comprehensive system for tracking AI agent work:

### Tools Available:
- **Tracking Script:** `./scripts/track_agent_work.sh`
  - View recent agent work
  - Check file changes
  - See commit history
  - Multiple viewing options (--today, --week, --files, --stats)

### Usage Examples:
```bash
# View all recent agent work
./scripts/track_agent_work.sh

# View today's work only
./scripts/track_agent_work.sh --today

# View with detailed file changes
./scripts/track_agent_work.sh --files

# View statistics
./scripts/track_agent_work.sh --stats
```

### Best Practices:
1. Always update `AGENT_WORK_LOG.md` after agent sessions
2. Use descriptive commit messages mentioning the agent
3. Push changes immediately after completion
4. Use branch naming: `copilot/*`, `agent/*`, `ai/*`

## Common Tasks

### Tracking Agent Work
```bash
# Find what an agent did
./scripts/track_agent_work.sh

# Check work log
cat AGENT_WORK_LOG.md
```

### Deploying Changes
```bash
# Full deployment
./deploy.sh

# Check deployment status
cat /var/www/campaign_platform/cron-deploy.log
```

### Running Tests
```bash
# Backend tests
cd backend
python -m pytest

# Frontend tests
cd Campaign_platform
npm test
```

### Database Management
```bash
# Setup MongoDB
python setup_mongodb.py

# Check database status
python check_correct_db.py
```

## Configuration

Key configuration files:
- `.env` - Environment variables
- `backend/config.py` - Backend configuration
- `nginx_campaign_platform.conf` - Nginx configuration
- `vm_settings.json` - VM settings

## Support

For issues or questions:
1. Check the [documentation](#documentation)
2. Review the [Agent Work Tracking](#agent-work-tracking) system
3. Run the tracking script: `./scripts/track_agent_work.sh`
4. Check the work log: `cat AGENT_WORK_LOG.md`

## License

Copyright © 2026 Cogentix Research Pvt Ltd

---

**Last Updated:** 2026-01-27  
**Repository:** [sristi3227/campaign_platform](https://github.com/sristi3227/campaign_platform)
