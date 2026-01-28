# Finding and Tracking Agent Work on the VM

## Quick Solution

If you completed work using GitHub Copilot agents (or other cloud agents) and can't locate it on the VM, follow these steps:

### 1. Locate Your Work

Run the tracking script:
```bash
cd /home/runner/work/campaign_platform/campaign_platform
./scripts/track_agent_work.sh
```

This will show you:
- ✅ Recent commits (including agent work)
- ✅ Current branch and uncommitted changes  
- ✅ Files that were created or modified
- ✅ Agent work log entries
- ✅ Quick reference commands

### 2. Check Specific Time Periods

For today's work only:
```bash
./scripts/track_agent_work.sh --today
```

For last week's work:
```bash
./scripts/track_agent_work.sh --week
```

With detailed file changes:
```bash
./scripts/track_agent_work.sh --files
```

### 3. Manual Commands

If you prefer manual investigation:

```bash
# See all commits from today
git log --since="today" --all --oneline

# See what files changed recently
find . -type f -mtime -1 -not -path "./.git/*"

# See the last commit's changes
git show --stat

# Check which branch you're on
git branch

# See uncommitted changes
git status
```

### 4. Check the Work Log

View the agent work log:
```bash
cat AGENT_WORK_LOG.md
```

This log contains detailed entries for each agent work session including:
- Date and time of work
- What was completed
- Files created/modified
- Branch information
- Deployment instructions

## Common Scenarios

### Scenario: "I did work this morning but don't see it"

**Possible causes and solutions:**

1. **Work wasn't committed**
   ```bash
   git status  # Check for uncommitted changes
   git add .
   git commit -m "feat: description - completed by agent"
   ```

2. **Work is on a different branch**
   ```bash
   git branch -a  # See all branches
   git checkout copilot/[branch-name]  # Switch to the branch
   ```

3. **Work wasn't pushed to remote**
   ```bash
   git log origin/$(git branch --show-current)..HEAD  # See unpushed commits
   git push origin $(git branch --show-current)  # Push to remote
   ```

4. **Work is in a different directory**
   ```bash
   pwd  # Check current directory
   cd /home/runner/work/campaign_platform/campaign_platform  # Go to project root
   ```

### Scenario: "Work is on my machine but not on VM"

**Solution:**
```bash
# On your local machine:
git add .
git commit -m "feat: description - completed by agent"
git push origin [branch-name]

# On the VM:
cd /home/runner/work/campaign_platform/campaign_platform
git fetch --all
git checkout [branch-name]
git pull origin [branch-name]
```

### Scenario: "Not sure what files the agent changed"

**Solution:**
```bash
# See files in last commit
git show --stat HEAD

# See all changes on current branch vs main
git diff main..HEAD --name-only

# Use the tracking script
./scripts/track_agent_work.sh --files
```

## Directory Structure

Agent work is typically located in these directories:

```
/home/runner/work/campaign_platform/campaign_platform/
├── backend/                    # Python/FastAPI backend
│   ├── agents/                # AI agent implementations
│   ├── routers/               # API routes
│   └── services/              # Business logic
├── Campaign_platform/         # React frontend
├── scripts/                   # Helper scripts
│   └── track_agent_work.sh   # Work tracking script ⭐
├── .github/                   # GitHub configuration
│   └── COPILOT_AGENTS_README.md  # Detailed guide ⭐
├── AGENT_WORK_LOG.md         # Work session log ⭐
└── [various config and doc files]
```

## Key Files for Tracking Agent Work

1. **AGENT_WORK_LOG.md** - Central log of all agent sessions
2. **.github/COPILOT_AGENTS_README.md** - Comprehensive tracking guide
3. **scripts/track_agent_work.sh** - Automated tracking script
4. **This file (AGENT_WORK_LOCATION_GUIDE.md)** - Quick reference

## Best Practices Going Forward

To avoid this issue in the future:

### ✅ After Each Agent Session:

1. **Update the work log:**
   ```bash
   # Edit AGENT_WORK_LOG.md and add session details
   nano AGENT_WORK_LOG.md
   ```

2. **Commit with clear messages:**
   ```bash
   git add .
   git commit -m "feat: [what was done] - completed by GitHub Copilot"
   ```

3. **Push immediately:**
   ```bash
   git push origin $(git branch --show-current)
   ```

4. **Verify on VM:**
   ```bash
   ./scripts/track_agent_work.sh
   ```

### ✅ Use Branch Naming Conventions:

- `copilot/*` - For GitHub Copilot agent work
- `agent/*` - For other AI agent work
- `ai/*` - For general AI-assisted work

Examples:
- `copilot/add-email-tracking`
- `copilot/fix-survey-allocation`
- `agent/database-optimization`

### ✅ Document As You Go:

Don't wait until the end of the day. Update AGENT_WORK_LOG.md after each significant agent session.

## Deployment After Finding Agent Work

Once you've located the agent work:

1. **Review the changes:**
   ```bash
   git diff main..HEAD
   ```

2. **Test if needed:**
   ```bash
   # Run tests, start servers, etc.
   ```

3. **Merge to main:**
   ```bash
   git checkout main
   git merge [agent-branch]
   git push origin main
   ```

4. **Deploy:**
   ```bash
   ./deploy.sh  # Use existing deployment script
   ```

## Getting Help

If you're still having trouble locating your agent work:

1. **Run the tracking script:** `./scripts/track_agent_work.sh --help`
2. **Read the detailed guide:** `cat .github/COPILOT_AGENTS_README.md`
3. **Check the work log:** `cat AGENT_WORK_LOG.md`
4. **Review git history:** `git log --all --oneline --graph`
5. **Ask team members** who may have context

## Summary

**Three tools to locate agent work:**

1. 🔍 **Tracking Script** - `./scripts/track_agent_work.sh`
2. 📋 **Work Log** - `AGENT_WORK_LOG.md`
3. 📖 **Detailed Guide** - `.github/COPILOT_AGENTS_README.md`

**The golden rule:**
> Always commit, document, and push agent work immediately after completion.

---

**Last Updated:** 2026-01-27  
**Purpose:** Help locate and track AI agent work on the VM  
**Quick Command:** `./scripts/track_agent_work.sh`
