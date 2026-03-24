import re

with open('/etc/nginx/sites-enabled/campaign-platform', 'r') as f:
    content = f.read()

# Remove broken location = /index.html block inserted by sed
content = re.sub(
    r'\s*location = /index\.html \{[^}]*\}\s*\n',
    '\n',
    content,
    flags=re.DOTALL
)

# Find the first 'location / {' and insert the correct no-cache block before it
no_cache = '''    location = /index.html {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Pragma "no-cache";
        expires 0;
    }

'''

# Only add if not already there
if 'location = /index.html' not in content:
    content = content.replace('    location / {', no_cache + '    location / {', 1)

with open('/etc/nginx/sites-enabled/campaign-platform', 'w') as f:
    f.write(content)

print("Fixed. Lines:", len(content.splitlines()))
