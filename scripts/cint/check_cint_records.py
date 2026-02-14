from pymongo import MongoClient
import os
from dotenv import load_dotenv
from bson import ObjectId

# Load environment variables - will search for .env files in current and parent directories
load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))

try:
    # Check survey 73861459
    cint_db = client["cint_research"]
    survey = cint_db.cint_surveys.find_one({"survey_id": 73861459})
    if survey:
        print("Survey 73861459:")
        print("  country_language:", survey.get("country_language"))
        print("  country:", survey.get("country"))
        print("  is_active:", survey.get("is_active"))
        print("  is_live:", survey.get("is_live"))
    else:
        print("Survey 73861459 not found in DB")

    # Check if there are any India surveys
    print("\nIndia surveys in CINT DB:")
    india_surveys = list(cint_db.cint_surveys.find({
        "$or": [
            {"country_language": {"$regex": "IND|IN", "$options": "i"}},
            {"country": {"$regex": "IND|India", "$options": "i"}}
        ],
        "is_active": True
    }).limit(5))
    print(f"  Found: {len(india_surveys)}")
    for s in india_surveys:
        print(f"  survey_id={s.get('survey_id')} country={s.get('country_language')} active={s.get('is_active')}")

finally:
    client.close()
