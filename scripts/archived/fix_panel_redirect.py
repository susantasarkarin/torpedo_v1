path = r'd:\Code\03. Projects\01. torpedo wip\01. Torpedo v1 (python reacy)\backend\routers\traffic.py'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the target lines (0-indexed: 1911=else, 1912=blank, 1913=print, 1914=return)
# Verify before patching
assert 'Vendor not found for vid' in lines[1910], f"Line 1911 unexpected: {lines[1910]!r}"
assert lines[1912].strip() == '', f"Line 1913 not blank: {lines[1912]!r}"
assert 'print(f' in lines[1912] or 'print(f' in lines[1913], f"Line 1914 unexpected"

# Insert the panel_id block between the blank line and the final print
insert_at = 1912  # 0-indexed, after the blank line following "Vendor not found"

new_lines = [
    '\n',
    '        # Append panel= so the panel backend can identify the panelist\n',
    '        _placeholder_tokens = {\n',
    '            "{PANEL}", "[PANEL]", "[%PANEL%]", "%PANEL%", "[PANEL%]", "{PANELIST}", "[PANELIST]"\n',
    '        }\n',
    '        raw_panel = (\n',
    '            traffic_record.get("panelId")\n',
    '            or (traffic_record.get("params") or {}).get("panel")\n',
    '            or ""\n',
    '        )\n',
    '        panel_id = str(raw_panel).strip()[:50]\n',
    '        if panel_id and panel_id.upper() not in _placeholder_tokens:\n',
    '            sep = "&" if "?" in redirect_url else "?"\n',
    '            redirect_url = f"{redirect_url}{sep}panel={panel_id}"\n',
]

lines[insert_at:insert_at] = new_lines

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Done. Lines around insertion:")
for i in range(1910, 1932):
    print(f"{i+1}: {lines[i]}", end='')
