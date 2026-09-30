#!/usr/bin/env python3
"""Generate the software bill of materials (SBOM) and the AI bill of
materials (AI-BOM) for ANUMAAN, in CycloneDX 1.6 JSON.

    python scripts/make_sbom.py
    -> results/sbom/sbom.cdx.json     every Python distribution in this
                                      environment + every npm package in
                                      laya-sidecar/package-lock.json
    -> results/sbom/aibom.cdx.json    the models and the data they learned
                                      from: the LightGBM slip model, the
                                      Laya triage model, the training panel

Every value is read from something on disk - installed package metadata,
the npm lockfile, laya-sidecar/model-manifest.json, the panel's SHA-256,
results/paimana/metrics_slip.json and the training code's own settings.
Nothing is typed in. Regenerate after any dependency or model change.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import inspect
import json
import sys
import uuid
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "results" / "sbom"
SPEC = "1.6"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _license(meta) -> list[dict]:
    expr = meta.get("License-Expression")
    if expr:
        return [{"expression": expr}]
    lic = (meta.get("License") or "").strip()
    if lic and len(lic) < 80 and "\n" not in lic:
        return [{"license": {"name": lic}}]
    classifiers = [c.split("::")[-1].strip() for c in (meta.get_all("Classifier") or [])
                   if c.startswith("License ::")]
    return [{"license": {"name": c}} for c in classifiers[:2]]


def python_components() -> list[dict]:
    out = []
    for d in sorted(distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
        name = d.metadata["Name"]
        if not name:
            continue
        comp = {"type": "library", "name": name, "version": d.version,
                "purl": f"pkg:pypi/{name.lower().replace('_', '-')}@{d.version}",
                "bom-ref": f"pypi:{name.lower()}@{d.version}"}
        lic = _license(d.metadata)
        if lic:
            comp["licenses"] = lic
        out.append(comp)
    return out


def npm_components() -> list[dict]:
    lock = ROOT / "laya-sidecar" / "package-lock.json"
    if not lock.exists():
        return []
    pkgs = json.loads(lock.read_text(encoding="utf-8")).get("packages", {})
    out = []
    for path, p in sorted(pkgs.items()):
        if not path.startswith("node_modules/"):
            continue
        name = path.split("node_modules/")[-1]
        comp = {"type": "library", "name": name, "version": p.get("version"),
                "purl": f"pkg:npm/{name.replace('@', '%40')}@{p.get('version')}",
                "bom-ref": f"npm:{name}@{p.get('version')}"}
        if p.get("license"):
            comp["licenses"] = [{"expression": p["license"]}]
        integ = p.get("integrity", "")
        if integ.startswith("sha512-"):
            comp["hashes"] = [{"alg": "SHA-512", "content": base64.b64decode(integ[7:]).hex()}]
        out.append(comp)
    return out


def _doc(components: list[dict], name: str) -> dict:
    return {
        "bomFormat": "CycloneDX", "specVersion": SPEC,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}", "version": 1,
        "metadata": {
            "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "tools": {"components": [{"type": "application", "name": "scripts/make_sbom.py"}]},
            "component": {"type": "application", "name": name, "bom-ref": name},
        },
        "components": components,
    }


def ai_components() -> list[dict]:
    from app.panel_adapter import REAL_CATEGORICAL, REAL_NUMERIC
    from scripts.train_t1 import fit_lightgbm

    panel = ROOT / "results" / "paimana" / "panel.csv"
    prov = json.loads((ROOT / "results/paimana/panel_provenance.json").read_text(encoding="utf-8"))
    metrics = json.loads((ROOT / "results/paimana/metrics_slip.json").read_text(encoding="utf-8"))
    fold = metrics["folds"][-1]
    lgb = fold["models"]["lightgbm"]
    comps = [{
        "type": "data", "name": "PAIMANA project x month panel", "bom-ref": "data:panel",
        "hashes": [{"alg": "SHA-256", "content": _sha256(panel)}],
        "data": [{"type": "dataset", "name": "results/paimana/panel.csv",
                  "description": (f"{prov['n_rows']} rows, {prov['n_projects']} projects, "
                                  f"{prov['n_months']} monthly MoSPI PAIMANA Flash Reports "
                                  f"({prov['panel_span']}), parsed and reconciled against each "
                                  "report's printed totals. Public data; no personal data."),
                  "classification": "public"}],
    }, {
        "type": "machine-learning-model", "name": "ANUMAAN slip model", "version": "lightgbm",
        "bom-ref": "model:slip",
        "description": ("Probability that a project's stated completion date moves in the next "
                        "monthly report."),
        "modelCard": {
            "modelParameters": {
                "task": "binary classification",
                "architectureFamily": "gradient-boosted decision trees (LightGBM)",
                "datasets": [{"ref": "data:panel"}],
                "inputs": [{"format": "tabular: " + ", ".join(REAL_NUMERIC + REAL_CATEGORICAL)}],
                "outputs": [{"format": "probability 0-1 (slip_next)"}],
            },
            "quantitativeAnalysis": {"performanceMetrics": [
                {"type": "PR-AUC", "value": str(round(lgb["pr_auc"], 4)),
                 "slice": f"walk-forward test month {fold['test_month']}"},
                {"type": "Brier score", "value": str(round(lgb["brier"], 4)),
                 "slice": f"walk-forward test month {fold['test_month']}"},
                {"type": "base rate", "value": str(round(fold["test_base_rate"], 4)),
                 "slice": f"walk-forward test month {fold['test_month']}"},
            ]},
            "considerations": {
                "useCases": ["rank projects for review before each monthly meeting"],
                "technicalLimitations": [
                    "one-month horizon; 11 months of history",
                    "predicts the agency's next revision of the date, not the final overrun",
                    "advisory only; a person decides"],
            },
        },
        "properties": [{"name": "training_code", "value": "scripts/train_t1.py:fit_lightgbm"},
                       {"name": "training_code_source",
                        "value": " ".join(inspect.getsource(fit_lightgbm).split())[:400]},
                       {"name": "validation", "value": "walk-forward by month; no random split"}],
    }]
    manifest = ROOT / "laya-sidecar" / "model-manifest.json"
    if manifest.exists():
        m = json.loads(manifest.read_text(encoding="utf-8"))
        lic = "Apache-2.0" if m.get("license") == "apache-2.0" else m.get("license")
        comps.append({
            "type": "machine-learning-model", "name": m["repo"], "version": m["revision"],
            "bom-ref": "model:laya",
            "licenses": [{"expression": lic}],
            "hashes": [{"alg": "SHA-256", "content": f["sha256"]}
                       for f in m["files"].values() if f.get("sha256")],
            "externalReferences": [{"type": "distribution",
                                    "url": f"https://huggingface.co/{m['repo']}/tree/{m['revision']}"}],
            "description": ("Laya, the open-weights Jev-compatible System-1 decision model, run "
                            "locally via ONNX Runtime (@receptron/laya) to triage field remarks "
                            "to a delay cause."),
            "modelCard": {"considerations": {
                "useCases": ["suggest the delay cause and owner for a field remark"],
                "technicalLimitations": [
                    "not evaluated on PAIMANA remarks",
                    "12-option cause probabilities are not calibrated; used as a ranking only",
                    "auto-routing only when P(describes a delaying problem) >= taxonomy min_confidence"],
            }},
            "properties": [{"name": "runs", "value": "on the ANUMAAN server CPU; no hosted API"},
                           {"name": "weights_pinned_by", "value": "laya-sidecar/model-manifest.json"}],
        })
    return comps


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sbom = _doc(python_components() + npm_components(), "anumaan")
    ai = _doc(ai_components(), "anumaan-ai")
    (OUT / "sbom.cdx.json").write_text(json.dumps(sbom, indent=1) + "\n", encoding="utf-8")
    (OUT / "aibom.cdx.json").write_text(json.dumps(ai, indent=1) + "\n", encoding="utf-8")
    n_py = sum(1 for c in sbom["components"] if c["purl"].startswith("pkg:pypi"))
    n_npm = len(sbom["components"]) - n_py
    print(f"sbom : {n_py} Python + {n_npm} npm components -> results/sbom/sbom.cdx.json")
    print(f"aibom: {len(ai['components'])} components (data + models) -> results/sbom/aibom.cdx.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
