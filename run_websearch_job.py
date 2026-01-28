"""
Run a specific web search job manually
Usage: python run_websearch_job.py <job_id>
"""
import sys
import asyncio
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

if len(sys.argv) < 2:
    print("Usage: python run_websearch_job.py <job_id>")
    sys.exit(1)

job_id = sys.argv[1]

# Import the job runner
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
from leads.router import run_web_search_job

print(f"Starting web search job: {job_id}")
print("Press Ctrl+C to stop")
print("-" * 60)

try:
    asyncio.run(run_web_search_job(job_id))
except KeyboardInterrupt:
    print("\n\nJob stopped by user")
except Exception as e:
    print(f"\n\nError running job: {e}")
