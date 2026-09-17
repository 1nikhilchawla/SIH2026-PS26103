import json, pathlib
from collections import Counter

rows_file = pathlib.Path("data/interim/paimana/FlashReport_September_2025.rows.json")
data = json.loads(rows_file.read_text(encoding="utf-8"))
q = data.get("quarantined", [])
reasons = Counter(r.get("reason", "?") for r in q)
print("by reason:", dict(reasons))
print()
print("WRONG_COLUMN_COUNT samples:")
for r in [x for x in q if x.get("reason") == "wrong_column_count"][:5]:
    print(f"  page {r['page']} row {r['row']}: got {r['got']} cols")
    print(f"    raw: {r['raw']}")
print()
print("NO_SERIAL_NUMBER samples:")
for r in [x for x in q if x.get("reason") == "no_serial_number"][:5]:
    print(f"  page {r['page']} row {r['row']}: cells={len(r['raw'])}")
    print(f"    raw: {r['raw']}")