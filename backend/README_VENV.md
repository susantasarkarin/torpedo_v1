# Python Virtual Environment Setup

This guide explains how to fix the "externally-managed-environment" error when installing Python packages on the server.

## Problem

On modern Debian/Ubuntu systems (Python 3.11+), the system Python is protected by PEP 668 to prevent breaking system packages. You'll see an error like:

```
error: externally-managed-environment
× This environment is externally managed
```

## Solution: Use a Virtual Environment

Always use a Python virtual environment for this project. Never install packages directly to the system Python.

## Quick Setup

### Option 1: Use the Setup Script (Recommended)

Run the provided setup script:

```bash
cd /var/www/campaign_platform/backend
chmod +x setup_venv.sh
./setup_venv.sh
```

This script will:
- Check if Python 3 and venv module are installed
- Create a virtual environment in `venv/` directory
- Install all dependencies from `requirements.txt`

### Option 2: Manual Setup

1. **Navigate to backend directory:**
   ```bash
   cd /var/www/campaign_platform/backend
   ```

2. **Create virtual environment:**
   ```bash
   python3 -m venv venv
   ```

3. **Install dependencies using venv's pip:**
   ```bash
   venv/bin/pip install --upgrade pip
   venv/bin/pip install -r requirements.txt
   ```

## Using the Virtual Environment

### Activate the venv (for interactive use):
```bash
source venv/bin/activate
# Now you can use 'pip' and 'python' directly
pip install some-package
python your_script.py
deactivate  # When done
```

### Use venv's Python directly (for scripts):
```bash
# No activation needed - use the full path
venv/bin/python your_script.py
venv/bin/pip install some-package
```

## Deployment Script

The `deploy.sh` script automatically:
- Creates the venv if it doesn't exist
- Uses `venv/bin/pip` to install packages (avoids the error)
- Uses `venv/bin/python` to run the application

## Systemd Service

If you're using systemd, make sure your service file uses the venv's Python:

```ini
[Service]
ExecStart=/var/www/campaign_platform/backend/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
WorkingDirectory=/var/www/campaign_platform/backend
```

## Troubleshooting

### Error: "python3-venv module not found"

On Debian/Ubuntu, install the required packages:
```bash
sudo apt update
sudo apt install python3-venv python3-full
```

### Error: "Virtual environment pip not found"

The venv might be corrupted. Recreate it:
```bash
rm -rf venv
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

### Still getting externally-managed-environment error?

Make sure you're using the venv's pip, not the system pip:
```bash
# ❌ Wrong - uses system pip
pip install package

# ✅ Correct - uses venv pip
venv/bin/pip install package

# ✅ Also correct (after activation)
source venv/bin/activate
pip install package
```

## Important Notes

- **Never use `pip install --break-system-packages`** - This can break your system
- **Always use the virtual environment** for this project
- The venv directory (`venv/`) is in `.gitignore` and should not be committed
- Each server/environment should have its own venv

