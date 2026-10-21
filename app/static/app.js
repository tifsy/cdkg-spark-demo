"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TOKEN_KEY = "cdkg-app-token";
const LABEL = {
  armed_conflict: "Armed conflict", natural_hazard: "Natural hazard", displacement: "Displacement",
  epidemic: "Epidemic", food_insecurity: "Food insecurity", protection_incident: "Protection incident",
  emergency_shelter: "Emergency shelter", food_security: "Food security", wash: "WASH",
  health: "Health", protection: "Protection", education: "Education",
};
const lbl = (k) => LABEL[k] || k || "";

function token() { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; } }
async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (token()) headers["X-App-Token"] = token();
  const r = await fetch(path, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });
  if (r.status === 401) {
    const t = prompt("This server needs an access token (APP_TOKEN in .env):");
    if (t) { try { localStorage.setItem(TOKEN_KEY, t); } catch {} return api(path, opts); }
  }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
  return body;
}
const post = (p, b = {}) => api(p, { method: "POST", body: JSON.stringify(b) });

/* ---------------- status + tabs ---------------- */
let HEALTH = {};
async function loadStatus() {
  HEALTH = await api("/api/health");
  const l = HEALTH.llm;
  const pills = [
    [l.ok ? "ok" : "warn", l.provider === "mock" ? "LLM: heuristic (mock)"
      : `LLM: ${l.model}${l.ok ? "" : l.error ? " (not connected)" : " (model not available for this key)"}`, l.error || ""],
    [HEALTH.mediacloud_key ? "ok" : "warn", HEALTH.mediacloud_key ? "Media Cloud key set" : "No Media Cloud key"],
    [HEALTH.crt_mode === "live" ? "ok" : "warn", HEALTH.crt_mode === "live" ? "Review tool: live" : "Review tool: demo queue"],
  ];
  if (HEALTH.tailnet_user) pills.push(["ok", `Tailscale: ${HEALTH.tailnet_user}`]);
  $("#status").innerHTML = pills.map(([c, t, tip]) => `<span class="pill ${c}" title="${esc(tip || "")}">${esc(t)}</span>`).join("");
  if (HEALTH.tailnet_user && !$("#reviewer").value) $("#reviewer").value = HEALTH.tailnet_user;
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => {
  $$(".tabs button").forEach((x) => x.setAttribute("aria-selected", x === b));
  $$(".tab").forEach((t) => (t.hidden = t.id !== `tab-${b.dataset.tab}`));
  if (b.dataset.tab === "review") { closeDetail(false); initReview(); }
}));

/* ================= Task 1 ================= */
async function loadStats() {
  const run = $("#stats-run").value;
  const s = await api(`/api/cdkg/stats${run ? `?run_id=${encodeURIComponent(run)}` : ""}`);
  $("#stats-run").innerHTML = `<option value="">all runs</option>` + s.runs.map((r) =>
    `<option value="${r.id}" ${String(r.id) === run ? "selected" : ""}>run ${r.id}: ${esc(r.source)}, ${esc(r.started_at)}</option>`).join("");
  $("#pipe-stats").innerHTML = [
    [s.articles, "articles stored"], [s.filter_passed, "passed filter"],
    [s.mentions, "event mentions"], [s.clusters, "event clusters"],
  ].map(([n, t]) => `<div class="fig"><b>${n}</b><span>${t}</span></div>`).join("");
  const sel = $("#q-country"), cur = sel.value;
  sel.innerHTML = `<option value="">Any</option>` + s.countries.map((c) => `<option ${c === cur ? "selected" : ""}>${esc(c)}</option>`).join("");
  return s;
}

async function loadQueries() {
  const qs = await api("/api/cdkg/queries");
  $("#q-name").insertAdjacentHTML("beforeend", qs.map((q) => `<option value="${esc(q.name)}">${esc(q.label)}</option>`).join(""));
}

function range(v) { return v ? esc(v) : `<span class="muted">–</span>`; }
function clusterTable(list) {
  if (!list.length) return `<tr><td class="empty">No event clusters match. Fetch articles in step 1, or choose a different query.</td></tr>`;
  return `<thead><tr><th>Event</th><th>Place</th><th>Dates</th><th>Sources</th><th>Deaths</th><th>Displaced</th><th>Affected</th><th>Confidence</th><th>Checks</th></tr></thead><tbody>` +
    list.map((e) => `<tr data-id="${esc(e.id)}" tabindex="0">
      <td><span class="type">${esc(lbl(e.event_type))}</span><br><span class="muted">${esc(lbl(e.sector))}</span></td>
      <td>${esc(e.admin2 || e.admin1 || "")}<br><span class="muted">${esc([e.admin2 ? e.admin1 : null, e.country].filter(Boolean).join(", "))}</span></td>
      <td>${esc(e.first_date)}${e.last_date !== e.first_date ? `<br><span class="muted">to ${esc(e.last_date)}</span>` : ""}</td>
      <td class="num-cell">${e.source_count}</td>
      <td class="num-cell">${range(e.killed_range)}</td><td class="num-cell">${range(e.displaced_range)}</td><td class="num-cell">${range(e.affected_range)}</td>
      <td><span class="conf"><i style="width:${Math.round(e.confidence * 100)}%"></i></span>${e.confidence.toFixed(2)}</td>
      <td>${(e.qa_flags || []).map((f) => `<span class="flag">${esc(f.replaceAll("_", " "))}</span>`).join("")}${e.sensitive ? `<span class="flag sensitive">sensitive</span>` : ""}</td>
    </tr>`).join("") + "</tbody>";
}
function genericTable(list) {
  if (!list.length) return `<tr><td class="empty">This query returned no rows for the selected country.</td></tr>`;
  const cols = Object.keys(list[0]);
  return `<thead><tr>${cols.map((c) => `<th>${esc(c.replaceAll("_", " "))}</th>`).join("")}</tr></thead><tbody>` +
    list.map((r) => `<tr>${cols.map((c) => `<td>${esc(typeof r[c] === "boolean" ? (r[c] ? "yes" : "no") : r[c] ?? "")}</td>`).join("")}</tr>`).join("") + "</tbody>";
}

async function loadResults() {
  const name = $("#q-name").value, country = $("#q-country").value;
  closeDetail(false);
  let list, title = "Event clusters";
  if (name) {
    if (!country) { $("#res-table").innerHTML = `<tr><td class="empty">Choose a country to run this query.</td></tr>`; $("#res-count").textContent = ""; return; }
    const r = await api(`/api/cdkg/queries/${name}?country=${encodeURIComponent(country)}`);
    list = r.results; title = r.label;
  } else {
    list = await api(`/api/cdkg/events${country ? `?country=${encodeURIComponent(country)}` : ""}`);
  }
  $("#res-title").textContent = title;
  $("#res-count").textContent = `${list.length} row${list.length === 1 ? "" : "s"}`;
  const isClusters = list.length && "linkage_score" in list[0];
  $("#res-table").innerHTML = isClusters || !list.length && !name ? clusterTable(list) : genericTable(list);
  $$("#res-table tbody tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => showDetail(tr));
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showDetail(tr); } });
  });
}

/* ---------------- event detail drawer ---------------- */
const FLAG_LABEL = {
  single_source: "Single source", temporal_span_gt_7d: "Reports span more than 7 days",
  uncertain_coreference: "Uncertain merge of reports", event_date_gt_30d_before_report: "Reported more than 30 days after the event",
  contradiction_killed: "Conflicting death figures", contradiction_displaced: "Conflicting displaced figures",
  contradiction_affected: "Conflicting affected figures",
};
const flagLabel = (f) => FLAG_LABEL[f] || f.replaceAll("_", " ");
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
let detailReq = 0;

const detailOpen = () => $("#detail").classList.contains("open");
const cdkgRows = () => $$("#res-table tbody tr[data-id]");

async function showDetail(tr, { focusRow = false } = {}) {
  const drawer = $("#detail"), wasOpen = detailOpen();
  $$("#res-table tr.sel").forEach((x) => x.classList.remove("sel"));
  tr.classList.add("sel");
  tr.scrollIntoView({ block: "nearest" });
  if (focusRow) tr.focus({ preventScroll: true });
  const req = ++detailReq;
  if (!wasOpen) {
    $("#detail-title").textContent = "Loading…";
    $("#detail-body").innerHTML = "";
  }
  drawer.classList.add("open");
  document.body.classList.add("drawer-open");
  if (!wasOpen) drawer.focus();
  let d;
  try { d = await api(`/api/cdkg/events/${encodeURIComponent(tr.dataset.id)}`); }
  catch (e) {
    if (req !== detailReq) return;
    $("#detail-title").textContent = "Could not load this event";
    $("#detail-body").innerHTML = `<p class="muted">${esc(e.message)}</p>`;
    return;
  }
  if (req !== detailReq || !detailOpen()) return;   // a newer row was chosen, or the drawer was closed
  const place = [d.admin2, d.admin1, d.country].filter(Boolean);
  const dates = d.last_date && d.last_date !== d.first_date ? `${d.first_date} to ${d.last_date}` : d.first_date;
  const flags = d.qa_flags || [];
  $("#detail-title").textContent = lbl(d.event_type);
  $("#detail-body").innerHTML = `
    <p class="drawer-place">${esc(place.join(", "))}</p>
    <p class="muted">${esc(dates)} · ${esc(lbl(d.sector))}</p>
    ${d.summary ? `<p>${esc(d.summary)}</p>` : ""}
    <h3>Figures</h3>
    <div class="figures drawer-figs">
      <div class="fig"><b>${range(d.killed_range)}</b><span>Deaths</span></div>
      <div class="fig"><b>${range(d.injured_range)}</b><span>Injured</span></div>
    </div>
    <dl>
      <dt>Displaced</dt><dd>${range(d.displaced_range)}</dd>
      <dt>Affected</dt><dd>${range(d.affected_range)}</dd>
      <dt>Sources</dt><dd>${esc(d.source_count)} outlet${d.source_count === 1 ? "" : "s"}, ${esc(d.mention_count)} mention${d.mention_count === 1 ? "" : "s"}</dd>
      <dt>Linkage score</dt><dd>${esc(d.linkage_score)}</dd>
      <dt>Confidence</dt><dd>${esc(d.confidence)}</dd>
    </dl>
    <p class="hint">Differing figures are kept as a range, never averaged.</p>
    <h3>Quality checks</h3>
    ${flags.length || d.sensitive
      ? `<ul class="drawer-flags">${flags.map((f) => `<li><span class="flag">${esc(flagLabel(f))}</span></li>`).join("")}${
          d.sensitive ? `<li><span class="flag sensitive">Sensitive</span> Location detail and actors are withheld for this event type.</li>` : ""}</ul>`
      : `<p class="muted">No flags.</p>`}
    <h3>Provenance</h3>
    <ol class="mentions">${d.mentions.map((m) => `<li>
      <a href="${esc(safeUrl(m.url))}" target="_blank" rel="noopener noreferrer">${esc(m.outlet)}</a>; ${esc(m.publish_date)}; ${esc(m.language)}
      <div>${esc(m.summary)}</div>
      <div class="meta">doc ${esc(m.document_id)}; ${m.event_start ? `event date ${esc(m.event_start)}; ` : ""}${esc(m.location_text || "")} (Admin${esc(m.admin_level)}, geo ${esc(m.geo_confidence)});
        deaths ${esc(m.killed ?? "–")}; injured ${esc(m.injured ?? "–")}; displaced ${esc(m.displaced ?? "–")}; affected ${esc(m.affected ?? "–")};
        ${m.actors?.length ? `actors as reported: ${esc(m.actors.join(", "))}; ` : ""}model ${esc(m.model_version)}; conf ${esc(m.confidence)}</div>
    </li>`).join("")}</ol>`;
  $("#detail-body").scrollTop = 0;
}

function closeDetail(restoreFocus = true) {
  if (!detailOpen()) return;
  detailReq++;
  $("#detail").classList.remove("open");
  document.body.classList.remove("drawer-open");
  const sel = $("#res-table tr.sel");
  sel?.classList.remove("sel");
  if (restoreFocus) sel?.focus();
}

$("#detail-close").addEventListener("click", () => closeDetail());
document.addEventListener("click", (e) => {   // click outside closes; clicks on other rows swap the content
  if (detailOpen() && !$("#detail").contains(e.target) && !e.target.closest("#res-table tr[data-id]")) closeDetail(false);
});
document.addEventListener("keydown", (e) => {
  if (!detailOpen() || $("#tab-cdkg").hidden) return;
  if (e.key === "Escape") { e.preventDefault(); closeDetail(); return; }
  if (!["ArrowUp", "ArrowDown"].includes(e.key) || ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
  const rows = cdkgRows(), i = rows.findIndex((r) => r.classList.contains("sel"));
  const next = rows[i + (e.key === "ArrowDown" ? 1 : -1)];
  e.preventDefault();
  if (next) showDetail(next, { focusRow: e.target.matches?.("#res-table tr[data-id]") });
});

async function pollCdkg() {
  const j = await api("/api/cdkg/job");
  const el = $("#job-cdkg");
  el.classList.toggle("err", !!j.error || !!j.result?.extract?.errors);
  if (j.running) { el.textContent = `Working: ${j.step}…`; setTimeout(pollCdkg, 1500); }
  else if (j.error) el.textContent = `Stopped: ${j.error}`;
  else if (j.result) {
    const r = j.result;
    el.textContent = [r.ingest && `Loaded ${r.ingest.fetched} (${r.ingest.new_articles} new)`,
      r.filter && `filter kept ${r.filter.passed}, dropped ${r.filter.dropped}`,
      r.extract && `extracted ${r.extract.event_mentions} mentions with ${r.extract.model_versions.join(", ") || "no model"}`,
      r.extract?.errors && `${r.extract.errors} article(s) failed${r.extract.stopped ? `, ${r.extract.stopped}` : ""}`,
      r.cluster && `${r.cluster.clusters} clusters`].filter(Boolean).join("; ");
  }
  $$("#btn-ingest, #btn-pipeline").forEach((b) => (b.disabled = j.running));
  if (!j.running) { await loadStats(); await loadResults(); }
}

function syncSourceFields() {
  const src = $("#ing-source").value;
  $$("[data-for]").forEach((el) => (el.hidden = el.dataset.for !== src));
  if (src === "text") $("#ing-country").value = "";
  $("#btn-ingest").textContent = src === "text" ? "Add texts and structure" : src === "random" ? "Generate and structure" : "Fetch and structure";
}
$("#ing-source").addEventListener("change", syncSourceFields);
syncSourceFields();

async function readUpload() {
  const f = $("#ing-file").files[0];
  if (!f) return null;
  if (f.size > 5e6) throw new Error("File is larger than 5 MB. Use: python -m app.cli ingest-file <path>");
  return { text: await f.text(), filename: f.name };
}

$("#btn-ingest").addEventListener("click", async () => {
  const el = $("#job-cdkg");
  el.classList.remove("err");
  try {
    const src = $("#ing-source").value, country = $("#ing-country").value || null;
    const body = { source: src, country };
    if (src === "random") {
      Object.assign(body, { n: +$("#ing-n").value, days: +$("#ing-days-r").value,
        seed: $("#ing-seed").value === "" ? null : +$("#ing-seed").value });
    } else if (src === "text") {
      const up = await readUpload();
      Object.assign(body, up || { text: $("#ing-text").value, filename: "pasted.txt" });
      if (!body.text.trim()) throw new Error("Paste some text or choose a file first.");
    } else if (src === "mediacloud") {
      Object.assign(body, { days: +$("#ing-days").value, max_stories: +$("#ing-max").value,
        query: $("#ing-query").value.trim() || null });
    }
    await post("/api/cdkg/ingest", body);
    pollCdkg();
  } catch (e) { el.textContent = e.message; el.classList.add("err"); }
});
$("#btn-pipeline").addEventListener("click", async () => { try { await post("/api/cdkg/pipeline"); pollCdkg(); } catch (e) { alert(e.message); } });
$("#btn-reset-cdkg").addEventListener("click", async () => {
  if (!confirm("Delete all stored articles, mentions and clusters on this machine? Raw JSONL files stay in data/raw.")) return;
  await post("/api/cdkg/reset"); $("#job-cdkg").textContent = "Cleared."; await loadStats(); await loadResults();
});
$("#stats-run").addEventListener("change", loadStats);
$("#q-name").addEventListener("change", loadResults);
$("#q-country").addEventListener("change", loadResults);

/* ================= Task 2 ================= */
let REVIEW_INIT = false, FILTER = "pending", SUGS = [], ACTIVE = 0;
const qguid = () => $("#queue-guid").value.trim();

async function initReview() {
  if (REVIEW_INIT) return;
  REVIEW_INIT = true;
  const cfg = await api("/api/review/config");
  if (cfg.default_queue) $("#queue-guid").value = cfg.default_queue;
  $("#btn-reset-mock").hidden = cfg.mode !== "mock";
  try { $("#reviewer").value ||= localStorage.getItem("cdkg-reviewer") || ""; } catch {}
  if (qguid()) refreshQueue();
}

async function refreshQueue() {
  if (!qguid()) { $("#queue-info").textContent = "Paste a reviewer queue GUID to begin."; return; }
  try {
    const { queue, metrics, job } = await api(`/api/review/queues/${encodeURIComponent(qguid())}`);
    $("#queue-info").textContent = `${queue.name || "Queue"}: ${queue.undecided_count ?? "?"} sources still undecided in the review tool.`
      + (job.error && job.queue_guid === qguid() ? ` AI run problem: ${job.error}` : "");
    $("#review-metrics").innerHTML = [
      [metrics.total, "AI proposals"], [metrics.pending || 0, "waiting for a person"],
      [metrics.reviewed || 0, "confirmed"], [metrics.agreement_rate == null ? "–" : `${Math.round(metrics.agreement_rate * 100)}%`, "people agreed with AI"],
    ].map(([n, t]) => `<div class="fig"><b>${n}</b><span>${t}</span></div>`).join("");
    $("#btn-run-ai").disabled = job.running;
    $("#btn-run-ai").textContent = job.running ? `AI reviewing ${job.done}/${job.total}…` : "Run AI pre-review";
    await loadSuggestions();
    if (job.running) setTimeout(refreshQueue, 1500);
  } catch (e) { $("#queue-info").textContent = e.message; }
}

function sugItem(s, i) {
  const done = s.status === "pushed", failed = s.status === "push_failed";
  const final = s.human_decision;
  const sig = s.signals || {};
  return `<li class="sug ${done ? `done ${final}` : ""} ${failed ? "failed" : ""} ${i === ACTIVE ? "active" : ""}" data-i="${i}">
    <div>
      <h3>${esc(s.source_label)}</h3>
      <a href="${esc(s.source_homepage)}" target="_blank" rel="noopener noreferrer">${esc(s.source_homepage)}</a>
      <div class="ai-line">
        <span class="chip proposal ${esc(s.ai_decision)}">AI: ${esc(s.ai_decision)} ${(+s.ai_confidence).toFixed(2)}</span>
        ${final ? `<span class="chip decided ${esc(final)}">${esc(final)} by ${esc(s.reviewer)}</span>` : ""}
      </div>
      <div class="muted" style="font-size:.78rem;margin-top:.3rem">${esc(s.model_version)}</div>
    </div>
    <div>
      <ul>${(s.ai_reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      ${s.ai_removal_reason ? `<p style="font-size:.85rem;margin:.4rem 0 0">Removal reason: ${esc(s.ai_removal_reason)}</p>` : ""}
      <details class="evidence"><summary>What the crawler saw${sig.reachable === false ? " (site did not load)" : ""}</summary>
        <pre>${esc(JSON.stringify(sig, null, 1))}</pre></details>
    </div>
    <div class="decide">
      ${done ? `<p class="result">Sent to the review tool${s.human_note ? `: "${esc(s.human_note)}"` : "."}</p>` : `
      <div class="btns">${["keep", "remove", "skip"].map((d) => `<button data-d="${d}" class="${d === s.ai_decision ? "suggested" : ""}">${d[0].toUpperCase() + d.slice(1)}</button>`).join("")}</div>
      <input class="note" placeholder="Note (optional; removal reason if you remove)" value="">
      ${failed ? `<p class="result err">Not sent: ${esc(s.push_error)}</p>` : `<p class="result"></p>`}`}
    </div>
  </li>`;
}

async function loadSuggestions() {
  SUGS = await api(`/api/review/queues/${encodeURIComponent(qguid())}/suggestions${FILTER ? `?status=${FILTER}` : ""}`);
  ACTIVE = Math.min(ACTIVE, Math.max(0, SUGS.length - 1));
  $("#suggestions").innerHTML = SUGS.length ? SUGS.map(sugItem).join("") :
    `<li class="empty">${FILTER === "pending" ? "Nothing is waiting for you. Run the AI pre-review to create proposals." : "No items in this view."}</li>`;
  $$("#suggestions .btns button").forEach((b) => b.addEventListener("click", () => {
    const li = b.closest(".sug"); confirmDecision(+li.dataset.i, b.dataset.d);
  }));
}

async function confirmDecision(i, decision) {
  const s = SUGS[i]; if (!s || s.status === "pushed") return;
  const li = $(`.sug[data-i="${i}"]`), note = $(".note", li)?.value.trim() || null, out = $(".result", li);
  const reviewer = $("#reviewer").value.trim();
  if (!reviewer && !HEALTH.tailnet_user) { out.textContent = "Enter your name first so the decision is attributed."; out.classList.add("err"); $("#reviewer").focus(); return; }
  try { localStorage.setItem("cdkg-reviewer", reviewer); } catch {}
  $$("button", li).forEach((b) => (b.disabled = true));
  try {
    const r = await post(`/api/review/suggestions/${s.id}/confirm`, {
      decision, reviewer, note, removal_reason: decision === "remove" ? note : null,
    });
    if (r.status !== "pushed") throw new Error(r.error || "not sent");
    await refreshQueue();
  } catch (e) {
    out.textContent = `Not sent: ${e.message}`; out.classList.add("err");
    $$("button", li).forEach((b) => (b.disabled = false));
  }
}

$("#btn-run-ai").addEventListener("click", async () => {
  if (!qguid()) return;
  try { await post(`/api/review/queues/${encodeURIComponent(qguid())}/run`, { limit: 200 }); refreshQueue(); }
  catch (e) { $("#queue-info").textContent = e.message; }
});
$("#btn-reset-mock").addEventListener("click", async () => { await post("/api/review/mock/reset"); refreshQueue(); });
$("#queue-guid").addEventListener("change", refreshQueue);
$$(".filter-row button").forEach((b) => b.addEventListener("click", () => {
  $$(".filter-row button").forEach((x) => x.classList.toggle("on", x === b));
  FILTER = b.dataset.f; ACTIVE = 0; loadSuggestions();
}));

document.addEventListener("keydown", (e) => {
  if ($("#tab-review").hidden || ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
  const move = (d) => { ACTIVE = Math.max(0, Math.min(SUGS.length - 1, ACTIVE + d));
    $$(".sug").forEach((x) => x.classList.toggle("active", +x.dataset.i === ACTIVE));
    $(`.sug[data-i="${ACTIVE}"]`)?.scrollIntoView({ block: "nearest" }); };
  if (e.key === "j") move(1);
  else if (e.key === "k") move(-1);
  else if (e.key === "Enter" && SUGS[ACTIVE]) confirmDecision(ACTIVE, SUGS[ACTIVE].ai_decision);
  else if (["1", "2", "3"].includes(e.key)) confirmDecision(ACTIVE, ["keep", "remove", "skip"][+e.key - 1]);
});

/* ---------------- boot ---------------- */
(async () => {
  await loadStatus().catch(() => {});
  await loadQueries();
  await loadStats();
  await loadResults();
})();
