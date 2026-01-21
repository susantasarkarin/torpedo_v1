
from leads.openai_wrapper import chat_completion
import os
import sys

print("--------------------------------------------------")
print("🧪 Testing DeepSeek API Connection...")
print("--------------------------------------------------")

try:
    # 1. Check Payload
    messages = [{"role":"user", "content":"Hello, respond with 'DeepSeek Online'"}]
    
    # 2. Make Request
    print("Sending request to DeepSeek...")
    res = chat_completion(
        messages=messages, 
        model="deepseek-chat", 
        provider="deepseek",
        max_output_tokens=50
    )
    
    # 3. Analyze Result
    print(f"Status: {'✅ Success' if res.get('success') else '❌ Failed'}")
    
    if res.get('success'):
        print(f"Response: {res.get('content').strip()}")
        print(f"Cost: ${res.get('usage', {}).get('cost_usd', 0):.6f}")
    else:
        print(f"Error: {res.get('error')}")
        
    print("--------------------------------------------------")

except Exception as e:
    print(f"❌ Script Error: {e}")
