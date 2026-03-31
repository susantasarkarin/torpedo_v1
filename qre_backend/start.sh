#!/bin/bash
cd /var/www/campaign_platform/qre_backend
source .venv/bin/activate
exec uvicorn main:app --host 127.0.0.1 --port 8001
