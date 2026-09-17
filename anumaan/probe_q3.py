import json, pathlib
from collections import Counter

# parse_paimana.py writes rows.json to data/interim/paimana/
rows_file = pathlib.Path("data/interim/paimana/FlashReport_September_2025.rows.json")
data = json.loads(rows_file.read_text(encoding="utf-8"))
print("keys:", list(data.keys()))
print(f"parsed rows: {len(data.get('rows', []))}")
print(f"quarantined: {len(data.get('quarantined', []))}")
q = data.get("quarantined", [])
reasons = Counter(r.get("reason", "?") for r in q)
print("by reason:", dict(reasons))
print()
# Show first 5 quarantined
for r in q[:5]:
    print(json.dumps(r, indent=2, default=str)[:400])
print()
# Check rows for missing data
rows = data.get("rows", [])
n_missing_orig = sum(1 for r in rows if r.get("original_cost_cr") is None)
n_missing_state = sum(1 for r in rows if r.get("state") is None)
n_missing_proj_code = sum(1 for r in rows if r.get("project_code") is None)
print(f"rows missing original_cost_cr: {n_missing_orig}")
print(f"rows missing state: {n_missing_state}")
print(f"rows missing project_code: {n_missing_proj_code}")