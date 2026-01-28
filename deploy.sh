#!/bin/bash

# ============================================================================
# AI Cold Outreach Platform - Deployment Script (Linux/macOS Bash)
# ============================================================================
# This script automates the entire deployment process for the campaign platform
# including dependency installation, environment setup, and service startup.
#
# Usage: ./deploy.sh [options]
# Options:
#   --frontend-only    Deploy only frontend
#   --backend-only     Deploy only backend
#   --no-pull          Skip git pull
#   --no-confirm       Skip confirmation prompts
#   --force            Force deployment even if working directory is dirty
#   --install-deps     Install/update all dependencies
#   --setup-env        Run environment setup
#
# ============================================================================

set -e  # Exit on error

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Script is in the project root (campaign_platform/)
# Check if .git exists in current dir, otherwise try parent (for flexibility)
if [ -d "$SCRIPT_DIR/.git" ]; then
    PROJECT_DIR="$SCRIPT_DIR"
else
    # Try parent directory (in case script is moved)
    PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

# Log file configuration (set up early)
LOG_FILE="/var/www/campaign_platform/cron-deploy.log"
# Fallback to local log file if /var/www doesn't exist (for local testing)
if [ ! -d "/var/www/campaign_platform" ]; then
    LOG_FILE="$SCRIPT_DIR/cron-deploy.log"
fi

# Initialize log file - delete old log and add header
init_log_file() {
    # Delete old log file if it exists
    if [ -f "$LOG_FILE" ]; then
        rm -f "$LOG_FILE"
    fi
    
    # Create log directory if it doesn't exist
    LOG_DIR=$(dirname "$LOG_FILE")
    if [ ! -d "$LOG_DIR" ]; then
        mkdir -p "$LOG_DIR" 2>/dev/null || true
    fi
    
    # Write initial header to log file
    echo "================================================" >> "$LOG_FILE"
    echo "Deployment Log Started: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
    echo "================================================" >> "$LOG_FILE"
    echo "" >> "$LOG_FILE"
}

# Get timestamp for logging
get_timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

# Log function that writes to both console and file
log_message() {
    local message="$1"
    local timestamp=$(get_timestamp)
    # Strip ANSI color codes for file logging
    local clean_message=$(echo -e "$message" | sed 's/\x1b\[[0-9;]*m//g')
    local log_entry="[${timestamp}] ${clean_message}"
    
    # Write to console (with colors preserved)
    echo -e "$message"
    
    # Write to log file (only if log file is initialized)
    if [ -f "$LOG_FILE" ] || [ -d "$(dirname "$LOG_FILE")" ]; then
        echo "$log_entry" >> "$LOG_FILE" 2>/dev/null || true
    fi
}

# Initialize log file immediately
init_log_file

# Load git credentials if .git-credentials file exists
if [ -f "$SCRIPT_DIR/.git-credentials" ]; then
    source "$SCRIPT_DIR/.git-credentials"
    log_message "Loaded git credentials from .git-credentials"
fi

# Configuration
FRONTEND_DIR="$SCRIPT_DIR/Campaign_platform"
FRONTEND_DIST="$FRONTEND_DIR/dist"
FRONTEND_WEB_ROOT="/var/www/html"  # Change this to your web server root
FRONTEND_SERVICE_NAME="campaign-frontend"  # systemd service name (if using systemd for web server)
BACKEND_DIR="$SCRIPT_DIR/backend"
BACKEND_VENV="$BACKEND_DIR/venv"
BACKEND_SERVICE_NAME="campaign-backend"  # systemd service name (if using systemd)
USE_SYSTEMD=false  # Set to true if using systemd service
USE_APACHE=false  # Set to true if using Apache
USE_NGINX=false  # Set to true if using Nginx
DEPLOY_FRONTEND=true
DEPLOY_BACKEND=true
SKIP_PULL=false
SKIP_CONFIRM=false
FORCE_DEPLOY=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --frontend-only)
            DEPLOY_FRONTEND=true
            DEPLOY_BACKEND=false
            shift
            ;;
        --backend-only)
            DEPLOY_FRONTEND=false
            DEPLOY_BACKEND=true
            shift
            ;;
        --no-pull)
            SKIP_PULL=true
            shift
            ;;
        --no-confirm)
            SKIP_CONFIRM=true
            shift
            ;;
        --force)
            FORCE_DEPLOY=true
            shift
            ;;
        *)
            print_error "Unknown option: $1"
            log_message "Usage: ./deploy.sh [--frontend-only|--backend-only] [--no-pull] [--no-confirm] [--force]"
            exit 1
            ;;
    esac
done

# Functions
print_success() {
    local message="${GREEN}✅ $1${NC}"
    log_message "$message"
}

print_info() {
    local message="${BLUE}ℹ️  $1${NC}"
    log_message "$message"
}

print_warning() {
    local message="${YELLOW}⚠️  $1${NC}"
    log_message "$message"
}

print_error() {
    local message="${RED}❌ $1${NC}"
    log_message "$message"
}

print_step() {
    local message="$1"
    log_message ""
    log_message "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    log_message "${BLUE}  ${message}${NC}"
    log_message "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Detect web server
detect_web_server() {
    if command -v systemctl > /dev/null 2>&1; then
        if systemctl list-units --type=service --all 2>/dev/null | grep -q "apache2.service\|httpd.service"; then
            USE_APACHE=true
            print_info "Detected Apache web server"
        elif systemctl list-units --type=service --all 2>/dev/null | grep -q "nginx.service"; then
            USE_NGINX=true
            print_info "Detected Nginx web server"
        fi
    elif command -v apache2 > /dev/null 2>&1 || command -v httpd > /dev/null 2>&1; then
        USE_APACHE=true
        print_info "Detected Apache web server"
    elif command -v nginx > /dev/null 2>&1; then
        USE_NGINX=true
        print_info "Detected Nginx web server"
    else
        print_warning "No web server detected. Will only build frontend, not deploy to web root."
    fi
}

# Check git status
check_git_status() {
    cd "$PROJECT_DIR"
    
    if [ ! -d .git ]; then
        print_warning "Not a git repository. Skipping git operations."
        SKIP_PULL=true
        return
    fi
    
    # Check for uncommitted changes
    if [ -n "$(git status --porcelain)" ] && [ "$FORCE_DEPLOY" = false ]; then
        print_warning "You have uncommitted changes:"
        git status --short
        echo ""
        read -p "Continue anyway? (y/N): " confirm
        if [[ ! $confirm =~ ^[Yy]$ ]]; then
            print_info "Deployment cancelled."
            exit 0
        fi
    fi
    
    # Check if we're on a branch
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
    print_info "Current branch: $CURRENT_BRANCH"
}

# Configure git credentials
setup_git_credentials() {
    cd "$PROJECT_DIR"
    
    if [ ! -d .git ]; then
        return
    fi
    
    # Check if credentials are provided via environment variables
    if [ -n "$GIT_USERNAME" ] && [ -n "$GIT_PASSWORD" ]; then
        print_info "Configuring git credentials from environment..."
        # Configure git to use credential helper
        git config --local credential.helper store
        # Set up credential in URL format for this session
        GIT_URL=$(git remote get-url origin 2>/dev/null || echo "")
        if [ -n "$GIT_URL" ]; then
            # Replace URL with credentials embedded (for HTTPS)
            if echo "$GIT_URL" | grep -q "^https://"; then
                # Extract repo path
                REPO_PATH=$(echo "$GIT_URL" | sed 's|https://||' | sed 's|.*@||' | sed 's|.*github.com/||' | sed 's|.*gitlab.com/||')
                if [ -n "$REPO_PATH" ]; then
                    # Set remote with embedded credentials
                    git remote set-url origin "https://${GIT_USERNAME}:${GIT_PASSWORD}@github.com/${REPO_PATH}" 2>/dev/null || \
                    git remote set-url origin "https://${GIT_USERNAME}:${GIT_PASSWORD}@gitlab.com/${REPO_PATH}" 2>/dev/null || true
                fi
            fi
        fi
    else
        # Try to use git credential helper if already configured
        if git config --get credential.helper > /dev/null 2>&1; then
            print_info "Using existing git credential helper"
        else
            # Set up credential helper to cache credentials
            git config --local credential.helper 'cache --timeout=3600' 2>/dev/null || true
        fi
    fi
}

# Git pull
git_pull() {
    if [ "$SKIP_PULL" = true ]; then
        print_info "Skipping git pull (--no-pull flag set)"
        return
    fi
    
    print_step "Step 1: Pulling Latest Code"
    
    cd "$PROJECT_DIR"
    
    if [ ! -d .git ]; then
        print_warning "Not a git repository. Skipping git pull."
        return
    fi
    
    # Setup git credentials before pulling
    setup_git_credentials
    
    print_info "Fetching latest changes..."
    git fetch origin
    
    # Check if there are updates
    LOCAL=$(git rev-parse @)
    REMOTE=$(git rev-parse @{u} 2>/dev/null || echo "")
    
    if [ -z "$REMOTE" ]; then
        print_warning "No upstream branch set. Skipping pull."
        return
    fi
    
    if [ "$LOCAL" = "$REMOTE" ]; then
        print_success "Already up to date with remote"
    else
        print_info "Pulling changes from remote..."
        git pull origin "$CURRENT_BRANCH"
        print_success "Code updated successfully"
    fi
}

# Check Node.js and npm
check_node() {
    if ! command -v node > /dev/null 2>&1; then
        print_error "Node.js is not installed. Please install Node.js 20+"
        exit 1
    fi
    
    NODE_VERSION=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
    if [ "$NODE_VERSION" -lt 20 ]; then
        print_error "Node.js version 20+ is required. Current version: $(node --version)"
        exit 1
    fi
    
    if ! command -v npm > /dev/null 2>&1; then
        print_error "npm is not installed. Please install npm"
        exit 1
    fi
    
    print_info "Node.js version: $(node --version)"
    print_info "npm version: $(npm --version)"
}

# Build frontend (npm build)
build_frontend() {
    print_step "Step 2: Building Frontend"
    
    cd "$FRONTEND_DIR"
    
    # Check Node.js
    check_node
    
    # Install/update dependencies
    print_info "Installing/updating npm dependencies..."
    if npm install --legacy-peer-deps; then
        print_success "Dependencies installed"
    else
        print_error "Failed to install dependencies"
        exit 1
    fi
    
    # Build the application
    print_info "Building frontend (this may take a few minutes)..."
    if npm run build; then
        print_success "Frontend build completed"
        
        # Check if dist directory exists
        if [ ! -d "$FRONTEND_DIST" ]; then
            print_error "Build directory not found: $FRONTEND_DIST"
            exit 1
        fi
        
        print_info "Build output: $FRONTEND_DIST"
    else
        print_error "Frontend build failed"
        exit 1
    fi
}

# Deploy frontend to web server
deploy_frontend() {
    print_step "Step 3: Deploying Frontend to Web Server"
    
    if [ ! -d "$FRONTEND_DIST" ]; then
        print_error "Build directory not found: $FRONTEND_DIST"
        print_info "Run build first: ./deploy.sh --frontend-only"
        exit 1
    fi
    
    # Copy files to web root
    if [ "$USE_APACHE" = true ] || [ "$USE_NGINX" = true ]; then
        print_info "Copying files to web root: $FRONTEND_WEB_ROOT"
        
        # Create web root if it doesn't exist
        if [ ! -d "$FRONTEND_WEB_ROOT" ]; then
            print_info "Creating web root directory..."
            sudo mkdir -p "$FRONTEND_WEB_ROOT"
        fi
        
        # Backup existing files (optional)
        if [ -d "$FRONTEND_WEB_ROOT" ] && [ "$(ls -A $FRONTEND_WEB_ROOT 2>/dev/null)" ]; then
            BACKUP_DIR="$(dirname "$FRONTEND_WEB_ROOT")/html_backup"
            print_info "Backing up existing files to: $BACKUP_DIR"
            sudo cp -r "$FRONTEND_WEB_ROOT" "$BACKUP_DIR" 2>/dev/null || true
        fi
        
        # Copy new files
        print_info "Copying build files..."
        sudo rm -rf "${FRONTEND_WEB_ROOT}"/* 2>/dev/null || true
        sudo cp -r "${FRONTEND_DIST}"/* "$FRONTEND_WEB_ROOT"/
        
        # Set proper permissions
        sudo chown -R www-data:www-data "$FRONTEND_WEB_ROOT" 2>/dev/null || \
        sudo chown -R apache:apache "$FRONTEND_WEB_ROOT" 2>/dev/null || \
        sudo chown -R nginx:nginx "$FRONTEND_WEB_ROOT" 2>/dev/null || true
        
        print_success "Files copied to web root"
        
        # Restart web server if using systemd
        if [ "$USE_APACHE" = true ]; then
            if command -v systemctl > /dev/null 2>&1; then
                print_info "Reloading Apache..."
                sudo systemctl reload apache2 2>/dev/null || sudo systemctl reload httpd 2>/dev/null || true
            fi
        elif [ "$USE_NGINX" = true ]; then
            if command -v systemctl > /dev/null 2>&1; then
                print_info "Reloading Nginx..."
                sudo systemctl reload nginx 2>/dev/null || true
            fi
        fi
        
        print_success "Frontend deployed successfully"
    else
        print_warning "No web server detected. Build files are in: $FRONTEND_DIST"
        print_info "Manually copy files to your web server root"
    fi
}

# Build backend (Python - install dependencies)
build_backend() {
    print_step "Step 2: Setting Up Backend"
    
    cd "$BACKEND_DIR"
    
    # Check Python
    if ! command -v python3 > /dev/null 2>&1; then
        print_error "Python 3 is not installed. Please install Python 3.10+"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
    print_info "Python version: $(python3 --version)"
    
    # Check if virtual environment exists
    if [ ! -d "$BACKEND_VENV" ]; then
        print_info "Creating Python virtual environment..."
        python3 -m venv "$BACKEND_VENV"
        print_success "Virtual environment created"
    fi
    
    # Use venv's pip directly (more reliable than activation)
    VENV_PIP="$BACKEND_VENV/bin/pip"
    VENV_PYTHON="$BACKEND_VENV/bin/python"
    
    if [ ! -f "$VENV_PIP" ]; then
        print_error "Virtual environment pip not found. Recreating venv..."
        rm -rf "$BACKEND_VENV"
        python3 -m venv "$BACKEND_VENV"
        VENV_PIP="$BACKEND_VENV/bin/pip"
        VENV_PYTHON="$BACKEND_VENV/bin/python"
    fi
    
    # Install/update dependencies using venv's pip directly
    print_info "Installing/updating Python dependencies..."
    
    if "$VENV_PIP" install -q --upgrade pip && "$VENV_PIP" install -q -r requirements.txt; then
        print_success "Backend dependencies installed"
    else
        print_error "Backend dependency installation failed"
        exit 1
    fi
}

# Check if backend uses systemd
check_backend_service() {
    # Check if using systemd (Linux only)
    if command -v systemctl > /dev/null 2>&1; then
        if systemctl list-units --type=service --all 2>/dev/null | grep -q "$BACKEND_SERVICE_NAME.service"; then
            USE_SYSTEMD=true
            print_info "Detected systemd service: $BACKEND_SERVICE_NAME"
        fi
    fi
}

# Restart backend (Python service)
restart_backend() {
    print_step "Step 3: Restarting Backend"
    
    cd "$BACKEND_DIR"
    
    # Check if using systemd
    check_backend_service
    
    if [ "$USE_SYSTEMD" = true ]; then
        # Restart using systemd
        print_info "Restarting backend service (systemd)..."
        if sudo systemctl restart "$BACKEND_SERVICE_NAME"; then
            sleep 2
            if sudo systemctl is-active --quiet "$BACKEND_SERVICE_NAME"; then
                print_success "Backend service restarted successfully"
                print_success "Backend is running at http://localhost:9944"
            else
                print_error "Backend service failed to start. Check logs with: sudo journalctl -u $BACKEND_SERVICE_NAME -f"
                exit 1
            fi
        else
            print_error "Failed to restart backend service"
            exit 1
        fi
    else
        # Manual restart - find and kill existing process, then start new one
        print_info "Stopping existing backend processes..."
        
        # Find processes running uvicorn on port 8000 or 9944
        PIDS=$(lsof -ti:8000,9944 2>/dev/null || true)
        if [ -n "$PIDS" ]; then
            echo "$PIDS" | xargs kill -9 2>/dev/null || true
            sleep 1
        fi
        
        print_info "Starting backend server..."
        
        # Use venv's python directly (more reliable than activation)
        VENV_PYTHON="$BACKEND_VENV/bin/python"
        
        if [ ! -f "$VENV_PYTHON" ]; then
            print_error "Virtual environment Python not found. Run build_backend first."
            exit 1
        fi
        
        # Start uvicorn in background using venv's python and save PID
        cd "$BACKEND_DIR"
        nohup "$VENV_PYTHON" -m uvicorn main:app --host 0.0.0.0 --port 8000 > "$BACKEND_DIR/backend.log" 2>&1 &
        BACKEND_PID=$!
        
        # Wait a moment for server to start
        sleep 3
        
        # Check if process is still running
        if ps -p $BACKEND_PID > /dev/null 2>&1; then
            print_success "Backend started successfully (PID: $BACKEND_PID)"
            print_success "Backend is running at http://localhost:9944"
            print_info "Logs: tail -f $BACKEND_DIR/backend.log"
            
            # Save PID to file for future reference
            echo $BACKEND_PID > "$BACKEND_DIR/.backend.pid"
        else
            print_error "Backend failed to start. Check logs: tail -f $BACKEND_DIR/backend.log"
            exit 1
        fi
    fi
}

# Show deployment summary
show_summary() {
    print_step "Deployment Summary"
    
    log_message ""
    log_message "${GREEN}Deployment completed successfully!${NC}"
    log_message ""
    log_message "Services Status:"
    
    if [ "$DEPLOY_FRONTEND" = true ]; then
        if [ -d "$FRONTEND_DIST" ]; then
            FRONTEND_STATUS="Built successfully"
            if [ "$USE_APACHE" = true ] || [ "$USE_NGINX" = true ]; then
                FRONTEND_STATUS="$FRONTEND_STATUS (deployed to $FRONTEND_WEB_ROOT)"
            fi
        else
            FRONTEND_STATUS="Build directory not found"
        fi
        log_message "  Frontend:  ${GREEN}$FRONTEND_STATUS${NC}"
        if [ "$USE_APACHE" = true ] || [ "$USE_NGINX" = true ]; then
            log_message "    URL:     http://localhost (or your configured domain)"
        else
            log_message "    Build:   $FRONTEND_DIST"
        fi
    fi
    
    if [ "$DEPLOY_BACKEND" = true ]; then
        # Check backend status
        BACKEND_STATUS="Unknown"
        if [ "$USE_SYSTEMD" = true ]; then
            if command -v systemctl > /dev/null 2>&1 && sudo systemctl is-active --quiet "$BACKEND_SERVICE_NAME" 2>/dev/null; then
                BACKEND_STATUS="Running (systemd)"
            else
                BACKEND_STATUS="Not running"
            fi
        else
            # Check if PID file exists and process is running
            if [ -f "$BACKEND_DIR/.backend.pid" ]; then
                PID=$(cat "$BACKEND_DIR/.backend.pid" 2>/dev/null || echo "")
                if [ -n "$PID" ] && ps -p $PID > /dev/null 2>&1; then
                    BACKEND_STATUS="Running (PID: $PID)"
                else
                    BACKEND_STATUS="Not running"
                fi
            else
                # Check if port is in use (macOS/Linux compatible)
                if command -v lsof > /dev/null 2>&1 && lsof -ti:8000,9944 > /dev/null 2>&1; then
                    BACKEND_STATUS="Running (port in use)"
                elif command -v netstat > /dev/null 2>&1 && netstat -an 2>/dev/null | grep -qE ":(8000|9944).*LISTEN"; then
                    BACKEND_STATUS="Running (port in use)"
                else
                    BACKEND_STATUS="Not running"
                fi
            fi
        fi
        log_message "  Backend:   ${GREEN}$BACKEND_STATUS${NC}"
        log_message "    URL:     http://localhost:9944"
    fi
    
    log_message ""
    log_message "Useful commands:"
    if [ "$DEPLOY_FRONTEND" = true ]; then
        log_message "  View frontend build:  ls -la $FRONTEND_DIST"
        if [ "$USE_APACHE" = true ]; then
            log_message "  Apache logs:          sudo tail -f /var/log/apache2/error.log"
        elif [ "$USE_NGINX" = true ]; then
            log_message "  Nginx logs:           sudo tail -f /var/log/nginx/error.log"
        fi
    fi
    if [ "$DEPLOY_BACKEND" = true ]; then
        if [ "$USE_SYSTEMD" = true ]; then
            log_message "  View backend logs:    sudo journalctl -u $BACKEND_SERVICE_NAME -f"
        else
            log_message "  View backend logs:    tail -f $BACKEND_DIR/backend.log"
        fi
    fi
    log_message "  View deployment log:  tail -f $LOG_FILE"
    log_message ""
    
    # Write footer to log file
    echo "" >> "$LOG_FILE"
    echo "================================================" >> "$LOG_FILE"
    echo "Deployment Log Ended: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
    echo "================================================" >> "$LOG_FILE"
}

# Main deployment function
deploy() {
    print_step "🚀 Starting Auto Deployment (No Docker)"
    
    log_message ""
    log_message "Deployment Configuration:"
    log_message "  Frontend: $([ "$DEPLOY_FRONTEND" = true ] && echo "Yes" || echo "No")"
    log_message "  Backend:  $([ "$DEPLOY_BACKEND" = true ] && echo "Yes" || echo "No")"
    log_message "  Git Pull: $([ "$SKIP_PULL" = true ] && echo "Skip" || echo "Yes")"
    log_message "  Log File: $LOG_FILE"
    log_message ""
    
    if [ "$SKIP_CONFIRM" = false ]; then
        # Prompt user (this won't be logged to avoid password issues)
        read -p "Continue with deployment? (y/N): " confirm
        # Log the response
        log_message "User confirmation: $([ "$confirm" = "y" ] || [ "$confirm" = "Y" ] && echo "Yes" || echo "No")"
        if [[ ! $confirm =~ ^[Yy]$ ]]; then
            print_info "Deployment cancelled."
            exit 0
        fi
    fi
    
    # Pre-flight checks
    check_git_status
    
    # Detect web server
    if [ "$DEPLOY_FRONTEND" = true ]; then
        detect_web_server
    fi
    
    # Git pull
    git_pull
    
    # Check backend service type before building
    if [ "$DEPLOY_BACKEND" = true ]; then
        check_backend_service
    fi
    
    # Build and deploy services
    if [ "$DEPLOY_FRONTEND" = true ]; then
        build_frontend
        deploy_frontend
    fi
    
    if [ "$DEPLOY_BACKEND" = true ]; then
        build_backend
        restart_backend
    fi
    
    # Show summary
    show_summary
}

# Run deployment
deploy
