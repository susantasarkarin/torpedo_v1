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
