"""
Quick Start - OpenAI Web Search
Creates a sample web search job to test the functionality
"""
from pymongo import MongoClient
from datetime import datetime
import os
import uuid
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
jobs_db = client['email_automation']
web_search_jobs = jobs_db['web_search_jobs']

print("=" * 70)
print("OPENAI WEB SEARCH - QUICK START")
print("=" * 70)
print()

# Check if OpenAI key is configured
settings_db = client['torpedo_settings']
app_settings = settings_db['app_settings']
config = app_settings.find_one({'_id': 'app_config'})
openai_key = config.get('openai_api_key', '') if config else ''

if not openai_key:
    print("❌ OpenAI API key not found!")
    print("   Please run: python update_openai_key_interactive.py")
    exit(1)

print(f"✓ OpenAI key found: {openai_key[:10]}...{openai_key[-4:]}")
print()

# Ask for search criteria
print("Let's create a web search job!")
print()
print("Choose a search target:")
print("  1. Director of Consumer Insights (CPG/FMCG)")
print("  2. VP of Market Research (Retail)")
print("  3. Head of Customer Analytics (Technology)")
print("  4. Custom query")
print()
choice = input("Enter choice (1-4): ").strip()

if choice == "1":
    designation = "Director of Consumer Insights"
    countries = ["United States"]
    seniorities = ["Director", "VP"]
    custom_query = "Director Consumer Insights CPG FMCG LinkedIn"
elif choice == "2":
    designation = "VP Market Research"
    countries = ["United States"]
    seniorities = ["VP", "Senior Director"]
    custom_query = "VP Market Research Retail LinkedIn"
elif choice == "3":
    designation = "Head of Customer Analytics"
    countries = ["United States"]
    seniorities = ["Director", "VP"]
    custom_query = "Head Customer Analytics Technology LinkedIn"
else:
    designation = input("Enter job title (e.g., 'Director of Insights'): ").strip()
    countries_input = input("Enter countries (comma-separated, or press Enter for US): ").strip()
    countries = [c.strip() for c in countries_input.split(",")] if countries_input else ["United States"]
    custom_query = input("Enter custom search query: ").strip()
    seniorities = ["Director", "VP", "Manager"]

# Create job
job_id = str(uuid.uuid4())[:8]
job = {
    "job_id": job_id,
    "status": "pending",
    "config": {
        "designations": [designation],
        "countries": countries,
        "seniorities": seniorities,
        "custom_query": custom_query
    },
    "target_count": None,  # No limit - runs until stopped
    "total_imported": 0,
    "total_duplicates": 0,
    "total_found": 0,
    "leads_today": 0,
    "day_started": datetime.utcnow().date().isoformat(),
    "total_classified": 0,
    "emails_found": 0,
    "query_combinations": [],
    "seen_urls": [],
    "errors": [],
    "current_query": "",
    "created_at": datetime.utcnow(),
    "started_at": None,
    "last_update": datetime.utcnow(),
    "completed_at": None
}

# Insert job
web_search_jobs.insert_one(job)

print()
print("=" * 70)
print("✅ WEB SEARCH JOB CREATED!")
print("=" * 70)
print()
print(f"Job ID: {job_id}")
print(f"Search: {designation} in {', '.join(countries)}")
print(f"Query: {custom_query}")
print()
print("⚠️ IMPORTANT: The job is created but NOT RUNNING yet!")
print()
print("To start the job, you need to:")
print()
print("Option 1: Start the backend server")
print("  cd backend")
print("  python -m uvicorn main:app --reload --port 8000")
print()
print("  The background scheduler will automatically pick up and run the job.")
print()
print("Option 2: Run the job manually")
print("  python run_websearch_job.py {job_id}")
print()
print("To check job status:")
print(f"  python check_job_status.py {job_id}")
print()
print("To stop the job:")
print(f"  python stop_job.py {job_id}")
print()
print("=" * 70)
