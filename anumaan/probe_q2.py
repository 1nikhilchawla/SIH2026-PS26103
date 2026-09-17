import json, pathlib
from collections import Counter

# Sep 2025 summary is at data/interim/, not data/interim/paimana/
interim = pathlib.Path("data/interim")
f = interim / "FlashReport_September_2025.summary.json"
data = json.loads(f.read_text(encoding="utf-8"))
print("keys:", list(data.keys()))
q = data.get("quarantined", [])
print(f"quarantined rows: {len(q)}")
reasons = Counter(r.get("reason", "?") for r in q)
print("by reason:", dict(reasons))
# show first 5 with raw
for r in q[:5]:
    print(json.dumps(r, indent=2, default=str)[:400])
print("\n... last 5:")
for r in q[-5:]:
    print(json.dumps(r, indent=2, default=str)[:400])