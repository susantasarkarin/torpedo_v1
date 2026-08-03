# AI-Driven LinkedIn Lead Ingestion & Segmentation Module
# Architecture:
#
# ┌─────────────────────────────────────────────────────────────────┐
# │                         ADMIN UI                                │
# │   /admin/sales/campaign/list/Add Contacts/Database Connection   │
# └─────────────────────────┬───────────────────────────────────────┘
#                           │
#                           ▼
# ┌─────────────────────────────────────────────────────────────────┐
# │                      API LAYER (FastAPI)                        │
# │  POST /leads/import | POST /leads/classify | GET /leads         │
# │  POST /campaigns/{id}/attach-leads                              │
# └─────────────────────────┬───────────────────────────────────────┘
#                           │
#          ┌────────────────┼────────────────┐
#          ▼                ▼                ▼
# ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐
# │  INGESTION  │  │ ENRICHMENT  │  │   PERSISTENCE   │
# │   SERVICE   │  │  SERVICE    │  │    SERVICE      │
# │             │  │  (ChatGPT)  │  │   (MongoDB)     │
# └─────────────┘  └─────────────┘  └─────────────────┘
#
# Data Flow:
# 1. Raw leads ingested → leads_raw collection
# 2. Background worker picks up unclassified leads
# 3. ChatGPT classifies with structured JSON output
# 4. Results stored in leads_enriched + logs in lead_ai_classification_logs
# 5. UI displays classified leads with filters
# 6. User attaches leads to campaigns

# ============== COST OPTIMIZATION EXPORTS ==============

# Search Cache - reduces Google CSE API calls by 70%+
from .search_cache import (
    get_cached_response,
    cache_response,
    get_cache_stats,
    get_cache_size,
    invalidate_cache,
    get_cache_settings
)

# Deduplication - prevents duplicate leads
from .deduplication import (
    check_duplicate,
    check_duplicates_batch,
    add_to_dedup_index,
    remove_from_dedup_index,
    rebuild_dedup_index,
    get_duplicate_stats,
    normalize_linkedin_url,
    normalize_email
)

# Query Generator - AI-powered smart queries (30-40% fewer API calls)
from .query_generator import (
    generate_search_plan,
    optimize_existing_queries,
    get_query_generation_stats
)

# URL Validator - validate LinkedIn URLs before enrichment
from .url_validator import (
    validate_linkedin_url,
    validate_urls_batch,
    filter_valid_leads,
    get_validation_stats
)

# Batch Enrichment - 50% cheaper OpenAI API
from .batch_enrichment import (
    queue_leads_for_batch_enrichment,
    submit_batch_job,
    check_batch_status,
    process_batch_results,
    run_batch_enrichment_cycle,
    get_batch_stats
)

# NOTE: scheduler_optimized was removed — it was never wired to any route and
# its search call used a signature that does not exist. See RUNBOOK/git history.
