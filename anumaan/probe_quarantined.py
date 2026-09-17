"""Inspect quarantined rows for Sep 2025 to understand what's going wrong."""
import json, pathlib
from collections import Counter

interim = pathlib.Path("data/interim/paimana")
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