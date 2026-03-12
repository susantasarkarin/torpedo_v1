#!/usr/bin/env python3
"""
Fetch survey qualification data for India (IN) surveys from Cint API.

This tells us the exact Lucid question IDs used for Indian state/city profiling,
so we can populate _build_geo_profiling_params() for IN traffic.

Run on the VM:
    python check_in_qualifications.py
"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

CINT_API_BASE = "https://api.samplicio.us"
# CountryLanguageID 7 = India (English)
IN_COUNTRY_LANG_ID = 7


def main():
    api_key = os.getenv("CINT_API_KEY")
    supplier_code = os.getenv("CINT_SUPPLIER_CODE", "6777")

    if not api_key:
        print("❌ CINT_API_KEY not set in environment")
        return

    headers = {"Authorization": api_key, "Accept": "application/json"}

    print("🔍 Fetching India surveys from offerwall...")
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            f"{CINT_API_BASE}/Supply/v1/Surveys/AllOfferwall/{supplier_code}",
            headers=headers,
        )

    if resp.status_code != 200:
        print(f"❌ Offerwall API error: {resp.status_code}")
        return

    surveys = resp.json().get("Surveys", [])
    in_surveys = [s for s in surveys if s.get("CountryLanguageID") == IN_COUNTRY_LANG_ID]
    print(f"✅ Found {len(surveys)} total surveys, {len(in_surveys)} for India (CountryLanguageID={IN_COUNTRY_LANG_ID})")

    if not in_surveys:
        print("⚠️  No India surveys in offerwall right now. Try again later or check CINT_SUPPLIER_CODE.")
        return

    print(f"\n📋 Sample India survey fields (first survey):")
    first = in_surveys[0]
    for k, v in sorted(first.items()):
        print(f"  {k}: {v}")

    # Fetch qualifications for the first few IN surveys
    print(f"\n🔍 Fetching qualifications for top 5 India surveys...\n")
    question_id_tally: dict = {}

    for survey in in_surveys[:5]:
        survey_num = survey.get("SurveyNumber")
        print(f"  Survey {survey_num} (CPI={survey.get('CPI')}, IR={survey.get('BidIncidence')}, LOI={survey.get('BidLengthOfInterview')}):")

        with httpx.Client(timeout=15.0) as client:
            qual_resp = client.get(
                f"{CINT_API_BASE}/Supply/v1/SurveyQualifications/{survey_num}/{supplier_code}",
                headers=headers,
            )

        if qual_resp.status_code != 200:
            print(f"    ⚠️  Could not fetch qualifications: HTTP {qual_resp.status_code}")
            continue

        quals = qual_resp.json().get("SurveyQualifications", [])
        if not quals:
            print("    ℹ️  No qualifications (open to all)")
            continue

        for q in quals:
            qid = q.get("QuestionID")
            name = q.get("Name", "")
            precodes = q.get("Conditions", {}).get("PreCodes", [])
            print(f"    QID={qid:>5}  Name={name!r}  PreCodes={precodes[:8]}{'...' if len(precodes) > 8 else ''}")
            question_id_tally[qid] = question_id_tally.get(qid, 0) + 1

    print(f"\n📊 Question ID frequency across sampled IN surveys:")
    for qid, count in sorted(question_id_tally.items(), key=lambda x: -x[1]):
        print(f"  QID {qid}: appeared in {count}/5 surveys")

    print(f"\n💡 Key IDs to look for:")
    print(f"   42  = Age (should always appear)")
    print(f"   43  = Gender (should always appear)")
    print(f"   ??? = India State  ← look for 'state' or 'IN' in Name column")
    print(f"   ??? = India City   ← look for 'city' or 'IN' in Name column")


if __name__ == "__main__":
    main()
