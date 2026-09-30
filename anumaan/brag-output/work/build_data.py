"""Turn the live ANUMAAN API responses into data.js for the video.

Every number shown on screen comes from these files; nothing is typed by hand.
"""
import json
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "brag-data"
OUT = Path(__file__).resolve().parent / "data.js"

MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def mon(s):  # "2026-08-01" or "2026-08" -> "Aug 2026"
    y, m = s[:7].split("-")
    return f"{MONTHS[int(m) - 1]} {y}"


def load(name):
    return json.loads((SRC / name).read_text(encoding="utf-8"))


status = load("status.json")
metrics = load("metrics.json")
alerts = load("projects.json")["alerts"]
proj = load("p619103.json")
snap = load("snapshot.json")
snap_gzip_bytes = int((SRC / "snapshot_gzip_bytes.txt").read_text().strip())

hook_id = proj["entity_id"]
live = next(r for r in snap["rows"] if str(r[0]) == hook_id)
live = dict(zip(snap["columns"], live))

# the stated completion date, report by report: first "from" then every "to"
moves = [e["detail"].split(" (")[0].split(" -> ") for e in proj["evidence"]]
stated_seq = [moves[0][0]] + [m[1] for m in moves]
report_seq = [proj["evidence"][0]["from_month"]] + [e["to_month"] for e in proj["evidence"]]

top = metrics["reliability_lightgbm"][-1]
top_n = top["n"]
top_moved = round(top["mean_y"] * top_n)
assert abs(top["mean_y"] * top_n - top_moved) < 1e-6, "top bin count is not a whole number"

june_rows = [a for a in alerts if a["month"].startswith(metrics["split_cutoff"])]
assert june_rows and june_rows[0]["entity_id"] == hook_id, "hook project is not the top June alert"

data = {
    "hook": {
        "id": hook_id,
        "short": "Raipur–Simga highway",  # from project_name "4/6 Laning of Raipur-Simga Pkg-I"
        "state": proj["state"],
        "agency": proj["agency"],
        "original": mon(proj["original_doc"]),
        "built_pct": proj["behaviour"]["physical_progress_pct"],
        "stated_seq": [mon(s) for s in stated_seq],
        "report_seq": [mon(s) for s in report_seq],
        "june_p": proj["risk_series"][-1]["p_slip"],
        "june_rank": proj["reference_class"]["rank"],
        "june_of": proj["reference_class"]["of_projects"],
        "july_stated": mon(proj["stated_doc"]),
        "live_p": live["p"],
        "live_month": mon(snap["month"]),
    },
    "table": [
        {
            "id": a["entity_id"],
            "name": a["project_name"][:70],
            "ministry": a["ministry"],
            "original": a["original_doc"],
            "stated": a["stated_doc"],
            "drift": int(a["drift_months"]),
            "p": a["p_slip"],
        }
        for a in june_rows[:5]
    ],
    "june": mon(metrics["split_cutoff"]),
    "top_n": top_n,
    "top_moved": top_moved,
    "base_rate": metrics["base_rate_test"],
    "pr_auc": metrics["models"]["lightgbm"]["pr_auc"],
    "n_projects_live": snap["n_projects"],
    "n_projects_panel": status["provenance"]["n_projects"],
    "n_reports": status["provenance"]["n_months"],
    "n_rows": status["provenance"]["n_rows"],
    "cutoff": metrics["split_cutoff"],
    "snapshot_kb": round(snap_gzip_bytes / 1000),
}

OUT.write_text("window.DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
print(json.dumps(data, ensure_ascii=False, indent=1))
