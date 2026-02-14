# Scripts Directory

This folder contains utility and operational scripts organized by domain.

## Structure

### `/cint/`
CINT survey platform related scripts for analysis, checking status, and maintenance.

- `analyze_cint.py` - Analyze CINT survey data
- `check_cint_api.py` - Verify CINT API connectivity
- `check_cint_records.py` - Audit CINT records
- `check_cint_status.py` - Monitor CINT survey status
- `cleanup_cint_surveys.py` - Clean up old/inactive surveys
- `find_cint_db.py` - Locate CINT data in database
- `fix_cint_is_active.py` - Fix active status flags
- `test_cint_api.py` - Test CINT API endpoints
- `validate_cint_surveys.py` - Validate survey data integrity

### `/entry_links/`
Survey entry link generation and verification scripts.

- `check_entry_links.py` - Verify entry link validity
- `check_entry_links_v2.py` - Enhanced entry link checks
- `find_survey_without_link.py` - Find surveys missing entry links
- `fix_entry_links.py` - Repair broken entry links
- `test_entry_link_creation.py` - Test link generation
- `test_fix_links.py` - Test link repair procedures
- `test_get_link.py` - Test link retrieval

### `/surveys/`
Survey management and status monitoring scripts.

- `check_surveys_db.py` - Database survey audit
- `check_surveys_detail.py` - Detailed survey inspection
- `check_survey_status.py` - Monitor survey states
- `fix_closed_survey.py` - Handle closed survey issues

### `/leads/`
Lead management and pool monitoring scripts.

- `check_leads_tmp.py` - Inspect temporary leads
- `check_lead_sources.py` - Audit lead sources
- `check_pool.py` - Monitor lead pool status
- `check_vm_leads.py` - Check VM-deployed leads
- `delete_specific_leads.py` - Remove specific lead records

### `/db/`
Database maintenance and operations scripts.

- `check_db_collections.py` - Audit database collections
- `clear_and_refresh.py` - Clear and refresh database

### `/diagnostics/`
System diagnostics and troubleshooting scripts.

- `diagnose_403.py` - Debug 403 forbidden errors
- `check_guards.py` - Verify guard conditions
- `check_message_reason.py` - Analyze message reasons
- `check_all_countries.py` - Country configuration check

### `/admin/`
Administrative and setup scripts.

- `create_admin_user.py` - Create admin user accounts

### `/email/`
Email system setup and testing scripts.

- `setup_email_system.py` - Initialize email system
- `test_smtp.py` - Test SMTP configuration
- `verify_email_setup.py` - Verify email system setup

## Usage

Most scripts can be run directly from the root project directory:

```bash
python scripts/cint/check_cint_status.py
python scripts/email/test_smtp.py
```

Ensure you have the proper environment variables configured (see `.env.example` in the project root) before running scripts that interact with external services or databases.
