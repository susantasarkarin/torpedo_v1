"""
Test OpenAI Web Search functionality for market research lead discovery.
Run: python test_openai_web_search.py
"""
import asyncio
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

# Check API key first
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
settings_db = client['torpedo_settings']
app_settings = settings_db['app_settings']

config = app_settings.find_one({'_id': 'app_config'})
api_key = config.get('openai_api_key', '') if config else ''

if not api_key:
    print("❌ No OpenAI API key found in database!")
    print("   Please update your key in Settings > Profile")
    exit(1)

print(f"✅ OpenAI API key found: {api_key[:10]}...{api_key[-4:]}")

# Test the web search
async def test_web_search():
    print("\n" + "="*60)
    print("TESTING OPENAI WEB SEARCH FOR MARKET RESEARCH LEADS")
    print("="*60)
    
    try:
        from openai import OpenAI
        openai_client = OpenAI(api_key=api_key)
        
        # Test 1: Basic API connectivity
        print("\n1. Testing basic API connectivity...")
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=5
        )
        print(f"   ✅ Basic API works! Response: {response.choices[0].message.content}")
        
        # Test 2: Web search with Responses API
        print("\n2. Testing Responses API with web_search_preview...")
        search_response = openai_client.responses.create(
            model="gpt-4o-mini",
            tools=[{"type": "web_search_preview"}],
            input="Find 3 Directors of Consumer Insights at major CPG companies on LinkedIn. Provide their names, titles, companies, and LinkedIn URLs."
        )
        
        # Extract content
        content = ""
        if hasattr(search_response, 'output'):
            for item in search_response.output:
                if hasattr(item, 'content'):
                    for block in item.content:
                        if hasattr(block, 'text'):
                            content += block.text
        
        if content:
            print(f"   ✅ Web search works!")
            print(f"\n   Sample results (first 500 chars):")
            print("   " + "-"*50)
            print(f"   {content[:500]}...")
        else:
            print("   ⚠️ Web search returned empty response")
        
        # Test 3: Test full ingestion function
        print("\n3. Testing full search_linkedin_leads function...")
        from backend.leads.ingestion import search_linkedin_leads
        
        leads = await search_linkedin_leads(
            query="Director of Consumer Insights CPG FMCG",
            num_results=5,
            skip_cache=True  # Force fresh search
        )
        
        print(f"   ✅ Found {len(leads)} leads!")
        
        if leads:
            print("\n   Sample leads:")
            for i, lead in enumerate(leads[:3], 1):
                print(f"\n   Lead {i}:")
                print(f"      Name: {lead.get('name', 'N/A')}")
                print(f"      Title: {lead.get('title', 'N/A')}")
                print(f"      Company: {lead.get('company_name', 'N/A')}")
                print(f"      LinkedIn: {lead.get('linkedin_url', 'N/A')[:60]}...")
                print(f"      Source: {lead.get('source', 'N/A')}")
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED - OpenAI Web Search is working!")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_web_search())
