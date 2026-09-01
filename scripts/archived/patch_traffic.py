path = r'd:\Code\03. Projects\01. torpedo wip\01. Torpedo v1 (python reacy)\backend\routers\traffic.py'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

insert_at = None
for i, line in enumerate(lines):
    if 'Vendor not found for vid' in line:
        j = i + 1
        while j < len(lines) and lines[j].strip() == '':
            j += 1
        insert_at = j
        break

if insert_at is None:
    print('NOT FOUND')
    exit(1)

if 'Append panel=' in lines[insert_at]:
    print('Already patched')
    exit(0)

print(f'Inserting at line {insert_at+1}, before: {lines[insert_at]!r}')

new_lines = [
    '        # Append panel= so the panel backend can identify the panelist\n',
    '        _panel_placeholders = {\n',
    '            "{PANEL}", "[PANEL]", "[%PANEL%]", "%PANEL%", "[PANEL%]", "{PANELIST}", "[PANELIST]"\n',
    '        }\n',
    '        raw_panel = (\n',
    '            traffic_record.get("panelId")\n',
    '            or (traffic_record.get("params") or {}).get("panel")\n',
    '            or ""\n',
    '        )\n',
    '        _panel_id = str(raw_panel).strip()[:50]\n',
    '        if _panel_id and _panel_id.upper() not in _panel_placeholders:\n',
    '            _sep = "&" if "?" in redirect_url else "?"\n',
    '            redirect_url = f"{redirect_url}{_sep}panel={_panel_id}"\n',
    '\n',
]

lines[insert_at:insert_at] = new_lines

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Done')
# Verify
with open(path, 'r', encoding='utf-8') as f:
    out = f.readlines()
for i in range(insert_at - 2, insert_at + len(new_lines) + 2):
    print(repr(out[i]))
