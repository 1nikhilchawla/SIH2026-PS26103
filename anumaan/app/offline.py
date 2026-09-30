#!/usr/bin/env python3
"""Offline delivery: the monthly snapshot and the single-file offline bundle.

Snapshot (GET /api/snapshot)
    The forecast for every project in the latest report, in one compact,
    columnar JSON document: repeated strings (ministry, sector, State, driver
    names) are sent once in `dict` and referenced by index, probabilities are
    rounded to 3 places, dates are YYYY-MM. It carries a strong ETag, so a
    device that already holds this month's snapshot re-syncs with a
    conditional request and gets a body-less 304. The server gzips it on the
    wire. Scoped to the caller's ministry.

Offline bundle (GET /api/offline-bundle, scripts/export_offline_bundle.py)
    One self-contained HTML file with the snapshot embedded - for a pen drive,
    an e-mail attachment when the signal comes back, or a laptop at a remote
    site. It opens in any browser with no server and no connection, and its
    Content-Security-Policy is `default-src 'none'`: the file cannot load or
    send anything, so a copy that travels cannot phone home or be turned into
    a beacon. On open it recomputes the SHA-256 of its data and says whether
    it matches - that catches corruption in transfer, not deliberate
    tampering (whoever edits the data can edit the hash too).
"""
from __future__ import annotations

import base64
import hashlib
import html
import json

import numpy as np
import pandas as pd

FORMAT = "anumaan-snapshot/1"
COLUMNS = ["id", "name", "ministry", "sector", "state", "stated", "original",
           "drift", "built", "p", "why1", "why2"]


def _ym(v) -> str | None:
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
        return None
    try:
        return pd.Timestamp(v).strftime("%Y-%m")
    except (TypeError, ValueError):
        return None


def _num(v, nd: int):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else round(f, nd)


def build_snapshot(forecast: pd.DataFrame, info: dict, scope: dict) -> dict:
    """`forecast` holds one row per project for the latest report, already
    filtered to what the caller may see, sorted by p_slip descending."""
    dicts: dict[str, list[str]] = {"ministry": [], "sector": [], "state": [], "driver": []}
    index: dict[str, dict[str, int]] = {k: {} for k in dicts}

    def ref(kind: str, value) -> int | None:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return None
        s = str(value)
        if s not in index[kind]:
            index[kind][s] = len(dicts[kind])
            dicts[kind].append(s)
        return index[kind][s]

    def why(v) -> int | None:
        # signed driver reference: +k = raises risk, -k = lowers risk (k = index + 1)
        if not isinstance(v, str) or not v:
            return None
        sign = 1 if v[0] == "+" else -1
        return sign * (ref("driver", v[1:]) + 1)

    rows = []
    for r in forecast.itertuples(index=False):
        rows.append([
            str(r.entity_id), str(r.project_name) if r.project_name is not None else "",
            ref("ministry", r.ministry), ref("sector", r.sector), ref("state", r.state),
            _ym(r.stated_doc), _ym(r.original_doc),
            _num(r.cumulative_drift_months, 1), _num(r.physical_progress_pct, 1),
            _num(r.p_slip, 3), why(r.why1), why(r.why2),
        ])
    return {"format": FORMAT, **info, "scope": scope, "columns": COLUMNS,
            "dict": dicts, "n_projects": len(rows), "rows": rows}


def encode(snapshot: dict) -> tuple[bytes, str]:
    body = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return body, '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


# The bundle's only script. Kept free of template substitutions so its hash -
# and so the CSP - is a constant of this file, not of the data.
_BUNDLE_JS = """
(async function () {
  const text = document.getElementById("data").textContent;
  const snap = JSON.parse(text);
  const expected = document.body.dataset.sha256;
  const status = document.getElementById("integrity");
  try {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    const hex = Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
    const ok = hex === expected;
    status.textContent = ok
      ? "Integrity check passed: the data matches SHA-256 " + expected.slice(0, 16) + "..."
      : "INTEGRITY CHECK FAILED: this file was damaged or altered. Do not rely on it.";
    status.className = ok ? "ok" : "bad";
  } catch (e) {
    status.textContent = "This browser cannot run the integrity check; compare the SHA-256 on the title line with the one you were sent.";
  }
  const d = snap.dict;
  const pick = (kind, i) => (i === null || i === undefined) ? "" : d[kind][i];
  const why = (w) => {
    if (w === null || w === undefined) return "";
    const name = d.driver[Math.abs(w) - 1];
    return (w > 0 ? "raises: " : "lowers: ") + name;
  };
  const sel = document.getElementById("ministry");
  d.ministry.forEach((m, i) => { const o = document.createElement("option"); o.value = String(i); o.textContent = m; sel.appendChild(o); });
  const tbody = document.getElementById("rows");
  function cell(tr, v, cls) { const td = document.createElement("td"); td.textContent = v === null || v === undefined ? "" : String(v); if (cls) td.className = cls; tr.appendChild(td); }
  function render() {
    const q = document.getElementById("q").value.toLowerCase();
    const minp = Number(document.getElementById("minp").value);
    const m = sel.value;
    tbody.replaceChildren();
    let n = 0;
    for (const r of snap.rows) {
      const p = r[9];
      if (p === null || p < minp) continue;
      if (m !== "" && String(r[2]) !== m) continue;
      const hay = (r[0] + " " + r[1] + " " + pick("ministry", r[2]) + " " + pick("state", r[4])).toLowerCase();
      if (q && !hay.includes(q)) continue;
      const tr = document.createElement("tr");
      cell(tr, r[0]); cell(tr, r[1]); cell(tr, pick("ministry", r[2])); cell(tr, pick("state", r[4]));
      cell(tr, r[5]); cell(tr, r[8] === null ? "" : r[8] + "%");
      cell(tr, (p * 100).toFixed(0) + "%", p >= 0.5 ? "hi" : p >= 0.25 ? "mid" : "lo");
      cell(tr, why(r[10])); cell(tr, why(r[11]));
      tbody.appendChild(tr);
      n += 1;
    }
    document.getElementById("count").textContent = n + " of " + snap.rows.length + " projects shown, highest risk first";
  }
  for (const id of ["q", "minp", "ministry"]) document.getElementById(id).addEventListener("input", render);
  render();
})();
"""

_BUNDLE_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src '__SCRIPT_HASH__'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer">
<title>ANUMAAN offline - __MONTH__</title>
<style>
 body{font:14px/1.45 system-ui,Segoe UI,sans-serif;margin:16px;color:#1a1a1a}
 h1{font-size:19px;margin:0 0 4px;color:#1f3864} .sub{color:#5b6575;font-size:12px}
 .ok{color:#1e7a46;font-weight:700} .bad{color:#b3261e;font-weight:700}
 .box{background:#f4f7fb;border:1px solid #dde4ee;border-radius:8px;padding:10px;margin:10px 0}
 table{border-collapse:collapse;width:100%;font-size:13px} th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #dde4ee}
 th{background:#eef3fa;color:#1f3864;position:sticky;top:0} td.hi{color:#b3261e;font-weight:700} td.mid{color:#b35c00;font-weight:700} td.lo{color:#1e7a46}
 input,select{padding:5px 7px;border:1px solid #dde4ee;border-radius:6px;font:inherit}
 .row{display:flex;gap:12px;flex-wrap:wrap;align-items:end;margin:8px 0} label{display:block;font-size:12px;color:#5b6575}
</style></head>
<body data-sha256="__SHA256__">
<h1>ANUMAAN offline early warning - __MONTH__ report</h1>
<div class="sub">__SUBTITLE__</div>
<div class="box"><div id="integrity">Checking integrity...</div>
 <div class="sub">Works with no network: this file cannot load or send anything. Scores are the chance that the
 stated completion date moves in the next monthly report. Advisory only; a person decides.</div></div>
<div class="row">
 <div><label for="q">Search</label><input id="q" placeholder="project, ministry, State"></div>
 <div><label for="ministry">Ministry</label><select id="ministry"><option value="">All</option></select></div>
 <div><label for="minp">Minimum score</label><input id="minp" type="number" min="0" max="1" step="0.05" value="0"></div>
 <div class="sub" id="count"></div>
</div>
<table><thead><tr><th>ID</th><th>Project</th><th>Ministry</th><th>State</th><th>Stated date</th><th>Built</th>
<th>Score</th><th>Top driver</th><th>Second driver</th></tr></thead><tbody id="rows"></tbody></table>
<script type="application/json" id="data">__DATA__</script>
<script>__SCRIPT__</script>
</body></html>
"""


def render_bundle(snapshot: dict) -> tuple[str, str]:
    """Return (html, sha256_of_data)."""
    data = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False)
    # Inside <script type="application/json">, "<" could close the element;
    # the JSON escape keeps the text identical once parsed.
    data = data.replace("<", "\\u003c")
    sha = hashlib.sha256(data.encode("utf-8")).hexdigest()
    script_hash = "sha256-" + base64.b64encode(
        hashlib.sha256(_BUNDLE_JS.encode("utf-8")).digest()).decode("ascii")
    scope = snapshot.get("scope", {})
    subtitle = (f"{snapshot['n_projects']} projects"
                f"{' - ' + scope['ministry'] if scope.get('ministry') else ' - all ministries'}"
                f" - generated {snapshot.get('generated_at', '')} - data SHA-256 {sha[:16]}...")
    page = (_BUNDLE_HTML
            .replace("__SCRIPT_HASH__", script_hash)
            .replace("__MONTH__", html.escape(str(snapshot.get("month", ""))))
            .replace("__SUBTITLE__", html.escape(subtitle))
            .replace("__SHA256__", sha)
            .replace("__SCRIPT__", _BUNDLE_JS)
            .replace("__DATA__", data))
    return page, sha
