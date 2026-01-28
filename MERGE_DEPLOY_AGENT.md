# Merge and Deploy Agent

## Overview

The Merge and Deploy Agent is an automated script that handles the complete workflow of merging PR branches and deploying to VM. It eliminates manual steps and reduces the chance of errors during the merge and deployment process.

## Purpose

This agent solves the problem of having to manually:
1. Merge pull request branches
2. Run tests before deployment
3. Deploy changes to the VM
4. Track the deployment process

## Features

✅ **Automated Merge Process** - Handles git checkout, pull, merge, and push  
✅ **Pre-Merge Validation** - Checks for uncommitted changes, validates branches  
✅ **Optional Testing** - Runs tests before merging (can be skipped)  
✅ **Automatic Deployment** - Runs deployment script after successful merge  
✅ **Dry Run Mode** - Preview what will happen without making changes  
✅ **Logging** - Records all operations to a log file  
✅ **Color-Coded Output** - Easy to read terminal output  
✅ **Confirmation Prompts** - Prevents accidental merges (can be disabled)

## Installation

The script is already installed at:
```
scripts/merge_and_deploy_agent.sh
```

Make sure it's executable:
```bash
chmod +x scripts/merge_and_deploy_agent.sh
```

## Usage

### Basic Usage

Merge a PR branch to main:
```bash
./scripts/merge_and_deploy_agent.sh copilot/fix-gloud-agents-visibility
```

### Common Options

**Auto-confirm mode (no prompts):**
```bash
./scripts/merge_and_deploy_agent.sh copilot/fix-gloud-agents-visibility --auto-confirm
```

**Dry run (see what would happen):**
```bash
./scripts/merge_and_deploy_agent.sh copilot/fix-gloud-agents-visibility --dry-run
```

**Skip deployment:**
```bash
./scripts/merge_and_deploy_agent.sh copilot/fix-gloud-agents-visibility --skip-deployment
```

**Skip tests:**
```bash
./scripts/merge_and_deploy_agent.sh copilot/fix-gloud-agents-visibility --skip-tests
```

**Merge to a different target branch:**
```bash
./scripts/merge_and_deploy_agent.sh feature/branch --target develop
```

**Full auto mode (no prompts, skip tests):**
```bash
./scripts/merge_and_deploy_agent.sh copilot/fix-gloud-agents-visibility --auto-confirm --skip-tests
```

## Command Line Options

| Option | Description |
|--------|-------------|
| `<source-branch>` | **Required.** Branch to merge (e.g., `copilot/fix-gloud-agents-visibility`) |
| `--target <branch>` | Target branch for merge (default: `main`) |
| `--skip-tests` | Skip running tests before merge |
| `--skip-deployment` | Skip deployment after merge |
| `--dry-run` | Show what would be done without making changes |
| `--auto-confirm`, `-y` | Skip all confirmation prompts |
| `--help`, `-h` | Show help message |

## Workflow

The agent follows this workflow:

### 1. Pre-Merge Checks ✓
- Validates source and target branches exist
- Checks for uncommitted changes
- Shows current branch

### 2. Changes Preview 📊
- Shows number of commits to merge
- Lists recent commits
- Displays files that will be changed
- Prompts for confirmation (unless `--auto-confirm`)

### 3. Testing 🧪
- Runs backend tests if available
- Can be skipped with `--skip-tests`

### 4. Merge Process 🔀
- Checks out target branch
- Pulls latest changes from remote
- Merges source branch (no fast-forward)
- Pushes merged changes to remote

### 5. Deployment 🚀
- Runs `deploy.sh` if it exists
- Can be skipped with `--skip-deployment`
- Passes `--no-confirm` if agent is in auto-confirm mode

### 6. Summary ✅
- Shows what was accomplished
- Provides log file location

## Examples

### Example 1: Standard Merge and Deploy

Merge the agent tracking system PR:
```bash
./scripts/merge_and_deploy_agent.sh copilot/fix-gloud-agents-visibility
```

**Output:**
- Shows commits to merge
- Asks for confirmation
- Runs tests
- Merges to main
- Deploys to VM
- Shows success message

### Example 2: Quick Merge (Auto-confirm)

For trusted branches, skip prompts:
```bash
./scripts/merge_and_deploy_agent.sh copilot/fix-gloud-agents-visibility -y
```

### Example 3: Preview Mode

See what would happen without making changes:
```bash
./scripts/merge_and_deploy_agent.sh copilot/fix-gloud-agents-visibility --dry-run
```

**Output:**
```
[DRY RUN] Would execute:
  git checkout main
  git pull origin main
  git merge --no-ff copilot/fix-gloud-agents-visibility
  git push origin main
[DRY RUN] Would execute: ./deploy.sh
```

### Example 4: Merge Only (No Deploy)

Merge changes but skip deployment:
```bash
./scripts/merge_and_deploy_agent.sh copilot/fix-gloud-agents-visibility --skip-deployment
```

Useful when you want to deploy later manually.

### Example 5: Fast Merge (Skip Tests)

When you're confident tests will pass:
```bash
./scripts/merge_and_deploy_agent.sh copilot/fix-gloud-agents-visibility --skip-tests -y
```

## Log Files

All operations are logged to:
```
merge-deploy.log
```

Example log entry:
```
[2026-01-28 04:35:00] Starting merge and deploy process
[2026-01-28 04:35:00] Source: copilot/fix-gloud-agents-visibility -> Target: main
[2026-01-28 04:35:15] Merge completed: copilot/fix-gloud-agents-visibility -> main
[2026-01-28 04:35:30] Deployment completed successfully
[2026-01-28 04:35:30] Merge and deploy process completed successfully
```

View the log:
```bash
cat merge-deploy.log
```

## Error Handling

The agent handles common errors:

### Uncommitted Changes
```
✗ You have uncommitted changes. Please commit or stash them first.
```

**Solution:** Commit or stash your changes before running the agent.

### Branch Doesn't Exist
```
✗ Source branch 'feature/xyz' does not exist locally or on remote
```

**Solution:** Check branch name spelling or fetch from remote first.

### No Commits to Merge
```
ℹ No new commits to merge. Branches are up to date.
```

**Result:** Agent exits cleanly (nothing to do).

### Tests Failed
```
✗ Tests failed, but continuing...
```

**Result:** Agent continues but you should review test failures.

## Integration with Existing Tools

The agent integrates with:

1. **deploy.sh** - Runs the existing deployment script
2. **pytest** - Runs backend tests if configured
3. **git** - Uses standard git commands for merge operations

## Best Practices

### ✅ DO

- **Use dry-run first** for unfamiliar branches
- **Review changes** before confirming merge
- **Check logs** after deployment
- **Keep target branch updated** before merging

### ❌ DON'T

- **Don't skip tests** on critical branches
- **Don't use auto-confirm** on untested code
- **Don't merge** with uncommitted changes
- **Don't force-push** after using this agent

## Troubleshooting

### Issue: "Permission denied"
**Cause:** Script is not executable  
**Solution:** Run `chmod +x scripts/merge_and_deploy_agent.sh`

### Issue: "Authentication failed"
**Cause:** Git credentials not configured  
**Solution:** Configure git credentials or use SSH keys

### Issue: "Merge conflict"
**Cause:** Conflicting changes in target branch  
**Solution:** Resolve conflicts manually, then rerun agent

### Issue: "Deploy script not found"
**Cause:** deploy.sh doesn't exist  
**Solution:** Agent will skip deployment and notify you

## Safety Features

The agent includes several safety features:

1. **Uncommitted Changes Check** - Prevents merging with dirty working directory
2. **Branch Validation** - Ensures source and target branches exist
3. **Confirmation Prompts** - Requires user approval (unless disabled)
4. **Dry Run Mode** - Test before executing
5. **Logging** - Audit trail of all operations
6. **Error Exit** - Stops on errors (set -e)

## Advanced Usage

### Custom Target Branch

Merge to a different branch:
```bash
./scripts/merge_and_deploy_agent.sh feature/branch --target develop
```

### Scripting/Automation

Use in scripts with auto-confirm:
```bash
#!/bin/bash
branches=("copilot/feature-1" "copilot/feature-2")
for branch in "${branches[@]}"; do
    ./scripts/merge_and_deploy_agent.sh "$branch" -y --skip-tests
done
```

### CI/CD Integration

Add to your CI/CD pipeline:
```yaml
- name: Merge and Deploy
  run: |
    ./scripts/merge_and_deploy_agent.sh ${{ github.ref_name }} \
      --auto-confirm \
      --target production
```

## Comparison with Manual Process

| Step | Manual Process | With Agent |
|------|----------------|------------|
| Checkout target | `git checkout main` | Automatic |
| Pull latest | `git pull origin main` | Automatic |
| Merge branch | `git merge feature` | Automatic |
| Run tests | Manual command | Automatic (optional) |
| Push changes | `git push origin main` | Automatic |
| Deploy | `./deploy.sh` | Automatic (optional) |
| Logging | Manual notes | Automatic |
| **Time** | 5-10 minutes | 1-2 minutes |
| **Errors** | Common | Rare |

## Related Tools

- **track_agent_work.sh** - Track and locate agent work
- **deploy.sh** - Deploy to VM
- **auto_pull.sh** - Auto-pull from remote

## Support

For issues or questions:
1. Check this documentation
2. Review the log file (`merge-deploy.log`)
3. Use `--dry-run` to preview operations
4. Run with `--help` for usage information

## Changelog

### Version 1.0 (2026-01-28)
- Initial release
- Basic merge and deploy functionality
- Dry run mode
- Auto-confirm mode
- Test running capability
- Logging support
- Color-coded output

---

**Created:** 2026-01-28  
**Purpose:** Automate PR merge and VM deployment  
**Location:** `scripts/merge_and_deploy_agent.sh`
