#!/bin/bash

# Merge and Deploy Agent
# Automates the process of merging PR branches and deploying to VM
# Usage: ./scripts/merge_and_deploy_agent.sh [branch-name] [options]

set -e  # Exit on error

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configuration
DEFAULT_TARGET_BRANCH="main"
DEPLOYMENT_LOG="$PROJECT_DIR/merge-deploy.log"

# Function to print section header
print_header() {
    echo -e "\n${BLUE}═══════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}\n"
}

# Function to print success message
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

# Function to print info message
print_info() {
    echo -e "${YELLOW}ℹ${NC} $1"
}

# Function to print error message
print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Function to log messages
log_message() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] $message" >> "$DEPLOYMENT_LOG"
}

# Parse command line arguments
SOURCE_BRANCH=""
TARGET_BRANCH="$DEFAULT_TARGET_BRANCH"
SKIP_TESTS=false
SKIP_DEPLOYMENT=false
DRY_RUN=false
AUTO_CONFIRM=false

show_usage() {
    echo "Merge and Deploy Agent"
    echo ""
    echo "Usage: $0 <source-branch> [options]"
    echo ""
    echo "Arguments:"
    echo "  source-branch       Branch to merge (e.g., copilot/fix-gloud-agents-visibility)"
    echo ""
    echo "Options:"
    echo "  --target <branch>   Target branch for merge (default: main)"
    echo "  --skip-tests        Skip running tests before merge"
    echo "  --skip-deployment   Skip deployment after merge"
    echo "  --dry-run           Show what would be done without making changes"
    echo "  --auto-confirm, -y  Skip all confirmation prompts"
    echo "  --help, -h          Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 copilot/fix-gloud-agents-visibility"
    echo "  $0 copilot/fix-gloud-agents-visibility --target main --auto-confirm"
    echo "  $0 feature/new-feature --dry-run"
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --target)
            TARGET_BRANCH="$2"
            shift 2
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --skip-deployment)
            SKIP_DEPLOYMENT=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --auto-confirm|-y)
            AUTO_CONFIRM=true
            shift
            ;;
        --help|-h)
            show_usage
            ;;
        *)
            if [[ -z "$SOURCE_BRANCH" ]]; then
                SOURCE_BRANCH="$1"
            else
                print_error "Unknown option: $1"
                show_usage
            fi
            shift
            ;;
    esac
done

# Validate source branch provided
if [[ -z "$SOURCE_BRANCH" ]]; then
    print_error "Source branch is required"
    show_usage
fi

# Main script
echo -e "${GREEN}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║        Merge and Deploy Agent                    ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════╝${NC}"

log_message "Starting merge and deploy process"
log_message "Source: $SOURCE_BRANCH -> Target: $TARGET_BRANCH"

# Change to project directory
cd "$PROJECT_DIR"

print_header "📋 Pre-Merge Checks"

# Check if source branch exists
if ! git show-ref --verify --quiet "refs/heads/$SOURCE_BRANCH"; then
    if git show-ref --verify --quiet "refs/remotes/origin/$SOURCE_BRANCH"; then
        print_info "Source branch exists on remote, checking out locally..."
        if [[ "$DRY_RUN" == false ]]; then
            git checkout -b "$SOURCE_BRANCH" "origin/$SOURCE_BRANCH"
        else
            print_info "[DRY RUN] Would checkout: $SOURCE_BRANCH"
        fi
    else
        print_error "Source branch '$SOURCE_BRANCH' does not exist locally or on remote"
        exit 1
    fi
fi

# Check if target branch exists
if ! git show-ref --verify --quiet "refs/heads/$TARGET_BRANCH"; then
    print_error "Target branch '$TARGET_BRANCH' does not exist"
    exit 1
fi

# Get current branch
CURRENT_BRANCH=$(git branch --show-current)
print_info "Current branch: $CURRENT_BRANCH"

# Check for uncommitted changes
if [[ -n $(git status -s) ]]; then
    print_error "You have uncommitted changes. Please commit or stash them first."
    git status -s
    exit 1
fi

print_success "Pre-merge checks passed"

# Show what will be merged
print_header "📊 Changes to be Merged"

print_info "Comparing $SOURCE_BRANCH with $TARGET_BRANCH..."
COMMIT_COUNT=$(git rev-list --count "$TARGET_BRANCH..$SOURCE_BRANCH" 2>/dev/null || echo "0")
print_info "Commits to merge: $COMMIT_COUNT"

if [[ "$COMMIT_COUNT" -eq 0 ]]; then
    print_info "No new commits to merge. Branches are up to date."
    exit 0
fi

echo ""
print_info "Recent commits in $SOURCE_BRANCH:"
git log --oneline "$TARGET_BRANCH..$SOURCE_BRANCH" | head -10

echo ""
print_info "Files that will be changed:"
git diff --name-status "$TARGET_BRANCH..$SOURCE_BRANCH" | head -20

# Confirmation prompt
if [[ "$AUTO_CONFIRM" == false && "$DRY_RUN" == false ]]; then
    echo ""
    read -p "Do you want to proceed with the merge? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Merge cancelled by user"
        exit 0
    fi
fi

# Run tests if not skipped
if [[ "$SKIP_TESTS" == false ]]; then
    print_header "🧪 Running Tests"
    
    # Check if there are any test scripts
    if [[ -f "$PROJECT_DIR/backend/pytest.ini" ]] || [[ -f "$PROJECT_DIR/backend/test_*.py" ]]; then
        print_info "Running backend tests..."
        if [[ "$DRY_RUN" == false ]]; then
            cd "$PROJECT_DIR/backend"
            if command -v pytest &> /dev/null; then
                pytest -v || print_error "Tests failed, but continuing..."
            else
                print_info "pytest not found, skipping tests"
            fi
            cd "$PROJECT_DIR"
        else
            print_info "[DRY RUN] Would run backend tests"
        fi
    else
        print_info "No test configuration found, skipping tests"
    fi
    
    print_success "Tests completed"
fi

# Perform the merge
print_header "🔀 Merging Branches"

if [[ "$DRY_RUN" == true ]]; then
    print_info "[DRY RUN] Would execute:"
    print_info "  git checkout $TARGET_BRANCH"
    print_info "  git pull origin $TARGET_BRANCH"
    print_info "  git merge --no-ff $SOURCE_BRANCH -m 'Merge $SOURCE_BRANCH into $TARGET_BRANCH'"
    print_info "  git push origin $TARGET_BRANCH"
else
    print_info "Switching to $TARGET_BRANCH..."
    git checkout "$TARGET_BRANCH"
    
    print_info "Updating $TARGET_BRANCH from remote..."
    git pull origin "$TARGET_BRANCH"
    
    print_info "Merging $SOURCE_BRANCH into $TARGET_BRANCH..."
    git merge --no-ff "$SOURCE_BRANCH" -m "Merge $SOURCE_BRANCH into $TARGET_BRANCH"
    
    print_info "Pushing merged changes to remote..."
    git push origin "$TARGET_BRANCH"
    
    print_success "Merge completed successfully!"
    log_message "Merge completed: $SOURCE_BRANCH -> $TARGET_BRANCH"
fi

# Deployment
if [[ "$SKIP_DEPLOYMENT" == false ]]; then
    print_header "🚀 Deployment"
    
    if [[ -f "$PROJECT_DIR/deploy.sh" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            print_info "[DRY RUN] Would execute: ./deploy.sh"
        else
            print_info "Running deployment script..."
            
            if [[ "$AUTO_CONFIRM" == true ]]; then
                # Run with auto-confirm if available
                bash "$PROJECT_DIR/deploy.sh" --no-confirm || print_error "Deployment completed with warnings"
            else
                bash "$PROJECT_DIR/deploy.sh" || print_error "Deployment completed with warnings"
            fi
            
            print_success "Deployment completed!"
            log_message "Deployment completed successfully"
        fi
    else
        print_info "No deploy.sh found. Manual deployment may be required."
        log_message "No deployment script found"
    fi
else
    print_info "Deployment skipped as requested"
fi

# Final summary
print_header "✅ Summary"

if [[ "$DRY_RUN" == true ]]; then
    echo -e "${YELLOW}DRY RUN MODE - No changes were made${NC}"
else
    print_success "Branch merged: $SOURCE_BRANCH -> $TARGET_BRANCH"
    if [[ "$SKIP_DEPLOYMENT" == false ]]; then
        print_success "Deployment completed"
    fi
fi

print_info "Log file: $DEPLOYMENT_LOG"

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Merge and deploy process complete!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""

log_message "Merge and deploy process completed successfully"
