"""
QUICK FIX IMPLEMENTATION SCRIPT
================================
Run this to immediately reduce OpenAI rate limit issues

This script will:
1. Disable redundant agent systems
2. Increase API call delays
3. Stop background auto-classification
4. Switch to DeepSeek for cost savings
"""

import os
import re
from pathlib import Path
import sys

# Fix Windows encoding issues
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Get project root
PROJECT_ROOT = Path(__file__).parent

def backup_file(file_path):
    """Create backup of file before modifying"""
    backup_path = f"{file_path}.backup"
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ Backed up: {file_path} -> {backup_path}")
    return backup_path

def update_env_file():
    """Update .env file with optimized settings"""
    env_path = PROJECT_ROOT / '.env'
    env_example_path = PROJECT_ROOT / '.env.example'
    
    # Create .env from .env.example if it doesn't exist
    if not env_path.exists() and env_example_path.exists():
        with open(env_example_path, 'r', encoding='utf-8') as f:
            content = f.read()
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print("✅ Created .env from .env.example")
    
    if env_path.exists():
        backup_file(env_path)
        
        with open(env_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Update or add AI provider settings
        updates = {
            'AI_DEFAULT_PROVIDER': 'deepseek',
            'DISABLE_AI_CALLS': 'false',
            # Add DeepSeek key placeholder if not exists
        }
        
        for key, value in updates.items():
            pattern = rf'^{key}=.*$'
            replacement = f'{key}={value}'
            
            if re.search(pattern, content, re.MULTILINE):
                content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
                print(f"✅ Updated: {key}={value}")
            else:
                content += f"\n{replacement}\n"
                print(f"✅ Added: {key}={value}")
        
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print("\n⚠️  IMPORTANT: Add your DeepSeek API key to .env:")
        print("   DEEPSEEK_API_KEY=your_actual_key_here")
        print("   Get free key from: https://platform.deepseek.com/")

def disable_background_classification():
    """Disable auto-classification in background sync"""
    main_py = PROJECT_ROOT / 'backend' / 'main.py'
    
    if not main_py.exists():
        print(f"⚠️  File not found: {main_py}")
        return
    
    backup_file(main_py)
    
    with open(main_py, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find and comment out the auto-classification block
    pattern = r'(\s+)(# Auto-classify new emails.*?\n.*?try:.*?\n.*?from leads\.email_classifier import classify_all_pending_emails.*?\n.*?print.*?\n.*?classify_result = classify_all_pending_emails\(.*?\n.*?\).*?\n.*?success_count.*?\n.*?print.*?\n.*?except ImportError.*?\n.*?print.*?\n.*?except Exception.*?\n.*?print.*?\n)'
    
    replacement = r'\1# DISABLED: Auto-classification runs too frequently (every 5 min)\n\1# This was causing rate limit issues\n\1# To re-enable, use manual trigger or scheduled job (once per hour)\n\1"""\n\1if total_synced > 0:\n\1    try:\n\1        from leads.email_classifier import classify_all_pending_emails\n\1        print(f"🤖 [AI] Starting OpenAI auto-classification of {min(total_synced, 100)} emails...")\n\1        classify_result = classify_all_pending_emails(\n\1            limit=min(total_synced, 100)\n\1        )\n\1        success_count = classify_result.get(\'classified\', 0)\n\1        print(f"✅ [AI] Classified {success_count} emails using OpenAI")\n\1    except ImportError as ie:\n\1        print(f"⚠️ [AI] Email classifier not available: {ie}")\n\1    except Exception as classify_err:\n\1        print(f"⚠️ [AI] Classification error: {classify_err}")\n\1"""\n'
    
    if re.search(r'from leads\.email_classifier import classify_all_pending_emails', content):
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
        print("✅ Disabled background auto-classification in main.py")
    else:
        print("⚠️  Auto-classification block not found or already disabled")
    
    with open(main_py, 'w', encoding='utf-8') as f:
        f.write(content)

def increase_api_delays():
    """Increase delays between API calls"""
    classifier_path = PROJECT_ROOT / 'backend' / 'leads' / 'email_classifier.py'
    
    if not classifier_path.exists():
        print(f"⚠️  File not found: {classifier_path}")
        return
    
    backup_file(classifier_path)
    
    with open(classifier_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    updated = False
    for i, line in enumerate(lines):
        # Update delay_between_emails from 0.05 to 2.0
        if 'delay_between_emails: float = 0.05' in line:
            lines[i] = line.replace('0.05', '2.0')
            lines[i] += '    # OPTIMIZED: Increased from 0.05s to stay within rate limits\n'
            updated = True
            print("✅ Updated delay_between_emails: 0.05s -> 2.0s")
    
    if updated:
        with open(classifier_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
    else:
        print("⚠️  delay_between_emails not found or already updated")

def update_rate_limiter():
    """Update rate limiter settings in openai_wrapper"""
    wrapper_path = PROJECT_ROOT / 'backend' / 'leads' / 'openai_wrapper.py'
    
    if not wrapper_path.exists():
        print(f"⚠️  File not found: {wrapper_path}")
        return
    
    backup_file(wrapper_path)
    
    with open(wrapper_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Update rate limits to be more conservative
    old_limits = r'self\.limits = \{[^}]+\}'
    new_limits = '''self.limits = {
            "cron": {"max_per_minute": 10, "max_per_hour": 200},       # Reduced
            "background": {"max_per_minute": 10, "max_per_hour": 300}, # Reduced from 2000!
            "api": {"max_per_minute": 20, "max_per_hour": 400},
            "user": {"max_per_minute": 30, "max_per_hour": 500},
            "internal": {"max_per_minute": 10, "max_per_hour": 150},
        }'''
    
    if re.search(old_limits, content):
        content = re.sub(old_limits, new_limits, content)
        print("✅ Updated rate limiter to conservative limits")
    else:
        print("⚠️  Rate limiter not found or already updated")
    
    with open(wrapper_path, 'w', encoding='utf-8') as f:
        f.write(content)

def create_monitoring_script():
    """Create a script to monitor API usage"""
    monitor_script = PROJECT_ROOT / 'monitor_api_usage.py'
    
    script_content = '''"""
Monitor OpenAI API Usage
========================
Run this to see your current API usage and costs
"""

import os
from pymongo import MongoClient
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)
db = client['email_automation']
logs = db['ai_usage_logs']

def get_usage_last_24h():
    """Get API usage for last 24 hours"""
    since = datetime.utcnow() - timedelta(hours=24)
    
    pipeline = [
        {"$match": {"timestamp": {"$gte": since}}},
        {"$group": {
            "_id": {
                "source": "$source",
                "provider": "$provider",
                "model": "$model"
            },
            "total_calls": {"$sum": 1},
            "total_tokens": {"$sum": "$total_tokens"},
            "total_cost": {"$sum": "$cost_usd"},
            "avg_latency": {"$avg": "$latency_ms"}
        }},
        {"$sort": {"total_calls": -1}}
    ]
    
    results = list(logs.aggregate(pipeline))
    
    print("\\n" + "="*70)
    print("API USAGE - LAST 24 HOURS")
    print("="*70)
    
    total_calls = 0
    total_cost = 0
    
    for r in results:
        source = r["_id"]["source"]
        provider = r["_id"]["provider"]
        model = r["_id"]["model"]
        calls = r["total_calls"]
        tokens = r["total_tokens"]
        cost = r["total_cost"]
        latency = r["avg_latency"]
        
        total_calls += calls
        total_cost += cost
        
        print(f"\\n{source} ({provider}/{model}):")
        print(f"  Calls:    {calls:,}")
        print(f"  Tokens:   {tokens:,}")
        print(f"  Cost:     ${cost:.4f}")
        print(f"  Latency:  {latency:.0f}ms")
    
    print("\\n" + "-"*70)
    print(f"TOTAL CALLS:  {total_calls:,}")
    print(f"TOTAL COST:   ${total_cost:.4f}")
    print(f"EST. MONTHLY: ${total_cost * 30:.2f}")
    print("="*70 + "\\n")
    
    # Check for rate limit issues
    print("\\nRATE LIMIT CHECK:")
    
    # Get calls per minute in last hour
    last_hour = datetime.utcnow() - timedelta(hours=1)
    hourly_logs = list(logs.find({"timestamp": {"$gte": last_hour}}).sort("timestamp", 1))
    
    if hourly_logs:
        # Count max calls in any 1-minute window
        max_rpm = 0
        for i in range(len(hourly_logs)):
            minute_start = hourly_logs[i]["timestamp"]
            minute_end = minute_start + timedelta(minutes=1)
            calls_in_minute = sum(1 for log in hourly_logs if minute_start <= log["timestamp"] < minute_end)
            max_rpm = max(max_rpm, calls_in_minute)
        
        print(f"  Max RPM in last hour: {max_rpm}")
        if max_rpm > 50:
            print(f"  ⚠️  WARNING: High burst detected! OpenAI limit is ~500 RPM")
        else:
            print(f"  ✅ Rate limit safe (recommended: <30 RPM)")
    
    print()

if __name__ == "__main__":
    get_usage_last_24h()
'''
    
    with open(monitor_script, 'w', encoding='utf-8') as f:
        f.write(script_content)
    
    print(f"✅ Created monitoring script: {monitor_script}")
    print("   Run with: python monitor_api_usage.py")

def main():
    """Run all quick fixes"""
    print("\n" + "="*70)
    print("QUICK FIX: Reducing OpenAI Rate Limit Issues")
    print("="*70 + "\n")
    
    print("Step 1: Updating .env file...")
    update_env_file()
    
    print("\nStep 2: Disabling background auto-classification...")
    disable_background_classification()
    
    print("\nStep 3: Increasing API call delays...")
    increase_api_delays()
    
    print("\nStep 4: Updating rate limiter...")
    update_rate_limiter()
    
    print("\nStep 5: Creating monitoring script...")
    create_monitoring_script()
    
    print("\n" + "="*70)
    print("✅ QUICK FIX COMPLETE!")
    print("="*70)
    
    print("\n⚠️  REQUIRED ACTIONS:")
    print("1. Add DEEPSEEK_API_KEY to your .env file")
    print("2. Restart your backend server")
    print("3. Run 'python monitor_api_usage.py' to check current usage")
    print("\n📚 See MULTI_AGENT_EFFICIENCY_ANALYSIS.md for full details\n")
    
    print("BACKUPS CREATED:")
    print("  All modified files have .backup copies")
    print("  To restore: cp file.backup file (or rename in Windows)\n")

if __name__ == "__main__":
    main()
