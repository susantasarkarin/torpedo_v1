#!/bin/bash

# Agent Work Tracking Script
# This script helps locate and summarize work completed by AI agents

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Date format for consistency
DATE_FORMAT="%Y-%m-%d"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Change to project directory
cd "$PROJECT_DIR"

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

# Parse command line arguments
SHOW_TODAY=0
SHOW_WEEK=0
SHOW_FILES=0
SHOW_STATS=0
SHOW_ALL=1
TIME_FILTER="7 days ago"

while [[ $# -gt 0 ]]; do
    case $1 in
        --today)
            SHOW_TODAY=1
            SHOW_ALL=0
            TIME_FILTER="today"
            shift
            ;;
        --week)
            SHOW_WEEK=1
            SHOW_ALL=0
            TIME_FILTER="1 week ago"
            shift
            ;;
        --files)
            SHOW_FILES=1
            shift
            ;;
        --stats)
            SHOW_STATS=1
            shift
            ;;
        --help|-h)
            echo "Agent Work Tracking Script"
            echo ""
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --today     Show only today's agent work"
            echo "  --week      Show last week's agent work"
            echo "  --files     Show detailed file changes"
            echo "  --stats     Show statistics about agent work"
            echo "  --help, -h  Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Show recent agent work (default: last 7 days)"
            echo "  $0 --today           # Show today's work"
            echo "  $0 --week --files    # Show last week's work with file details"
            echo "  $0 --stats           # Show agent work statistics"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Main script
echo -e "${GREEN}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║        Agent Work Tracking & Location Tool       ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════╝${NC}"

# Show current location
print_header "📍 Current Location"
print_info "Project Directory: $PROJECT_DIR"
print_info "Current Branch: $(git branch --show-current)"
print_info "Latest Commit: $(git log -1 --oneline)"

# Show repository status
print_header "📊 Repository Status"

# Check for uncommitted changes
if [[ -n $(git status -s) ]]; then
    print_info "Uncommitted changes detected:"
    git status -s
else
    print_success "No uncommitted changes"
fi

# Check for unpushed commits
CURRENT_BRANCH=$(git branch --show-current)
# Check if the remote branch exists before comparing
if git show-ref --verify --quiet refs/remotes/origin/$CURRENT_BRANCH; then
    UNPUSHED=$(git log origin/$CURRENT_BRANCH..$CURRENT_BRANCH --oneline 2>/dev/null | wc -l)
else
    UNPUSHED=0
    print_info "Remote branch not found (new branch or not yet pushed)"
fi
if [[ $UNPUSHED -gt 0 ]]; then
    print_info "$UNPUSHED unpushed commit(s) on branch $CURRENT_BRANCH"
    git log origin/$CURRENT_BRANCH..$CURRENT_BRANCH --oneline
else
    print_success "All commits pushed to remote"
fi

# Show recent agent work
print_header "🤖 Recent Agent Work (since $TIME_FILTER)"

# Show commits that mention agents or copilot
AGENT_COMMITS=$(git log --all --oneline --since="$TIME_FILTER" --grep="copilot\|agent\|AI\|bot" -i)

if [[ -n "$AGENT_COMMITS" ]]; then
    echo -e "${GREEN}Agent-related commits:${NC}"
    echo "$AGENT_COMMITS"
else
    # If no agent-specific commits, show all recent commits
    print_info "No commits explicitly mentioning agents found. Showing all recent commits:"
    git log --all --oneline --since="$TIME_FILTER"
fi

# Show agent branches
print_header "🌿 Agent Work Branches"

AGENT_BRANCHES=$(git branch -a | grep -E 'copilot|agent|ai' || echo "")
if [[ -n "$AGENT_BRANCHES" ]]; then
    echo -e "${GREEN}Branches with agent work:${NC}"
    echo "$AGENT_BRANCHES"
else
    print_info "No specific agent branches found"
fi

# Show recently modified files
if [[ $SHOW_FILES -eq 1 ]] || [[ $SHOW_ALL -eq 1 ]]; then
    print_header "📝 Recently Modified Files"
    
    # Files modified in last commit
    print_info "Files in last commit:"
    git show --stat --oneline HEAD | tail -n +2
    
    # Files with uncommitted changes
    if [[ -n $(git status -s) ]]; then
        echo ""
        print_info "Files with uncommitted changes:"
        git status -s
    fi
fi

# Show statistics
if [[ $SHOW_STATS -eq 1 ]]; then
    print_header "📈 Agent Work Statistics"
    
    # Count commits
    TOTAL_COMMITS=$(git log --all --oneline --since="$TIME_FILTER" | wc -l)
    AGENT_COMMIT_COUNT=$(git log --all --oneline --since="$TIME_FILTER" --grep="copilot\|agent\|AI\|bot" -i | wc -l)
    
    print_info "Total commits (since $TIME_FILTER): $TOTAL_COMMITS"
    print_info "Agent-related commits: $AGENT_COMMIT_COUNT"
    
    # Lines changed
    echo ""
    print_info "Lines changed in recent work:"
    # Check if we have enough commits before running diff
    COMMIT_COUNT=$(git rev-list --count HEAD 2>/dev/null || echo "0")
    if [[ $COMMIT_COUNT -ge 6 ]]; then
        git diff --shortstat HEAD~5..HEAD 2>/dev/null || print_info "Unable to compute statistics"
    else
        print_info "Not enough commit history (need at least 6 commits)"
    fi
    
    # Most changed files
    echo ""
    print_info "Most frequently changed files (last 20 commits):"
    git log --name-only --oneline --since="$TIME_FILTER" | grep -v '^[a-f0-9]' | grep -v '^$' | sort | uniq -c | sort -rn | head -10
fi

# Check agent work log
print_header "📋 Agent Work Log"

if [[ -f "$PROJECT_DIR/AGENT_WORK_LOG.md" ]]; then
    print_success "AGENT_WORK_LOG.md found"
    
    # Show recent entries from the log
    echo ""
    print_info "Recent log entries:"
    echo ""
    
    # Try to extract the last session entry
    if [[ $SHOW_TODAY -eq 1 ]]; then
        TODAY=$(date +$DATE_FORMAT)
        grep -A 20 "Session: $TODAY" "$PROJECT_DIR/AGENT_WORK_LOG.md" || print_info "No entries for today"
    else
        # Show last few session entries
        tail -50 "$PROJECT_DIR/AGENT_WORK_LOG.md"
    fi
else
    print_error "AGENT_WORK_LOG.md not found"
    print_info "Create it to track agent work sessions"
fi

# Quick reference commands
print_header "🔧 Quick Reference Commands"

echo -e "${CYAN}View detailed changes:${NC}"
echo '  git show HEAD              # Last commit details'
echo '  git diff main..HEAD        # All changes on current branch'
echo ""
echo -e "${CYAN}Find specific work:${NC}"
echo "  git log --since='today'    # Today's commits"
echo "  git log --grep='copilot'   # Commits mentioning copilot"
echo ""
echo -e "${CYAN}Sync with remote:${NC}"
echo '  git pull origin $(git branch --show-current)'
echo '  git push origin $(git branch --show-current)'
echo ""
echo -e "${CYAN}View work log:${NC}"
echo '  cat AGENT_WORK_LOG.md      # Full work log'
echo '  tail -50 AGENT_WORK_LOG.md # Recent entries'

# Summary
print_header "✅ Summary"

print_success "Repository location: $PROJECT_DIR"
print_success "Current branch: $(git branch --show-current)"
print_success "Tracking script location: $SCRIPT_DIR/$(basename $0)"

echo ""
print_info "For more help, see: .github/COPILOT_AGENTS_README.md"
print_info "To update work log: Edit AGENT_WORK_LOG.md"
print_info "Run with --help for more options"

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Agent work tracking complete!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""
