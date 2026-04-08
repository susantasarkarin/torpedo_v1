import subprocess

conf_path = '/etc/nginx/sites-enabled/campaign-platform'
with open(conf_path) as f:
    conf = f.read()

old = '''    # Static assets: serve directly, 404 if missing (prevents SPA HTML being cached as JS)
    location ~* ^/assets/ {
        root /var/www/campaign_platform/Campaign_platform/dist;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        try_files $uri =404;
    }'''

new = '''    # Static assets (assets/ and static/ dirs): serve directly, 404 if missing
    location ~* ^/(assets|static)/ {
        root /var/www/campaign_platform/Campaign_platform/dist;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        try_files $uri =404;
    }'''

if old in conf:
    conf = conf.replace(old, new, 1)
    with open(conf_path, 'w') as f:
        f.write(conf)
    print('Config updated successfully')
else:
    print('Pattern not found, current asset lines:')
    for line in conf.split('\n'):
        if 'assets' in line or 'static' in line:
            print(line)
