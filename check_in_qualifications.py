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

    # Candidate API endpoint formats to try
    QUAL_ENDPOINT_VARIANTS = [
        # Lucid/Fulcrum Supply v1 variants
        lambda n: f"{CINT_API_BASE}/Supply/v1/SurveyQualifications/{n}/{supplier_code}",
        lambda n: f"{CINT_API_BASE}/Supply/v1/Surveys/{n}/Qualifications/{supplier_code}",
        lambda n: f"{CINT_API_BASE}/Supply/v1/Surveys/Qualifications/{n}/{supplier_code}",
        # Demand side (reversed)
        lambda n: f"{CINT_API_BASE}/Demand/v1/SurveyQualifications/{n}",
    ]

    # Probe first survey to find a working endpoint
    working_endpoint = None
    probe_num = in_surveys[0]["SurveyNumber"]
    print(f"\n🔍 Probing qualification endpoint with survey {probe_num}...")
    with httpx.Client(timeout=15.0) as client:
        for variant in QUAL_ENDPOINT_VARIANTS:
            url = variant(probe_num)
            r = client.get(url, headers=headers)
            print(f"  {r.status_code}  {url}")
            if r.status_code == 200:
                working_endpoint = variant
                print(f"  ✅ Found working endpoint!")
                break

    if not working_endpoint:
        print("\n⚠️  No qualification endpoint returned 200.")
        print("   The offerwall may use a different API or profile variables are embedded in the entry link SID.")
        print("   → Check the Cint Dashboard for IN survey targeting attributes to identify question IDs.")
        return

    # Fetch qualifications for the first few IN surveys
    print(f"\n🔍 Fetching qualifications for top 5 India surveys...\n")
    question_id_tally: dict = {}

    for survey in in_surveys[:5]:
        survey_num = survey.get("SurveyNumber")
        print(f"  Survey {survey_num} (CPI={survey.get('CPI')}, IR={survey.get('BidIncidence')}, LOI={survey.get('BidLengthOfInterview')}):")

        with httpx.Client(timeout=15.0) as client:
            qual_resp = client.get(working_endpoint(survey_num), headers=headers)

        if qual_resp.status_code != 200:
            print(f"    ⚠️  Could not fetch qualifications: HTTP {qual_resp.status_code}")
            continue

        # Try multiple response shapes
        body = qual_resp.json()
        quals = (
            body.get("SurveyQualifications")
            or body.get("qualifications")
            or body.get("data", {}).get("qualifications")
            or []
        )
        if not quals:
            print(f"    ℹ️  Response keys: {list(body.keys())} — no qualification list found")
            continue

        for q in quals:
            qid = q.get("QuestionID") or q.get("question_id") or q.get("id")
            name = q.get("Name") or q.get("name") or ""
            precodes = (
                q.get("Conditions", {}).get("PreCodes")
                or q.get("PreCodes")
                or q.get("precodes")
                or []
            )
            print(f"    QID={str(qid):>5}  Name={name!r}  PreCodes={precodes[:8]}{'...' if len(precodes) > 8 else ''}")
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
