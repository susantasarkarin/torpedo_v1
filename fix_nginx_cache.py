import subprocess

conf_path = '/etc/nginx/sites-enabled/campaign-platform'
with open(conf_path) as f:
    conf = f.read()

old = '''    location / {
        root /var/www/campaign_platform/Campaign_platform/dist;
        try_files $uri $uri/ /index.html;
    }'''

new = '''    # Static assets: serve directly, 404 if missing (prevents SPA HTML being cached as JS)
    location ~* ^/assets/ {
        root /var/www/campaign_platform/Campaign_platform/dist;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        try_files $uri =404;
    }

    # SPA routes: always serve index.html with no-cache header
    location / {
        root /var/www/campaign_platform/Campaign_platform/dist;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        try_files $uri $uri/ /index.html;
    }'''

if old in conf:
    conf = conf.replace(old, new, 1)
    with open(conf_path, 'w') as f:
        f.write(conf)
    print('Config updated successfully')
else:
    print('Pattern not found, showing current location / block:')
    for line in conf.split('\n'):
        if 'location' in line or 'try_files' in line or 'root' in line:
            print(line)
