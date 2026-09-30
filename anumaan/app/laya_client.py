#!/usr/bin/env python3
"""Client for the Laya sidecar (laya-sidecar/server.mjs).

Laya is the open-weights, Jev-compatible System-1 decision model
(@receptron/laya; weights Apache-2.0, receptron/laya-onnx). The deck rejected
Jev itself - no public weights, data location not disclosed. Laya answers the
same kind of typed question on this server's CPU, with nothing sent anywhere
else.

What ANUMAAN asks it, in ONE forward pass, about a field remark:
    describes_delay  noul    "Does the remark describe a specific problem that
                              is delaying the project?"  -> P(yes)
    cause            choice  which of the 12 causes in config/delay_taxonomy.yaml

How the answer is used - and why, measured on this model (28-29 Sep 2026):
    - The 12-option question falls in Laya's "choice:11+" calibration bucket,
      whose temperature is 0.10 (laya_config.json). Its probabilities come
      out at ~1.00 even when the top answer is wrong ("work is on track" ->
      contractor_performance at 1.00). So the cause is used as a RANKED
      SUGGESTION only; its probability is not shown as a confidence.
    - The yes/no question is a 2-option question (its own bucket). With the
      wording below and the remark alone as input it separated the 7 test
      remarks cleanly: 0.66-0.81 for the five concrete problems, 0.08 and
      0.12 for "work is on track" and "status as reported earlier".
    - So a remark is routed to the cause's owner automatically only when
      P(describes a delaying problem) >= the taxonomy's min_confidence (0.6).
      Everything else goes to the human review queue, with the suggestion
      attached. On the 7 test remarks: 7/7 correct end to end, none routed
      to a wrong owner. Seven remarks is a smoke test, not an evaluation.

What it is NOT: evaluated on PAIMANA remarks. No labelled remark set exists
yet. Every answer says so, and a person decides. The forecast model is
untouched by any of this.

Failure is explicit: sidecar not configured -> status "not_configured";
unreachable, timed out or malformed -> status "unavailable" with the reason.
Never a guessed cause.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

# Measured on the development laptop's CPU: 0.4-10 s per call, one outlier
# at 63 s. The remark is recorded first; triage is best-effort within this.
TIMEOUT_S = 30.0
DELAY_INSTRUCTIONS = ("A field official wrote this remark about an Indian central-sector "
                      "infrastructure project. Does the remark describe a specific problem "
                      "that is delaying the project?")
CAUSE_INSTRUCTIONS = "Which cause of delay does the remark describe?"


def build_questions(labels: dict) -> dict:
    criteria = {name: str(spec.get("description", ""))
                for name, spec in labels.items() if name != "unclassified"}
    return {
        "describes_delay": {"type": "noul", "instructions": DELAY_INSTRUCTIONS},
        "cause": {"type": "choice", "instructions": CAUSE_INSTRUCTIONS, "criteria": criteria},
    }


def triage(url: str | None, token: str | None, remark: str,
           labels: dict, min_confidence: float) -> dict:
    if not url or not token:
        return {"status": "not_configured",
                "note": "Laya sidecar not configured on this server; the remark is recorded "
                        "for a person to classify."}
    # The remark alone. Measured 29 Sep 2026 on the same 7 test remarks: with
    # the project name, ministry and sector added, Laya got 3/7 right end to
    # end (the rest fell below the routing threshold); with the remark alone,
    # 7/7. Project context is noise for "what is holding this up".
    state = {"remark": remark}
    body = json.dumps({"state": state, "questions": build_questions(labels)}).encode("utf-8")
    req = urllib.request.Request(url.rstrip("/") + "/v1/system-one", data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "X-Laya-Token": token})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            out = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"status": "unavailable", "reason": f"sidecar answered HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "unavailable", "reason": f"sidecar unreachable ({type(exc).__name__})"}
    except json.JSONDecodeError:
        return {"status": "unavailable", "reason": "sidecar returned invalid JSON"}
    round_trip_ms = round((time.perf_counter() - t0) * 1000, 1)

    try:
        cause = out["answers"]["cause"]
        p_delay = float(out["answers"]["describes_delay"]["noul"])
        ranked = [k for k, _ in sorted(((k, float(v)) for k, v in cause["probabilities"].items()),
                                       key=lambda kv: -kv[1])]
        top = ranked[0]
    except (KeyError, TypeError, ValueError, IndexError):
        return {"status": "unavailable", "reason": "sidecar answer did not have the expected shape"}
    if top not in labels:
        return {"status": "unavailable", "reason": "sidecar suggested a cause outside the taxonomy"}

    auto = p_delay >= min_confidence
    route = labels[top] if auto else labels.get("unclassified", {})
    return {
        "status": "ok",
        "routing": "auto" if auto else "human_review",
        "suggested_cause": top,
        "ranked_causes": ranked[:3],
        "cause_description": labels[top].get("description", ""),
        "p_describes_delay": round(p_delay, 4),
        "min_confidence": min_confidence,
        "owner": route.get("owner", "n/a"),
        "escalation": route.get("escalation", "n/a"),
        "inference_ms": out.get("ms"),
        "round_trip_ms": round_trip_ms,
        "model": f"Laya (receptron/laya-onnx @ {str(out.get('revision', ''))[:12]}), local CPU",
        "caveat": ("Suggestion only. Laya has not been evaluated on PAIMANA remarks. The cause is "
                   "a ranking; its 12-option probabilities are not calibrated, so none is shown. "
                   "A person decides."),
    }
