# Deployment Directory

This folder contains deployment scripts and configuration templates for various environments.

## Structure

### `/scripts/`
Deployment automation scripts for different environments and workflows.

#### PowerShell Scripts
- `deploy.ps1` - Main deployment script
- `safe_release.ps1` - Commit only an explicit allowlist of files (prevents accidental `git add -A` releases)
- `deploy_localhost.ps1` - Deploy to localhost
- `deploy_ssh.ps1` - Deploy via SSH
- `deploy_to_vm.ps1` - Deploy to VM
- `deploy-to-vm.ps1` - Alternative VM deployment
- `deploy_vm.ps1` - Simplified VM deployment
- `sync-to-vm.ps1` - Sync files to VM
- `health_check.ps1` - System health check
- `install_dependencies.ps1` - Install required dependencies
- `setup_environment.ps1` - Environment setup
- `start_services.ps1` - Start all services
- `stop_services.ps1` - Stop all services

#### Shell Scripts
- `deploy.sh` - Main deployment script (Unix)
- `deploy_manual.sh` - Manual deployment steps
- `deploy_to_vm.sh` - VM deployment (Unix)
- `verify_deployment.sh` - Verify deployment success

#### Batch Scripts
- `deploy.bat` - Windows batch deployment

### `/configs/`
Configuration templates and examples for web servers and services.

- `nginx_campaign_platform.conf` - Nginx configuration for campaign platform
- `apache.conf.example` - Apache configuration example
- `.git-credentials.example` - Git credentials template

## Usage

### Quick Deployment to VM
```powershell
.\deploy\scripts\deploy_to_vm.ps1
```

### Safe Git Release (Recommended)
```powershell
.\deploy\scripts\safe_release.ps1 `
	-Message "Add LinkedIn opportunity dashboard updates" `
	-Include @("backend/linkedin_automation","backend/routers/linkedin.py","backend/routers/cold_outreach_router.py","Campaign_platform/src/pages/sales/campaign/Reports.jsx") `
	-Push
```

This script aborts if files are already staged and stages only the specified include paths, so broad dirty-workspace commits are avoided.

### Local Development
```powershell
.\deploy\scripts\deploy_localhost.ps1
.\deploy\scripts\start_services.ps1
```

### Health Check
```powershell
.\deploy\scripts\health_check.ps1
```

### Stop Services
```powershell
.\deploy\scripts\stop_services.ps1
```

## Configuration

Before deploying, ensure:
1. Environment variables are set (see `.env.example` in project root)
2. VM credentials are configured if deploying remotely
3. Web server configs are customized for your environment (see `/configs/`)

For detailed deployment instructions, see [docs/deployment/QUICK_DEPLOYMENT_GUIDE.md](../docs/deployment/QUICK_DEPLOYMENT_GUIDE.md).
