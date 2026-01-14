"""Check survey fields in MongoDB"""
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv('MONGO_URI'))

# Check CPX survey fields
cpx_db = client['cpx_research']
cpx_survey = cpx_db.cpx_surveys.find_one()
print('CPX Survey fields:', list(cpx_survey.keys()) if cpx_survey else 'None')
if cpx_survey:
    print('  status:', cpx_survey.get('status'))
    print('  is_active:', cpx_survey.get('is_active'))
    print('  loi:', cpx_survey.get('loi'))
    print('  live_link:', cpx_survey.get('live_link', '')[:50] if cpx_survey.get('live_link') else None)

# Check CINT survey fields  
cint_db = client['cint_research']
cint_survey = cint_db.cint_surveys.find_one()
print('\nCINT Survey fields:', list(cint_survey.keys()) if cint_survey else 'None')
if cint_survey:
    print('  is_active:', cint_survey.get('is_active'))
    print('  is_live:', cint_survey.get('is_live'))
    print('  length_of_interview:', cint_survey.get('length_of_interview'))
    print('  bid_length_of_interview:', cint_survey.get('bid_length_of_interview'))
    print('  loi:', cint_survey.get('loi'))
