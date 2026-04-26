#!/bin/bash
python3 << 'PYEOF'
try:
    from google import genai
    print("NEW SDK: google.genai")
    # Test generating with new SDK
    print("genai.Client available:", hasattr(genai, 'Client'))
except ImportError:
    print("NEW SDK not available")

try:
    import google.generativeai as genai_old
    print("OLD SDK: google.generativeai")
    print("GenerativeModel available:", hasattr(genai_old, 'GenerativeModel'))
except ImportError:
    print("OLD SDK not available")
PYEOF
