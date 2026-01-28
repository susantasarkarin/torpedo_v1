# GitHub Copilot Agents - Work Tracking Guide

## Overview

This guide explains how to track, locate, and manage work completed by GitHub Copilot agents and other AI assistants in this repository.

## The Problem

When AI agents complete work in a repository:
- Files may be created or modified across multiple directories
- Work might be on a specific branch
- Team members may not know what was changed or where
- Deployment to VM requires knowing what files to sync

## The Solution

This repository includes several tools to make agent work visible and trackable:

1. **AGENT_WORK_LOG.md** - Central log of all agent work sessions
2. **scripts/track_agent_work.sh** - Automated tracking script
3. **Git commit conventions** - Clear commit messages for agent work
4. **Branch naming conventions** - Prefixed branch names (e.g., `copilot/feature-name`)

## Quick Start

### After Agent Completes Work

1. **Check what changed:**
   ```bash
   git status
   git diff
   ```

2. **Update the work log:**
   ```bash
   # Edit AGENT_WORK_LOG.md and add an entry for this session
   nano AGENT_WORK_LOG.md
   ```

3. **Commit and push:**
   ```bash
   git add .
   git commit -m "feat: [description] - completed by GitHub Copilot"
   git push origin [branch-name]
   ```

4. **Verify on VM:**
   ```bash
   # On the VM
   cd /home/runner/work/campaign_platform/campaign_platform
   git pull origin [branch-name]
   ./scripts/track_agent_work.sh
   ```

## Locating Agent Work on VM

### Option 1: Use the Tracking Script

```bash
cd /home/runner/work/campaign_platform/campaign_platform
./scripts/track_agent_work.sh
```

This will show:
- Recent commits
- Files changed
- Current branch
- Uncommitted changes

### Option 2: Manual Git Commands

```bash
# See recent commits
git log --oneline --since="1 day ago"

# See files changed in last commit
git show --stat HEAD

# See all changes on current branch
git diff main..HEAD --name-only

# See what branch you're on
git branch
```

### Option 3: Check the Work Log

```bash
cat AGENT_WORK_LOG.md
```

The work log contains:
- Dates of agent sessions
- What was completed
- Which files were created/modified
- Location of files
- Deployment instructions

## Understanding Agent Branches

Agent work is typically done on feature branches with naming conventions:

- `copilot/*` - Work done by GitHub Copilot agents
- `agent/*` - Work done by other AI agents
- `ai/*` - General AI-assisted work

**To see all agent branches:**
```bash
git branch -a | grep -E 'copilot|agent|ai'
```

**To switch to an agent branch:**
```bash
git checkout copilot/[feature-name]
```

## Common Workflows

### Scenario 1: Finding Morning's Agent Work

```bash
# Show commits from today
git log --since="today" --oneline

# Show files changed today
find . -type f -mtime -1 -not -path "./.git/*"

# Check the agent work log
tail -50 AGENT_WORK_LOG.md
```

### Scenario 2: Deploying Agent Work to Production

```bash
# 1. Review what changed
git diff main..copilot/[feature-name] --name-only

# 2. Check the work log for deployment notes
grep -A 10 "Deployment Notes" AGENT_WORK_LOG.md

# 3. Merge to main
git checkout main
git merge copilot/[feature-name]

# 4. Deploy using existing scripts
./deploy.sh
```

### Scenario 3: Agent Work Not Visible

If you completed work with an agent but can't find it:

```bash
# 1. Check if changes were committed
git status

# 2. Check which branch you're on
git branch

# 3. Check if there are unpushed commits
git log origin/[branch]..HEAD

# 4. Push if needed
git push origin [branch-name]

# 5. Check other branches
git branch -a

# 6. Check recent activity across all branches
git log --all --oneline --since="1 day ago"
```

## File Organization

Agent work typically creates or modifies files in these areas:

### Backend Code
- `/backend/*` - Python/FastAPI backend code
- `/backend/agents/*` - AI agent implementations
- `/backend/routers/*` - API routes
- `/backend/services/*` - Business logic

### Frontend Code
- `/Campaign_platform/*` - React frontend
- `/websites/*` - Additional web properties

### Configuration
- `/*.py` - Root-level Python scripts
- `/*.sh` - Shell scripts
- `/*.md` - Documentation
- `/*.json` - Configuration files

### Documentation
- `/AGENT_WORK_LOG.md` - Agent work tracking
- `/*_DOCS.md` - Feature documentation
- `/*_SUMMARY.md` - Implementation summaries

## Best Practices

### ✅ DO

1. **Always update AGENT_WORK_LOG.md** after agent work
2. **Use descriptive commit messages** that mention the agent
3. **Test agent-generated code** before deploying
4. **Push changes immediately** so they're visible on VM
5. **Document file locations** in the work log
6. **Use feature branches** for agent work
7. **Review changes** before committing

### ❌ DON'T

1. **Don't skip the work log** - it's the primary tracking mechanism
2. **Don't use vague commit messages** like "update" or "fix"
3. **Don't work directly on main** - use feature branches
4. **Don't forget to push** - local commits aren't visible on VM
5. **Don't delete the work log** - it's the permanent record
6. **Don't assume others know** what the agent did - document it

## Commit Message Conventions

When committing agent work, use these prefixes:

- `feat:` - New feature added by agent
- `fix:` - Bug fix by agent
- `docs:` - Documentation updates
- `refactor:` - Code refactoring
- `test:` - Test additions/updates
- `chore:` - Maintenance tasks

**Format:**
```
<type>: <description> - completed by <agent-name>

Examples:
feat: add email campaign automation - completed by GitHub Copilot
fix: resolve CPX entry link format issue - completed by GitHub Copilot
docs: update agent work tracking guide - completed by GitHub Copilot
```

## Integration with Existing Tools

### Deploy Script

The existing `deploy.sh` script works with agent changes:

```bash
./deploy.sh --frontend-only  # Deploy frontend changes
./deploy.sh --backend-only   # Deploy backend changes
./deploy.sh                   # Deploy everything
```

### Git Pull Automation

The `auto_pull.sh` script can fetch agent work:

```bash
./auto_pull.sh  # Pull latest from current branch
```

### Monitoring

Check deployment logs:
```bash
cat /var/www/campaign_platform/cron-deploy.log
```

## Troubleshooting

### Problem: "I did work this morning but can't find it"

**Solution:**
1. Check if you committed the work:
   ```bash
   git log --since="today" --all --oneline
   ```

2. Check all branches:
   ```bash
   git branch -a
   ```

3. Check for uncommitted changes:
   ```bash
   git status
   ```

4. Run the tracking script:
   ```bash
   ./scripts/track_agent_work.sh --today
   ```

### Problem: "Work is on my local machine but not on VM"

**Solution:**
1. Commit changes:
   ```bash
   git add .
   git commit -m "feat: [description] - completed by agent"
   ```

2. Push to remote:
   ```bash
   git push origin [branch-name]
   ```

3. On VM, pull changes:
   ```bash
   git pull origin [branch-name]
   ```

### Problem: "Not sure which files the agent modified"

**Solution:**
1. Check last commit:
   ```bash
   git show --stat
   ```

2. Check work log:
   ```bash
   grep -A 20 "Session: $(date +%Y-%m-%d)" AGENT_WORK_LOG.md
   ```

3. Use tracking script:
   ```bash
   ./scripts/track_agent_work.sh --files
   ```

## Advanced Usage

### View Detailed Change Statistics

```bash
# Lines changed per file
git diff --stat main..HEAD

# Detailed changes with diff
git diff main..HEAD

# Changes by file type
git diff main..HEAD --name-only | grep '\.py$'  # Python files
git diff main..HEAD --name-only | grep '\.jsx\?$'  # JS/JSX files
```

### Track Agent Performance

```bash
# Count commits by agent
git log --all --oneline | grep -i "copilot\|agent" | wc -l

# See agent work over time
git log --all --oneline --since="1 week ago" | grep -i "copilot\|agent"

# Files most frequently modified by agents
git log --all --name-only --oneline | grep -v '^[a-f0-9]' | sort | uniq -c | sort -rn | head -20
```

## Resources

- **Main Work Log:** `/AGENT_WORK_LOG.md`
- **Tracking Script:** `/scripts/track_agent_work.sh`
- **Deploy Script:** `/deploy.sh`
- **Auto Pull:** `/auto_pull.sh`

## Getting Help

If you're having trouble locating agent work:

1. Check this README
2. Review the AGENT_WORK_LOG.md file
3. Run the tracking script
4. Check git history
5. Ask team members who may have more context

## Summary

**The key to making agent work visible:**

1. 📝 **Log it** - Update AGENT_WORK_LOG.md
2. 💾 **Commit it** - Use descriptive messages
3. 🚀 **Push it** - Make it visible on VM
4. ✅ **Verify it** - Run tracking script

Follow these practices and agent work will always be easy to locate and manage!

---

**Last Updated:** 2026-01-27  
**For Questions:** Check AGENT_WORK_LOG.md or contact the development team
