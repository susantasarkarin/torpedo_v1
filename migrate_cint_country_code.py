#!/usr/bin/env python3
"""
Migrate CINT surveys to add country_code field by mapping CountryLanguageID
"""
import pymongo
from datetime import datetime

# Cint country_language ID to country code mapping
CINT_COUNTRY_LANGUAGE_MAP = {
    1: "UK", 2: "FR", 3: "DE", 4: "NL", 5: "AU", 6: "CA", 7: "NZ", 8: "IE", 9: "US",
    10: "ES", 11: "IT", 12: "BR", 13: "MX", 14: "AR", 15: "CL", 16: "CO", 17: "PE",
    18: "AT", 19: "CH", 20: "BE", 21: "SE", 22: "NO", 23: "DK", 24: "KR", 25: "JP",
    26: "CN", 27: "IN", 28: "BE", 29: "PL", 30: "RU", 31: "TR", 32: "ZA", 33: "SG",
    34: "MY", 35: "TH", 36: "PH", 37: "ID", 38: "VN", 39: "TW", 40: "HK", 41: "AE",
    42: "SA", 43: "EG", 44: "NG", 45: "KE", 46: "GH", 47: "PT", 48: "FI", 49: "CZ",
    50: "HU", 51: "RO", 52: "GR", 53: "UA", 54: "IL", 55: "PK", 56: "BD", 57: "LK",
    86: "KZ", 146: "EU",
}

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["cint_research"]
cint_surveys = db["cint_surveys"]

print(f"🔄 Migrating CINT surveys to add country_code field\n")

# Count total surveys
total = cint_surveys.count_documents({})
print(f"📊 Total CINT surveys: {total}")

# Count surveys with no country_code
no_country_code = cint_surveys.count_documents({"country_code": {"$exists": False}})
print(f"⚠️  Surveys without country_code: {no_country_code}\n")

# Process in batches
batch_size = 1000
updated = 0
skipped = 0
failed = 0

print(f"🔄 Processing {no_country_code} surveys in batches of {batch_size}...\n")

cursor = cint_surveys.find({"country_code": {"$exists": False}})

for survey in cursor:
    try:
        survey_id = survey.get("survey_id")
        country_language = survey.get("country_language")
        
        # Try to map country_language to country_code
        country_code = None
        
        if country_language is not None:
            # If it's a number, use the mapping
            if isinstance(country_language, (int, float)):
                country_code = CINT_COUNTRY_LANGUAGE_MAP.get(int(country_language))
            # If it's a string like "eng_in", extract the country
            elif isinstance(country_language, str):
                if "_" in country_language:
                    country_code = country_language.split("_")[-1].upper()
                elif country_language.isdigit():
                    country_code = CINT_COUNTRY_LANGUAGE_MAP.get(int(country_language))
        
        # Also check raw_data for CountryLanguageID
        if not country_code and "raw_data" in survey:
            raw_country_lang_id = survey["raw_data"].get("CountryLanguageID")
            if raw_country_lang_id:
                country_code = CINT_COUNTRY_LANGUAGE_MAP.get(int(raw_country_lang_id))
        
        if country_code:
            # Update the survey with country_code
            cint_surveys.update_one(
                {"_id": survey["_id"]},
                {
                    "$set": {
                        "country_code": country_code,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            updated += 1
            
            if updated % 1000 == 0:
                print(f"  ✅ Updated {updated} surveys...")
        else:
            # No country code found, skip
            skipped += 1
            if skipped <= 5:
                print(f"  ⚠️  Survey {survey_id}: Could not map country_language={country_language}")
    
    except Exception as e:
        failed += 1
        if failed <= 5:
            print(f"  ❌ Survey {survey_id}: Error - {e}")

print(f"\n{'='*70}")
print(f"\n📊 Migration Summary:")
print(f"  ✅ Updated: {updated}")
print(f"  ⚠️  Skipped (no mapping): {skipped}")
print(f"  ❌ Failed: {failed}")

# Verify India surveys
india_count = cint_surveys.count_documents({"country_code": "IN"})
print(f"\n🇮🇳 India surveys after migration: {india_count}")

# Show sample India surveys
if india_count > 0:
    print(f"\n📋 Sample India surveys:")
    for idx, survey in enumerate(cint_surveys.find({"country_code": "IN"}).limit(5), 1):
        survey_id = survey.get("survey_id")
        name = survey.get("survey_name", "N/A")[:50]
        is_active = survey.get("is_active")
        is_live = survey.get("is_live")
        print(f"  {idx}. Survey {survey_id}: Active={is_active}, Live={is_live}")
        print(f"     {name}")

client.close()

print(f"\n✅ Migration complete! You can now query surveys by country_code.")
