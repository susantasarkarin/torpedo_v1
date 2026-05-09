"""
Patch traffic.py to integrate is_active_in_pool (Survey Pool layer) with yield scoring.
Three changes:
  1. Add is_active_in_pool to cint_surveys cache join projection + store in cache dict
  2. Add fast-path in _score_cint_survey to return -999.0 when is_active_in_pool==False
  3. When auto-deactivating (conv<5%), also set is_active_in_pool=False on cint_surveys
"""
import sys

TRAFFIC_PATH = r"backend\routers\traffic.py"

with open(TRAFFIC_PATH, "rb") as f:
    content = f.read()

original = content

# ── Change 1a: add is_active_in_pool to cint_surveys projection ──────────────
old1a = (
    b'                {"survey_id": 1, "total_remaining": 1, "conversion": 1,\n'
    b'                 "account_name": 1, "termination_length_of_interview": 1},\n'
)
new1a = (
    b'                {"survey_id": 1, "total_remaining": 1, "conversion": 1,\n'
    b'                 "account_name": 1, "termination_length_of_interview": 1,\n'
    b'                 "is_active_in_pool": 1},\n'
)

if old1a not in content:
    print("ERROR: Change 1a target not found"); sys.exit(1)
content = content.replace(old1a, new1a, 1)
print("OK: Change 1a applied (projection)")

# ── Change 1b: store is_active_in_pool in cache after tloi ───────────────────
old1b = (
    b'                    if new_cache[sid].get("tloi") is None:\n'
    b'                        new_cache[sid]["tloi"] = sdoc.get("termination_length_of_interview")\n'
    b'        _cint_metrics_cache = new_cache\n'
)
new1b = (
    b'                    if new_cache[sid].get("tloi") is None:\n'
    b'                        new_cache[sid]["tloi"] = sdoc.get("termination_length_of_interview")\n'
    b'                    new_cache[sid]["is_active_in_pool"] = sdoc.get("is_active_in_pool", True)\n'
    b'        _cint_metrics_cache = new_cache\n'
)
if old1b not in content:
    print("ERROR: Change 1b target not found"); sys.exit(1)
content = content.replace(old1b, new1b, 1)
print("OK: Change 1b applied (store in cache)")

# ── Change 2: fast-path in _score_cint_survey for pool exclusion ─────────────
old2 = (
    b'    # Fast-path: surveys marked inactive are guaranteed excluded from routing\n'
    b'    if metrics and metrics.get("survey_status") == "inactive":\n'
    b'        return -999.0\n'
)
new2 = (
    b'    # Fast-path: surveys marked inactive or removed from pool are excluded from routing\n'
    b'    if metrics and metrics.get("survey_status") == "inactive":\n'
    b'        return -999.0\n'
    b'    if metrics and metrics.get("is_active_in_pool") == False:\n'
    b'        return -999.0\n'
)
if old2 not in content:
    print("ERROR: Change 2 target not found"); sys.exit(1)
content = content.replace(old2, new2, 1)
print("OK: Change 2 applied (scoring fast-path)")

# ── Change 3: sync is_active_in_pool=False when auto-deactivating ────────────
old3 = (
    b'                        await _metrics_col.update_one(\n'
    b'                            {"survey_id": _sid_str},\n'
    b'                            {"$set": status_update}\n'
    b'                        )\n'
    b'                    elif entrants > 0 and current_survey_status not in ("active", "inactive"):\n'
)
new3 = (
    b'                        await _metrics_col.update_one(\n'
    b'                            {"survey_id": _sid_str},\n'
    b'                            {"$set": status_update}\n'
    b'                        )\n'
    b'                        # Sync pool flag when yield auto-deactivates\n'
    b'                        if status_update.get("survey_status") == "inactive" and _sid_str.isdigit():\n'
    b'                            _cint_surveys_col = get_async_collection("cint_research", "cint_surveys")\n'
    b'                            await _cint_surveys_col.update_one(\n'
    b'                                {"survey_id": int(_sid_str)},\n'
    b'                                {"$set": {"is_active_in_pool": False}}\n'
    b'                            )\n'
    b'                    elif entrants > 0 and current_survey_status not in ("active", "inactive"):\n'
)
if old3 not in content:
    print("ERROR: Change 3 target not found"); sys.exit(1)
content = content.replace(old3, new3, 1)
print("OK: Change 3 applied (auto-deactivation syncs pool)")

with open(TRAFFIC_PATH, "wb") as f:
    f.write(content)

print(f"\nAll 3 changes applied to {TRAFFIC_PATH}")
print(f"File size: {len(original)} -> {len(content)} bytes (+{len(content)-len(original)})")
