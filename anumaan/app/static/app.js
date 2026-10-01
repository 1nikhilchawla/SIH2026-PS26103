// ANUMAAN dashboard.
//
// Served as a file, not inline, so the Content-Security-Policy can say
// script-src 'self' and refuse every inline or injected script.
//
// Every value that reaches innerHTML goes through the h`` tag, which
// HTML-escapes each interpolation by default. Project, ministry and agency
// names come from parsed government PDFs - text we do not control - so a
// name containing markup must render as text, never execute. Only fragments
// built by h`` itself (or raw() on a constant) are inserted unescaped.

const $ = (s) => document.querySelector(s);
const fmt = (x, n = 3) => (x === null || x === undefined) ? "—" : Number(x).toFixed(n);

const ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;"};
const esc = (v) => String(v ?? "").replace(/[&<>"'`]/g, (c) => ESC[c]);
class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
// raw() is for markup this file wrote itself. Never pass it API data.
const raw = (s) => new Raw(String(s));
function h(strings, ...vals) {
  let out = strings[0];
  vals.forEach((v, i) => {
    if (v instanceof Raw) out += v.s;
    else if (Array.isArray(v)) out += v.map((x) => (x instanceof Raw ? x.s : esc(x))).join("");
    else out += esc(v);
    out += strings[i + 1];
  });
  return new Raw(out);
}
// Links from config/competitors.yaml: only http(s) may become an href, so a
// javascript: URL in a tampered config cannot run on click.
const safeUrl = (u) => (/^https?:\/\//i.test(String(u ?? "")) ? String(u) : "#");

let PROV = null;
// The horizon block travels with every scored response. The UI must render
// the label the API sends, never a hardcoded one: the real panel forecasts
// one month ahead, the synthetic one twelve.
let HORIZON = {horizon_label: "next period", target: "target", target_definition: ""};

function riskPill(p) {
  const c = p >= 0.5 ? "hi" : p >= 0.25 ? "mid" : "lo";
  return h`<span class="pill ${c}">${p.toFixed(2)}</span>`;
}

async function jget(u) { const r = await fetch(u); if (!r.ok) throw new Error(await r.text()); return r.json(); }
async function jpost(u, body, headers = {}) {
  const r = await fetch(u, {method: "POST",
    headers: {"Content-Type": "application/json", ...headers}, body: JSON.stringify(body)});
  if (!r.ok) throw new Error(await r.text()); return r.json();
}

document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav button").forEach(x => x.classList.remove("on"));
  document.querySelectorAll("section").forEach(x => x.classList.remove("on"));
  b.classList.add("on"); $("#" + b.dataset.tab).classList.add("on");
  if (b.dataset.tab === "model") loadModel();
  if (b.dataset.tab === "pipeline") loadPipeline();
  if (b.dataset.tab === "bench") loadCompetitors();
  if (b.dataset.tab === "offline") loadOffline();
});

let STATUS = null;

async function boot() {
  let s;
  try {
    s = await jget("/api/status");
  } catch (e) {
    // TypeError = no network. Anything else (401, 500) is a real error.
    if (e instanceof TypeError) return bootOffline();
    throw e;
  }
  STATUS = s;
  PROV = s.provenance;
  HORIZON = s.horizon;
  $("#cutoff").value = s.cutoff;
  const synth = PROV.data_source === "synthetic";
  const el = $("#banner");
  el.className = synth ? "synthetic" : "paimana";
  const who = s.principal.role === "open"
    ? raw(" · <span class='bad'>no login configured (development)</span>")
    : h` · signed in as <b>${s.principal.user}</b> (${s.principal.role === "ministry" ? s.principal.ministry + " only" : "all ministries"})`;
  el.innerHTML = h`${raw(synth
      ? "<b>SYNTHETIC DATA — method demonstration, not PAIMANA results.</b> "
      : "<b>PAIMANA DATA — parsed from MoSPI Flash Reports.</b> ")}Panel <code>${PROV.panel_file}</code> · ${PROV.n_projects} projects × ${PROV.n_months} months (${PROV.n_rows} rows, ${PROV.panel_span}) · model trained in this process at startup (${s.train_seconds}s, walk-forward cutoff ${s.cutoff}) · forecast horizon: <b>${HORIZON.horizon_label}</b> (<code>${HORIZON.target}</code>)${who}.`;
  loadAlerts();
}

// ---------------------------------------------------------------------------
// Offline: service worker, saved snapshot, offline watchlist
// ---------------------------------------------------------------------------

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {
    console.info("offline app shell not installed; online use is unaffected");
  });
  navigator.serviceWorker.addEventListener("message", (ev) => {
    const m = ev.data || {};
    const out = $("#off_out");
    if (!out) return;
    if (m.type === "snapshot-saved") out.textContent = `Saved for offline use: ${(m.bytes / 1024).toFixed(0)} KB, version ${m.etag}.`;
    if (m.type === "snapshot-failed") out.textContent = `Could not save (HTTP ${m.status}).`;
    if (m.type === "cleared") out.textContent = "Offline data cleared from this device.";
  });
}

function swPost(msg) {
  if (!navigator.serviceWorker || !navigator.serviceWorker.controller) {
    $("#off_out").textContent = "The offline app is still installing - reload the page once, then try again.";
    return;
  }
  navigator.serviceWorker.controller.postMessage(msg);
}

function snapshotRows(snap) {
  const d = snap.dict;
  const pick = (kind, i) => (i === null || i === undefined) ? "" : d[kind][i];
  const why = (w) => (w === null || w === undefined) ? "" : (w > 0 ? "raises: " : "lowers: ") + d.driver[Math.abs(w) - 1];
  return snap.rows.map(r => ({id: r[0], name: r[1], ministry: pick("ministry", r[2]), state: pick("state", r[4]),
    stated: r[5], original: r[6], drift: r[7], built: r[8], p: r[9], why1: why(r[10]), why2: why(r[11])}));
}

function snapshotTable(rows, limit) {
  return h`<table style="margin-top:8px"><thead><tr><th>Project</th><th>Ministry</th><th>State</th><th>Stated date</th>
    <th>Built</th><th>Score</th><th>Top driver</th></tr></thead><tbody>${rows.slice(0, limit).map(r => h`
    <tr><td><b>${r.id}</b><div class="muted">${String(r.name).slice(0, 70)}</div></td><td>${r.ministry}</td><td>${r.state}</td>
      <td>${r.stated ?? ""}</td><td>${r.built === null ? "" : r.built + "%"}</td><td>${riskPill(r.p)}</td><td class="muted">${r.why1}</td></tr>`)}</tbody></table>`;
}

async function bootOffline() {
  const el = $("#banner");
  el.className = "synthetic";
  let snap;
  try {
    snap = await jget("/api/snapshot");
  } catch (e) {
    el.textContent = "OFFLINE and nothing saved on this device. Connect once and use Offline → Save for offline use.";
    return;
  }
  // Every project, highest risk first - a fixed threshold would show an empty
  // list to a ministry whose projects all score low.
  const rows = snapshotRows(snap);
  el.innerHTML = h`<b>OFFLINE</b> — showing the copy saved on this device: forecast for ${snap.forecast_for}
    (${snap.n_projects} projects${snap.scope.ministry ? ", " + snap.scope.ministry : ""}). It updates the next time you are online.`;
  $("#alertCount").textContent = `${rows.length} projects in the saved snapshot, highest risk first${rows.length > 300 ? " (top 300 shown)" : ""}. Search, filters and project pages need a connection.`;
  $("#alertTable tbody").innerHTML = h`${rows.slice(0, 300).map(r => h`
    <tr><td><b>${r.id}</b><div class="muted">${String(r.name).slice(0, 70)}</div></td>
      <td>${r.ministry}</td><td>${r.original ?? ""}</td><td>${r.stated ?? ""}</td>
      <td>${r.drift ?? ""} mo</td><td>${riskPill(r.p)}</td><td class="muted">${r.why1}</td><td>—</td></tr>`)}`;
}

async function loadOffline() {
  const month = STATUS ? STATUS.live_forecast_month : "";
  $("#offBox").innerHTML = h`
    <div class="card"><b>Latest-report forecast</b> — every project in the ${month} report, scored in one pass
      <div class="muted">Model: same LightGBM recipe as Model Honesty, trained on every month whose outcome is already known.
      The outcome of this forecast is not known until the next report.</div>
    </div>
    <div class="card"><b>Use it without a network</b>
      <div class="row" style="margin-top:8px">
        <div class="ctl"><button class="go" id="off_save">Save for offline use</button></div>
        <div class="ctl"><button class="go" id="off_clear" style="background:#5b6575">Clear offline data</button></div>
        <div class="ctl"><a class="go" href="/api/offline-bundle" style="display:inline-block;text-decoration:none">Download offline file (HTML)</a></div>
      </div>
      <div id="off_out" class="muted">—</div>
      <div class="muted" style="margin-top:8px">
        <b>Save for offline use</b> keeps this month's forecast in this browser; the app then opens and shows it with no network.
        Re-syncing an unchanged month costs one empty 304 response. <b>Clear</b> removes it from this device - do this on shared computers.<br>
        <b>Offline file</b>: one HTML file for a pen drive or e-mail. It opens in any browser with no server, cannot make a network
        request, and checks its own SHA-256 when opened. It contains only the projects you are allowed to see.
      </div>
    </div>
    <div class="card"><b>Preview</b> — top 25 from the current snapshot<div id="off_preview" class="muted">loading…</div></div>`;
  $("#off_save").onclick = () => swPost({type: "save-snapshot"});
  $("#off_clear").onclick = () => swPost({type: "clear"});
  try {
    const snap = await jget("/api/snapshot");
    $("#off_preview").innerHTML = h`<div class="muted">${snap.n_projects} projects · model trained on ${snap.model.trained_on_months}
      · walk-forward PR-AUC of this recipe ${snap.model.walk_forward_pr_auc_lightgbm} (${snap.model.walk_forward_test_months.join(", ")})</div>${snapshotTable(snapshotRows(snap), 25)}`;
  } catch (e) { $("#off_preview").textContent = "snapshot unavailable: " + e.message; }
}

async function loadAlerts() {
  const d = await jget(`/api/projects?min_p=${encodeURIComponent($("#thr").value)}&ministry=${encodeURIComponent($("#ministry").value)}&q=${encodeURIComponent($("#q").value)}&limit=60`);
  const sel = $("#ministry");
  if (sel.options.length === 1) d.ministries.forEach(m => sel.add(new Option(m, m)));
  $("#alertCount").textContent = `${d.count} projects at or above risk ${$("#thr").value} — scored live by LightGBM on held-out months.`;
  HORIZON = d.horizon;
  $("#alertTable tbody").innerHTML = h`${d.alerts.map(a => h`
    <tr class="clickable" data-id="${a.entity_id}">
      <td><b>${a.entity_id}</b><div class="muted">${(a.project_name ?? "").slice(0, 70)}</div></td>
      <td>${a.ministry ?? ""}</td>
      <td>${a.original_doc ?? ""}</td><td>${a.stated_doc ?? ""}</td>
      <td>${a.drift_months} mo</td><td>${riskPill(a.p_slip)}</td>
      <td>${a.delay_cause}</td><td>${a.owning_authority}</td></tr>`)}`;
  document.querySelectorAll("#alertTable tbody tr").forEach(tr => tr.onclick = () => {
    $("#pid").value = tr.dataset.id;
    document.querySelector('nav button[data-tab="audit"]').click();
    loadProject(tr.dataset.id);
  });
}

$("#thr").oninput = () => { $("#thrVal").textContent = Number($("#thr").value).toFixed(2); loadAlerts(); };
$("#refresh").onclick = loadAlerts;
$("#q").onkeyup = (e) => { if (e.key === "Enter") loadAlerts(); };
$("#ministry").onchange = loadAlerts;
$("#loadProj").onclick = () => loadProject($("#pid").value.trim());

function spark(series) {
  if (!series.length) return raw("");
  const w = 420, ht = 70, n = series.length;
  const pts = series.map((s, i) => {
    const x = (i / Math.max(n - 1, 1)) * (w - 8) + 4;
    const y = ht - 6 - Number(s.p_slip) * (ht - 16);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return h`<svg width="${w}" height="${ht}" role="img" aria-label="risk over time">
    <polyline points="${pts}" fill="none" stroke="#0f62a8" stroke-width="2"/>
  </svg>`;
}

async function loadProject(id) {
  if (!id) return;
  try {
    const p = await jget("/api/project/" + encodeURIComponent(id));
    const rc = p.reference_class, b = p.behaviour;
    const maxAbs = Math.max(...p.contributions.map(c => Math.abs(c.shap)), 0.0001);
    const contribRows = p.contributions.map(c => {
      const w = Math.round(Math.abs(c.shap) / maxAbs * 100);
      const col = c.shap > 0 ? "#b3261e" : "#1e7a46";
      return h`<tr><td>${c.feature}</td><td style="text-align:right">${c.value}</td>
        <td style="width:220px"><div style="background:${col};height:11px;width:${w}%;border-radius:3px"></div></td>
        <td style="text-align:right">${c.shap > 0 ? "+" : ""}${c.shap}</td><td class="muted">${c.direction}</td></tr>`;
    });
    const flagRows = p.quality_flags.map(f =>
      h`<li><b>${f.code}</b> <span class="${f.severity === "INFO" ? "ok" : "bad"}">${f.severity}</span> — ${f.text}</li>`);
    const hist12 = p.history.slice(-12).reverse().map(r =>
      h`<tr><td>${String(r.month).slice(0, 7)}</td><td>${r.stated_doc ?? ""}</td>
        <td style="text-align:right">${r.cumulative_drift_months ?? ""}</td>
        <td style="text-align:right">${r.revisions_so_far ?? ""}</td>
        <td style="text-align:right">${fmt(r.expenditure_ratio, 3)}</td>
        <td style="text-align:right">${fmt(r.physical_progress_pct, 1)}</td>
        <td style="text-align:right">${r.silent_streak ?? r.months_since_last_revision ?? ""}</td></tr>`);
    // The rows that drove the score: the actual month-to-month date moves
    // printed in the source reports, alongside the model's own attribution.
    const evidenceRows = (p.evidence ?? []).map(e =>
      h`<tr><td>${e.from_month ?? "—"} → ${e.to_month ?? "—"}</td>
        <td>${e.what}</td><td><code>${e.detail}</code></td></tr>`);
    const f = p.forecast ?? {available: false};
    const vcol = p.p_slip >= 0.5 ? "#b3261e" : p.p_slip >= 0.25 ? "#e87722" : "#1e7a46";
    $("#projBox").innerHTML = h`
      <div class="card" style="border-left:6px solid ${vcol}">
        <b>${p.entity_id}</b> — ${(p.project_name ?? "")}<br>
        ${p.ministry ?? "—"} · sector ${p.sector ?? "—"} · agency ${p.agency ?? "—"} · ${p.state ?? "—"} ·
        approved ${String(p.approval_month ?? "").slice(0, 7)}
        <div style="margin-top:6px;font-size:15px"><b>${p.verdict}</b></div>
      </div>
      <div class="grid">
        <div class="stat"><b>${p.p_slip === null ? "—" : p.p_slip.toFixed(2)}</b><span>P(date moves in the ${HORIZON.horizon_label})</span></div>
        <div class="stat" style="background:#0f62a8"><b>${p.stated_doc ?? "—"}</b><span>agency stated completion date</span></div>
        <div class="stat" style="background:#e87722"><b>${f.available ? "+" + f.if_it_slips_p50_months + " mo" : "—"}</b><span>if it moves: median move (observed)</span></div>
        <div class="stat" style="background:#1e7a46"><b>${f.available ? "+" + Number(f.if_it_slips_p90_months).toFixed(1) + " mo" : "—"}</b><span>if it moves: 90th percentile</span></div>
      </div>

      <div class="card"><b>Why this score</b> — exact SHAP contributions for this project's latest scored month
        <table style="margin-top:6px"><thead><tr><th>Feature</th><th style="text-align:right">Value</th><th>Contribution</th><th style="text-align:right">SHAP</th><th></th></tr></thead>
        <tbody>${contribRows}</tbody></table>
        <div class="muted">Red bars push the risk up, green pull it down. Values are log-odds contributions from the trained LightGBM model, not correlations.
        ${f.available ? `Magnitudes above come from ${f.measured_on_moves} observed date moves in the training window, not from the model.` : ""}</div>
      </div>

      <div class="card"><b>The rows that drove it</b> — what the source reports actually printed
        <table style="margin-top:6px"><thead><tr><th>Between reports</th><th>What changed</th><th>Detail</th></tr></thead>
        <tbody>${evidenceRows}</tbody></table>
        <div class="muted">SHAP above says <em>how much</em> each feature moved the score. This table says <em>what happened</em> in the PDFs.
        Read them together: a large positive SHAP on drift should have a matching row here.</div>
      </div>

      <div class="card"><b>Reference class — is the model saying more than the base rate?</b>
        <table style="margin-top:6px"><tbody>
          <tr><td>This project</td><td style="text-align:right"><b>${p.p_slip === null ? "—" : (p.p_slip * 100).toFixed(1) + "%"}</b></td></tr>
          <tr><td>Sector <code>${rc.sector ?? "—"}</code> observed slip rate (held-out months)</td><td style="text-align:right">${rc.sector_slip_rate === null ? "—" : (rc.sector_slip_rate * 100).toFixed(1) + "%"}</td></tr>
          <tr><td>Ministry <code>${rc.ministry ?? "—"}</code> observed slip rate</td><td style="text-align:right">${rc.ministry_slip_rate === null ? "—" : (rc.ministry_slip_rate * 100).toFixed(1) + "%"}</td></tr>
          <tr><td>All projects, held-out months</td><td style="text-align:right">${(rc.overall_slip_rate * 100).toFixed(1)}%</td></tr>
          <tr><td>Rank by risk</td><td style="text-align:right"><b>${rc.rank ?? "—"} of ${rc.of_projects}</b> (${rc.percentile_among_projects ?? "—"}th percentile)</td></tr>
        </tbody></table>
        <div class="muted">A score that beats its reference class by a wide margin is exactly what should be reviewed — by a human, per SOURCES §6.4 on reference-class manipulation.</div>
      </div>

      <div class="card"><b>Behaviour over the whole observed history</b>
        <div class="grid" style="margin-top:8px">
          <div class="stat" style="background:#5b6575"><b>${b.months_observed}</b><span>months observed in the panel</span></div>
          <div class="stat" style="background:#5b6575"><b>${b.total_drift_months} mo</b><span>total drift since approval</span></div>
          <div class="stat" style="background:#5b6575"><b>${b.months_since_last_revision} mo</b><span>since the last date revision</span></div>
          <div class="stat" style="background:#5b6575"><b>${b.revisions_so_far}</b><span>date revisions so far</span></div>
        </div>
        <table style="margin-top:10px"><tbody>
          <tr><td>First stated completion date</td><td><b>${b.first_stated_doc ?? "—"}</b></td>
              <td>Original date at approval</td><td><b>${b.original_doc ?? "—"}</b></td></tr>
          <tr><td>Months since last revision</td><td>${b.months_since_last_revision}</td>
              <td>Silent streak</td><td>${b.silent_streak} months</td></tr>
          <tr><td>Expenditure ratio</td><td>${b.expenditure_ratio}</td>
              <td>Physical progress</td><td>${b.physical_progress_pct}%</td></tr>
          <tr><td>Spend-vs-progress divergence</td><td>${b.exp_progress_divergence}</td>
              <td>Months since approval</td><td>${b.months_since_approval}</td></tr>
        </tbody></table>
      </div>

      <div class="card"><b>Data quality flags on the latest row</b><ul style="margin:6px 0">${flagRows}</ul>
        <div class="muted">These are panel-level checks. DQ001–DQ012 run earlier, at parse time, and block rows before they ever reach the model.</div>
      </div>

      <div class="card"><b>Prescriptive Decision Support</b><br>
        Cause: <code>${p.delay_cause}</code>${p.cause_description ? " — " + p.cause_description : ""}<br>
        Owning authority: <b>${p.owning_authority}</b><br>
        Escalation path: ${p.escalation}
      </div>

      <div class="card"><b>Risk over held-out months</b><br>${spark(p.risk_series)}
        <div class="muted">${p.risk_series.length} scored months · a rising line means the model saw the drift building before the agency revised the date.</div>
      </div>

      <div class="card"><b>Last 12 reported months</b>
        <table style="margin-top:6px"><thead><tr><th>Month</th><th>Stated DoC</th><th style="text-align:right">Drift</th>
          <th style="text-align:right">Revisions</th><th style="text-align:right">Exp. ratio</th>
          <th style="text-align:right">Progress %</th><th style="text-align:right">Silent</th></tr></thead>
        <tbody>${hist12}</tbody></table>
      </div>

      <div class="card"><b>What this number is, and is not</b>
        <div class="muted" style="margin-top:4px">${p.horizon.target_definition}</div>
        <div class="muted" style="margin-top:6px"><b>It is not</b> a prediction of the final completion date, a statement that the agency is at fault,
        or a substitute for the site review. It is a calibrated probability that the <em>stated date will move</em>, scored on months the model never saw.</div>
      </div>
      <div class="card"><b>What-if — re-score live</b>
        <div class="muted">Overrides are applied to the project's latest point-in-time row and sent to the model. Nothing is read from a stored prediction, and nothing is saved.</div>
        <div class="row" style="margin-top:8px">
          <div class="ctl"><label>Cumulative drift (months)</label><input type="number" id="w_drift" step="1" min="-600" max="600"></div>
          <div class="ctl"><label>Revisions so far</label><input type="number" id="w_rev" step="1" min="0" max="100"></div>
          <div class="ctl"><label>Expenditure ratio</label><input type="number" id="w_exp" step="0.05" min="-1" max="1000"></div>
          <div class="ctl"><label>Physical progress %</label><input type="number" id="w_prog" step="1" min="0" max="100"></div>
          <div class="ctl"><button class="go" id="w_go">Score it</button></div>
        </div>
        <div id="w_out" class="muted">—</div>
      </div>
      <div class="card"><b>Field remark — what is holding this project up?</b>
        <div class="muted">A nodal officer's note. Phone numbers, e-mail, Aadhaar, PAN and account numbers are removed before it is stored.
        ${STATUS && STATUS.laya.configured
          ? "It is triaged by Laya, an open-weights model running on this server - nothing leaves it."
          : "Automatic triage (Laya) is not configured on this server; the remark is recorded for a person to classify."}
        Do not enter personal details.</div>
        <textarea id="rm_text" maxlength="1000" rows="3" style="width:100%;margin-top:8px;font:inherit;padding:6px;border:1px solid var(--line);border-radius:6px"
          placeholder="e.g. Land compensation still pending for 2 km; collector yet to hand over possession."></textarea>
        <div class="row" style="margin-top:6px"><div class="ctl"><button class="go" id="rm_go">Record remark</button></div>
          <div class="ctl muted" id="rm_out"></div></div>
        <div id="rm_list">${remarkList(p.remarks || [])}</div>
      </div>
      <div class="muted">data_source: <code>${p.provenance.data_source}</code> · panel <code>${p.provenance.panel_file}</code></div>`;
    $("#rm_go").onclick = async () => {
      const text = $("#rm_text").value.trim();
      if (text.length < 3) { $("#rm_out").textContent = "Write at least a few words."; return; }
      $("#rm_out").textContent = "recording and triaging…";
      try {
        const r = await jpost("/api/project/" + encodeURIComponent(id) + "/remark", {text});
        $("#rm_out").textContent = "recorded";
        $("#rm_text").value = "";
        const fresh = await jget("/api/project/" + encodeURIComponent(id));
        $("#rm_list").innerHTML = h`${remarkList(fresh.remarks || [])}`;
      } catch (e) { $("#rm_out").textContent = "refused: " + e.message; }
    };
    const last = p.history[p.history.length - 1] || {};
    $("#w_drift").value = last.cumulative_drift_months ?? 0;
    $("#w_rev").value = last.revisions_so_far ?? 0;
    $("#w_exp").value = last.expenditure_ratio ?? 0;
    $("#w_prog").value = last.physical_progress_pct ?? 0;
    $("#w_go").onclick = async () => {
      const body = {entity_id: id,
        cumulative_drift_months: Number($("#w_drift").value),
        revisions_so_far: Number($("#w_rev").value),
        expenditure_ratio: Number($("#w_exp").value),
        physical_progress_pct: Number($("#w_prog").value)};
      try {
        const s = await jpost("/api/score", body);
        $("#w_out").innerHTML = h`Model returned <b>${s.p_slip.toFixed(4)}</b> — P(date moves in the ${s.horizon.horizon_label})${s.forecast.available ? ` · if it moves, median +${s.forecast.if_it_slips_p50_months} mo` : ""} · computed ${s.computed_at}`;
      } catch (e) { $("#w_out").textContent = "refused: " + e.message; }
    };
  } catch (e) { $("#projBox").innerHTML = h`<span class="bad">${e.message}</span>`; }
}

function remarkList(items) {
  if (!items.length) return raw("<div class='muted' style='margin-top:6px'>No remarks recorded on this server yet.</div>");
  return h`${items.map(r => {
    const t = r.triage || {};
    const removed = Object.keys(r.personal_data_removed || {});
    const body = t.status === "ok"
      ? h`<b>${t.routing === "auto" ? "Routed" : "Needs human review"}</b> — suggested cause <code>${t.suggested_cause}</code>
          (next: ${(t.ranked_causes || []).slice(1).join(", ")}) · P(describes a delaying problem) ${fmt(t.p_describes_delay, 2)}
          (auto-route at ≥ ${t.min_confidence}) · owner: <b>${t.owner}</b> · escalation: ${t.escalation}
          <div class="muted">${t.model}, ${t.inference_ms} ms. ${t.caveat}</div>`
      : h`<span class="muted">Triage ${t.status === "not_configured" ? "not configured" : "unavailable"}${t.reason ? " (" + t.reason + ")" : ""} - recorded for a person to classify.</span>`;
    return h`<div style="border-top:1px solid var(--line);margin-top:8px;padding-top:6px">
      <div class="muted">${r.at} · ${r.by}${removed.length ? " · removed: " + removed.join(", ") : ""}</div>
      <div>${r.text}</div><div style="margin-top:4px">${body}</div></div>`;
  })}`;
}

async function loadModel() {
  const m = await jget("/api/metrics");
  const rows = Object.entries(m.models).map(([k, v]) =>
    h`<tr><td>${k}</td><td>${fmt(v.pr_auc)}</td><td>${fmt(v.brier)}</td></tr>`);
  const lk = m.leakage_check;
  // Keys come from scripts/train_t1.reliability_table(): n, mean_p, mean_y.
  const rel = m.reliability_lightgbm.map(r =>
    h`<tr><td>${fmt(r.mean_p, 3)}</td><td>${fmt(r.mean_y, 3)}</td><td>${r.n ?? ""}</td></tr>`);
  $("#trainInfo").textContent = `trained in ${m.train_seconds}s · train ${m.n_train} rows · test ${m.n_test} rows · base rate ${(m.base_rate_test * 100).toFixed(1)}%`;
  $("#modelBox").innerHTML = h`
    <div class="card"><b>Benchmarking and Comparative Analytics</b> — five models, one walk-forward split
      <table><thead><tr><th>Model</th><th>PR-AUC</th><th>Brier</th></tr></thead><tbody>${rows}</tbody></table>
      <div class="muted">Held-out base rate ${(m.base_rate_test * 100).toFixed(1)}%. Cutoff ${m.split_cutoff}. No random split anywhere.</div>
    </div>
    <div class="card"><b>Leakage guard</b><br>
      real ${fmt(lk.real_pr_auc)} · with synthetic leak ${fmt(lk.with_synthetic_leak_pr_auc)} · shuffled train ${fmt(lk.shuffled_train_pr_auc)} —
      <span class="${lk.ok ? "ok" : "bad"}">${lk.ok ? "PASS" : "FAIL"}</span>
      <div class="muted">${lk.interpretation ?? ""}</div>
    </div>
    <div class="card"><b>Calibration (10-bin, LightGBM)</b>
      <table><thead><tr><th>Mean predicted</th><th>Observed</th><th>n</th></tr></thead><tbody>${rel}</tbody></table>
    </div>`;
}

// Retrain replaces the model every viewer sees, so the server demands an
// admin token. The token is typed per use and kept only for this request -
// never stored in the page, in localStorage, or in a cookie.
$("#retrain").onclick = async () => {
  const cutoff = $("#cutoff").value.trim();
  const tok = window.prompt("Admin token (leave empty on a local development server):", "");
  if (tok === null) return;
  const headers = tok ? {"X-Admin-Token": tok} : {};
  $("#trainInfo").textContent = "training…";
  try {
    await jpost("/api/retrain", {cutoff: cutoff || null}, headers);
    await loadModel(); await loadAlerts();
  } catch (e) { $("#trainInfo").textContent = "retrain refused: " + e.message; }
};

async function loadPipeline() {
  const d = await jget("/api/pipeline");
  const man = d.real_data.manifest, rec = d.real_data.reconciliation, integ = d.integrity || {};
  $("#pipeBox").innerHTML = h`
    <div class="card"><b>Real PAIMANA corpus on disk</b>
      ${man ? h`<div class="grid" style="margin-top:8px">
        <div class="stat"><b>${man.pdfs_on_disk}</b><span>Flash Report PDFs harvested</span></div>
        <div class="stat" style="background:#1e7a46"><b>${man.sha_ok}/${man.manifest_rows}</b><span>SHA-256 verified, ${man.sha_mismatch} mismatches</span></div>
        <div class="stat" style="background:#0f62a8"><b>${Object.entries(man.fy_counts).map(([k, v]) => k + ":" + v).join("  ")}</b><span>financial-year spread</span></div>
      </div>` : raw("<div class='muted'>manifest verification not on disk</div>")}
    </div>
    <div class="card"><b>Parser reconciliation — the honest number</b>
      ${recCard(rec)}
    </div>
    <div class="card"><b>Integrity of the files this server runs on</b>
      <div class="muted">integrity/MANIFEST.json: <b>${integ.status ?? "unknown"}</b>${integ.n_files ? ` · ${integ.n_files} files` : ""}${integ.signature ? ` · signature ${integ.signature}` : ""}</div>
    </div>
    <div class="card"><b>What this means</b><div class="muted">${meaning(rec, d.serving)}</div></div>`;
}

// Every figure comes from results/paimana/reconciliation_meta.json, which
// scripts/reconciliation_meta.py rebuilds from the parser's own
// reconciliation.csv on every parse. Nothing here is typed in.
function recCard(rec) {
  if (!rec) return raw("<div class='muted'>reconciliation not on disk</div>");
  if (rec.paimana_era_reports === undefined) {
    return h`<div class="muted"><span class="bad">This reconciliation summary was written by an older parser run</span>
      (${rec.generated_by ?? "unknown"}, ${rec.generated_at ?? "unknown"}). Re-run
      <code>python scripts/reconciliation_meta.py</code> to rebuild it from <code>reconciliation.csv</code>.</div>`;
  }
  const allOk = rec.reconciled === rec.paimana_era_reports && rec.paimana_era_reports > 0;
  const rows = rec.reports.filter(r => r.era === "paimana").map(r => h`
    <tr><td>${r.report}</td><td style="text-align:right">${r.parsed_rows}</td>
      <td style="text-align:right">${r.summary_projects ?? "—"}</td>
      <td style="text-align:right">${r.quarantined_rows}</td>
      <td class="${r.status === "reconciled" ? "ok" : "bad"}">${r.status === "reconciled" ? "reconciled" : "failed"}</td></tr>`);
  return h`<div class="grid" style="margin-top:8px">
      <div class="stat" style="background:${allOk ? "#1e7a46" : "#b3261e"}"><b>${rec.reconciled}/${rec.paimana_era_reports}</b><span>PAIMANA-era reports reconcile against the totals printed inside each report</span></div>
      <div class="stat" style="background:#0f62a8"><b>${rec.rows_in_reconciled_reports}</b><span>project-month rows parsed from the reconciled reports</span></div>
      <div class="stat" style="background:#5b6575"><b>${rec.not_paimana_era_reports}</b><span>older-layout (OCMS-period) reports — not parsed yet</span></div>
    </div>
    <table style="margin-top:10px"><thead><tr><th>PAIMANA-era report</th><th style="text-align:right">Rows parsed</th>
      <th style="text-align:right">Projects printed in report</th><th style="text-align:right">Rows quarantined</th><th>Reconciliation</th></tr></thead>
      <tbody>${rows}</tbody></table>
    <div class="muted" style="margin-top:8px">A report is admitted only if its parsed rows re-add to the project count, original cost and
      expenditure printed inside that same report; otherwise it is rejected whole.
      Quarantined rows: ${rec.rows_quarantined} (${rec.quarantined_row_pct}% of rows, in ${rec.reports_with_quarantined_rows} report(s)) ·
      unparsed non-blank cells: ${rec.unparsed_nonblank_cells} ·
      status breakdown: ${Object.entries(rec.status_breakdown).map(([k, v]) => k + " = " + v).join(" · ")}.
      Source: <code>${rec.source_file}</code>, summarised ${rec.generated_at} by <code>${rec.generated_by}</code>.</div>`;
}

function meaning(rec, serving) {
  if (!rec || rec.paimana_era_reports === undefined) {
    return h`The corpus is SHA-256 verified. The reconciliation summary above is missing or out of date, so this page cannot say
      how many reports feed the panel. This app is serving <code>${serving.data_source}</code> data.`;
  }
  if (serving.data_source !== "paimana") {
    return h`The corpus is SHA-256 verified and ${rec.reconciled} of ${rec.paimana_era_reports} PAIMANA-era reports reconcile,
      but this app is serving the <code>${serving.data_source}</code> panel — a method demonstration, not those reports.`;
  }
  return h`The corpus is SHA-256 verified. Only reports that re-add to their own printed totals enter the panel:
    the ${rec.reconciled} reconciled PAIMANA-era reports supply ${rec.rows_in_reconciled_reports} rows, and the panel this app is
    serving has ${serving.n_rows} rows across ${serving.n_projects} projects (${serving.panel_span}).
    The ${rec.not_paimana_era_reports} older-layout reports are reported as not parsed rather than half-read;
    extending the parser to that layout is the next data step.`;
}

async function loadCompetitors() {
  const d = await jget("/api/competitors");
  const a = d.anumaan;
  const yn = (v) => v ? raw(`<span class="ok">yes</span>`) : raw(`<span class="bad">no</span>`);
  const rows = d.competitors.map(c => h`
    <tr>
      <td><b>${c.name}</b><div class="muted">${c.operator}</div></td>
      <td>${c.unit_of_analysis}</td>
      <td>${c.input_required}</td>
      <td style="text-align:center">${yn(c.per_project_forecast)}</td>
      <td style="text-align:center">${yn(c.calibration_published)}</td>
      <td style="text-align:center">${yn(c.leakage_test_published)}</td>
      <td>${c.cost_model}</td>
      <td class="muted">${c.verified
          ? h`<a href="${safeUrl(c.source_url)}" target="_blank" rel="noopener noreferrer">source</a> · read ${c.source_date}`
          : h`<a href="${safeUrl(c.source_url)}" target="_blank" rel="noopener noreferrer">source</a> · <span class="bad">not verified</span>`}</td>
    </tr>`);
  $("#benchBox").innerHTML = h`
    <div class="card"><b>Where ANUMAAN sits against the alternatives</b>
      <div class="muted">Competitor rows come from <code>config/competitors.yaml</code>; each carries its source link and the date we opened it.
      Rows marked <span class="bad">not verified</span> come from a search summary only — we did not open the primary page, and we say so rather than dress it up.</div>
      <div style="overflow-x:auto">
      <table style="margin-top:10px;min-width:960px"><thead><tr>
        <th>System</th><th>Unit of analysis</th><th>Input it needs</th>
        <th>Per-project forecast</th><th>Publishes calibration</th><th>Publishes leakage test</th>
        <th>Cost</th><th>Source</th>
      </tr></thead><tbody>
        ${rows}
        <tr style="background:#eef6ff">
          <td><b>${a.name}</b><div class="muted">${a.operator}</div></td>
          <td>${a.unit_of_analysis}</td>
          <td>${a.input_required}</td>
          <td style="text-align:center">${yn(a.per_project_forecast)}</td>
          <td style="text-align:center">${yn(a.calibration_published)}</td>
          <td style="text-align:center">${yn(a.leakage_test_published)}</td>
          <td>${a.cost_model}</td>
          <td class="muted">computed live from this run</td>
        </tr>
      </tbody></table></div>
    </div>

    <div class="card"><b>Our numbers — regenerated by the running process, not typed in</b>
      <div class="grid" style="margin-top:8px">
        <div class="stat"><b>${a.pr_auc_lightgbm}</b><span>PR-AUC, LightGBM, held-out months</span></div>
        <div class="stat" style="background:#0f62a8"><b>${a.uplift_vs_base_rate}×</b><span>uplift over the ${(a.base_rate * 100).toFixed(1)}% base rate</span></div>
        <div class="stat" style="background:#e87722"><b>${a.brier_lightgbm}</b><span>Brier score (lower is better)</span></div>
        <div class="stat" style="background:#1e7a46"><b>${a.calibration_bins}-bin</b><span>reliability diagram published</span></div>
      </div>
      <table style="margin-top:10px"><tbody>
        <tr><td>Leakage guard</td><td>real ${fmt(a.leakage_check.real_pr_auc)} · synthetic leak ${fmt(a.leakage_check.with_synthetic_leak_pr_auc)} · shuffled ${fmt(a.leakage_check.shuffled_train_pr_auc)} —
          <span class="${a.leakage_check.ok ? "ok" : "bad"}">${a.leakage_check.ok ? "PASS" : "FAIL"}</span></td></tr>
        <tr><td>Panel</td><td>${a.scale} · ${a.panel_rows} rows · walk-forward cutoff ${a.split_cutoff}</td></tr>
        <tr><td>Retrain time</td><td>${a.train_seconds}s — an admin can move the cutoff and watch it retrain</td></tr>
        <tr><td>Source corpus integrity</td><td>${a.corpus_pdfs_sha_verified ?? "—"} Flash Report PDFs SHA-256 verified</td></tr>
        <tr><td>Data source serving these numbers</td><td><code>${a.data_source}</code></td></tr>
      </tbody></table>
    </div>

    <div class="card"><b>What we do not claim</b>
      <div class="muted">We do not claim to be more accurate than nPlan or Primavera. Neither publishes a per-project accuracy or calibration
      figure, so there is no number to beat — and inventing a comparison would be the kind of thing this project exists to catch.
      What we claim is narrower and checkable: on the data MoSPI already publishes, we produce a forward-looking per-project probability,
      publish its calibration, publish the leakage test that protects it, and pin the source corpus by SHA-256. On the evidence we could
      verify, none of the alternatives publish all four.</div>
    </div>

    <div class="muted">Comparison file updated ${d.updated} · served from <code>config/competitors.yaml</code></div>`;
}

boot();
