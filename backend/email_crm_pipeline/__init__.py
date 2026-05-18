"""
Email CRM Pipeline
==================
Reads emails from email_sync.emails, classifies them via Claude Batch API,
populates existing CRM collections, identifies reactivation candidates,
and drafts personalised outreach emails.

Entry points:
  python -m backend.email_crm_pipeline.email_classifier   --help
  python -m backend.email_crm_pipeline.crm_populator      --help
  python -m backend.email_crm_pipeline.reactivation_identifier --help
  python -m backend.email_crm_pipeline.email_drafter      --help
  python -m backend.email_crm_pipeline.scheduler          --help
"""
