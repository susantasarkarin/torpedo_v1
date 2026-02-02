import os
import glob

# Try to find the file starting from current directory or typical paths
search_paths = [
    '**/backend/routers/traffic.py',
    '/root/**/backend/routers/traffic.py',
    '/var/www/**/backend/routers/traffic.py'
]

target_file = None
for pattern in search_paths:
    files = glob.glob(pattern, recursive=True)
    if files:
        target_file = files[0]
        break

if not target_file:
    print("File backend/routers/traffic.py not found")
    exit(1)

print(f"Found file at: {target_file}")

with open(target_file, 'r') as f:
    content = f.read()

# Context to match - ensure indentation matches exactly
# The file indentation seems to be spaces (32 spaces based on previous view_file?)
# Let's match a smaller unique chunk to be safe, but large enough to be unique.
# The block starts around line 762 in the provided view.

target_str = """                                # Use fetch_and_allocate_for_respondent for per-respondent API call
                                # This method:
                                # 1. Calls CPX API with traffic_id as ext_user_id
                                # 2. Applies filter settings (max_loi, min_cpi, min_ir)
                                # 3. Randomly selects one survey from filtered results
                                # 4. Generates entry link with subid_1=traffic_id
                                result = cpx_service.fetch_and_allocate_for_respondent(
                                    respondent_id=traffic_id  # Use SFWID as ext_user_id
                                )
                                
                                if result.get("success"):
                                    entry_link = result.get("entry_link", "")"""

replacement_str = """                                # Use fetch_and_allocate_for_respondent for per-respondent API call
                                # This method:
                                # 1. Calls CPX API with traffic_id as ext_user_id
                                # 2. Applies filter settings (max_loi, min_cpi, min_ir)
                                # 3. Randomly selects one survey from filtered results
                                # 4. Generates entry link with subid_1=traffic_id
                                
                                # Get client IP for correct geo-targeting
                                # This ensures the IP used to fetch surveys matches the IP used to click the link
                                forwarded = request.headers.get("X-Forwarded-For")
                                client_ip = forwarded.split(",")[0] if forwarded else request.client.host
                                print(f"📍 Detect client IP: {client_ip} for SFWID: {traffic_id}")
                                
                                result = cpx_service.fetch_and_allocate_for_respondent(
                                    respondent_id=traffic_id,  # Use SFWID as ext_user_id
                                    user_ip=client_ip          # Pass authenticated user IP
                                )
                                
                                if result.get("success"):
                                    entry_link = result.get("entry_link", "")"""

if target_str in content:
    new_content = content.replace(target_str, replacement_str)
    with open(target_file, 'w') as f:
        f.write(new_content)
    print("Successfully patched traffic.py")
elif 'client_ip = forwarded.split' in content:
    print("File already appears to be patched.")
else:
    print("Could not find exact match for replacement block.")
    # Debug: print what we see around the expected area if possible
    # Just fail for now to avoid corrupting
    exit(1)
