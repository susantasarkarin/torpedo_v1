"""Test OpenAI Web Search on VM"""
import asyncio
from pymongo import MongoClient
from openai import OpenAI

# Get API key from MongoDB
client_db = MongoClient()
config = client_db.torpedo_settings.app_settings.find_one()
api_key = config.get('openai_api_key', '')

print(f"✅ OpenAI key: ...{api_key[-4:]}")

# Test OpenAI web search
openai_client = OpenAI(api_key=api_key)

print("\n🔍 Testing OpenAI web_search_preview...")
response = openai_client.responses.create(
    model="gpt-4o-mini",
    tools=[{"type": "web_search_preview"}],
    input="Find 3 Directors of Consumer Insights at major CPG companies on LinkedIn. Provide their names, titles, companies, and LinkedIn URLs."
)

# Extract content
content = ""
if hasattr(response, 'output'):
    for item in response.output:
        if hasattr(item, 'content'):
            for block in item.content:
                if hasattr(block, 'text'):
                    content += block.text

print("\n📋 Results:")
print("-" * 50)
print(content[:1000] if content else "No content returned")

print("\n✅ OpenAI Web Search is working on VM!")
