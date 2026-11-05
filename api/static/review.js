// Job engine review app: Gates 2 + 3 (read the CV, write the opening, approve).
// The letter file is the source of truth; this page edits it with autosave and live checks.
// Job and letter text is only ever inserted with textContent / textarea.value.
"use strict";

const $ = (id) => document.getElementById(id);
const OPENING_RE = /<!--\s*OPENING: WRITE THIS YOURSELF[\s\S]*?-->/;
const S = { jobs: [], current: null, data: null, hash: null, dirty: false, saving: false, filter: "" };

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Job-Engine": "1" },
    body: JSON.stringify(body),
  };
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.detail || `${r.status}`); e.status = r.status; e.data = data; throw e; }
  return data;
}

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) if (c) n.append(c);
  return n;
}

const STATE_LABEL = { ready_for_review: "to review", pursued: "waiting", drafting: "drafting", approved: "approved" };

let toastTimer = null;
function toast(msg, ms = 4000) {
  $("toast-msg").textContent = msg;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, ms);
}

function confirmDialog(msg) {
  return new Promise((resolve) => {
    const d = $("confirm");
    $("confirm-msg").textContent = msg;
    const done = (v) => { d.close(); resolve(v); };
    $("confirm-yes").onclick = () => done(true);
    $("confirm-no").onclick = () => done(false);
    d.oncancel = () => resolve(false);
    d.showModal();
  });
}

// ------------------------------------------------------------------ queue

async function loadQueue() {
  const d = await api("/ui/api/review");
  S.jobs = d.jobs;
  const todo = S.jobs.filter((j) => j.state === "ready_for_review").length;
  $("tab-review-n").textContent = todo ? String(todo) : "";
  $("summary").textContent = `${todo} to review · ${S.jobs.filter((j) => j.state === "approved").length} approved`;
  renderQueue();
}

function renderQueue() {
  const f = S.filter.toLowerCase();
  const shown = S.jobs.filter((j) => !f || `${j.company} ${j.title}`.toLowerCase().includes(f));
  const list = $("queue");
  list.replaceChildren();
  let lastState = null;
  for (const j of shown) {
    if (j.state !== lastState) {
      list.append(el("li", { class: "qsection", text: { ready_for_review: "To review", pursued: "Waiting for drafting", drafting: "Drafting", approved: "Approved (step 9 packages these)" }[j.state] }));
      lastState = j.state;
    }
    const bits = [j.relative != null ? `score ${j.relative}` : null, j.cv_variant ? `CV ${j.cv_variant}` : null,
                  j.state === "ready_for_review" ? (j.opening_written ? "opening written" : "opening to write") : null,
                  j.draft_error ? "drafting failed" : null].filter(Boolean).join(" · ");
    list.append(el("li", { class: `qitem${S.current === j.id ? " active" : ""}`, tabindex: "0",
                           onclick: () => select(j.id), onkeydown: (e) => { if (e.key === "Enter") select(j.id); } },
      el("div", { class: "qt", text: `${j.company || "?"} — ${j.title}` }),
      el("div", { class: "qm" }, el("span", { class: `state ${j.state}`, text: STATE_LABEL[j.state] || j.state }), bits)));
  }
  $("queue-empty").hidden = S.jobs.length > 0;
}

// ------------------------------------------------------------------ one job

async function select(id) {
  if (S.dirty && !(await flush())) return;
  S.current = id;
  history.replaceState(null, "", `#${id}`);
  renderQueue();
  let d;
  try { d = await api(`/ui/api/review/${id}`); } catch (e) { toast(`Could not load: ${e.message}`); return; }
  S.data = d;
  S.hash = d.letter ? d.letter.hash : null;
  S.dirty = false;
  render();
}

function render() {
  const d = S.data, j = d.job;
  $("pane").hidden = false;
  $("pane-empty").hidden = true;
  $("r-title").replaceChildren(el("a", { href: j.url || "#", target: "_blank", rel: "noopener", text: j.title }));
  $("r-meta").textContent = [j.company, j.location, j.source, STATE_LABEL[j.state] || j.state].filter(Boolean).join(" · ");
  const editable = j.state === "ready_for_review";
  $("r-reopen").hidden = j.state !== "approved";
  $("r-drop").hidden = !["ready_for_review", "pursued"].includes(j.state);

  const b = $("r-banner");
  b.hidden = true; b.className = "banner"; b.replaceChildren();
  if (j.state === "pursued" && j.draft_error) {
    b.className = "banner bad";
    b.append(`Drafting failed (${j.draft_attempts} attempt${j.draft_attempts === 1 ? "" : "s"}): ${j.draft_error} `,
             el("button", { class: "btn small", text: "Retry", onclick: retry }));
    b.hidden = false;
  } else if (j.state === "pursued" || j.state === "drafting") {
    b.textContent = "The CV and letter draft are being built; this usually takes a few seconds.";
    b.hidden = false;
    setTimeout(() => { if (S.current === j.id) { loadQueue(); select(j.id); } }, 4000);
  } else if (j.state === "approved") {
    b.className = "banner";
    b.textContent = "Approved. The letter is rendered; step 9 assembles the application folder. Reopen to edit it again.";
    b.hidden = false;
  }

  // CV
  const sel = $("r-variant");
  sel.replaceChildren(...d.variants.map((v) => el("option", { value: v.id, text: `${v.id} — ${v.label}` })));
  if (d.cv) sel.value = d.cv.variant || "";
  sel.disabled = !editable;
  $("r-rebuild").disabled = true;
  $("r-cv").src = d.cv ? `/ui/files/cv/${j.id}?v=${d.cv.version}` : "about:blank";
  $("r-cv-open").href = d.cv ? `/ui/files/cv/${j.id}?v=${d.cv.version}` : "#";
  $("r-cv-open").hidden = !d.cv;
  $("r-cv-status").textContent = d.cv ? `version ${d.cv.version}, ${d.cv.ok ? "all fatal checks pass" : "a fatal check FAILS"}` : "no CV yet";
  renderChecks($("r-cv-checks"), d.cv ? d.cv.checks : [], true);

  // Letter
  const L = d.letter;
  $("r-text").value = L ? L.text : "";
  $("r-text").readOnly = !editable || !L;
  $("r-opening").hidden = !(L && L.opening_pending && editable);
  $("r-hooks").replaceChildren(...(L ? L.hooks : []).flatMap((h) => h.split(" · ")).filter(Boolean).slice(0, 14)
    .map((h) => el("span", { class: "chip", title: "Proper noun from the posting", text: h })));
  $("r-evidence").replaceChildren(...(L ? L.evidence : []).map((e) => el("li", { text: e })));
  $("r-evidence-box").hidden = !(L && L.evidence.length);
  $("r-cvread").checked = false;
  $("r-cvread").disabled = !editable;
  setSave(L ? "Saved" : "No letter draft yet");
  applyChecks(L ? L : { checks: [], prose: "" });
}

function renderChecks(ul, checks, compact = false) {
  ul.replaceChildren(...(checks || []).map((c) => {
    const cls = c.pass ? "ok" : (c.fatal === false ? "warn" : "fail");
    const mark = c.pass ? "✓" : (c.fatal === false ? "!" : "✗");
    return el("li", { class: cls, title: c.detail || "" }, el("span", { class: "mark", text: mark }),
              el("span", { text: compact ? c.check : `${c.check}: ${c.detail}` }));
  }));
}

function applyChecks(r) {
  S.lastChecks = r.checks || [];
  renderChecks($("r-checks"), S.lastChecks);
  $("r-prose").textContent = r.prose || "";
  if (typeof r.opening_pending === "boolean" && S.data.job.state === "ready_for_review" && S.data.letter)
    $("r-opening").hidden = !r.opening_pending;
  updateApprove();
}

function blocking() {
  // Everything fatal except `approved` itself, which Approve is about to set.
  return S.lastChecks.filter((c) => c.fatal !== false && !c.pass && c.check !== "approved");
}

function updateApprove() {
  const d = S.data;
  const ok = d && d.job.state === "ready_for_review" && d.letter && d.cv && d.cv.ok
             && blocking().length === 0 && $("r-cvread").checked;
  $("r-approve").disabled = !ok;
  const why = !d || !d.letter ? "No letter yet"
            : d.job.state !== "ready_for_review" ? ""
            : !d.cv?.ok ? "The CV has a failing fatal check"
            : blocking().length ? `Still failing: ${blocking().map((c) => c.check).join(", ")}`
            : !$("r-cvread").checked ? "Tick that you read the CV" : "Approve: renders the letter";
  $("r-approve").title = why;
}

function setSave(msg) { $("r-save").textContent = msg; }

// ------------------------------------------------------------------ editing

let checkTimer = null, saveTimer = null;
function onEdit() {
  S.dirty = true;
  setSave("Unsaved changes");
  clearTimeout(checkTimer);
  checkTimer = setTimeout(liveCheck, 400);
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flush, 1500);
}

async function liveCheck() {
  if (!S.data) return;
  try { applyChecks(await api(`/ui/api/review/${S.data.job.id}/check`, { text: $("r-text").value })); } catch (e) { /* next keystroke retries */ }
}

async function flush() {
  if (!S.dirty || !S.data || S.saving) return true;
  S.saving = true;
  setSave("Saving…");
  const text = $("r-text").value;
  try {
    const r = await api(`/ui/api/review/${S.data.job.id}/letter`, { text, base_hash: S.hash });
    S.hash = r.hash;
    S.dirty = $("r-text").value !== text;      // typed again while saving
    setSave(S.dirty ? "Unsaved changes" : "Saved");
    applyChecks(r);
    return true;
  } catch (e) {
    setSave(e.status === 409 ? "Conflict: the file changed on disk" : "Not saved");
    toast(e.status === 409 ? `${e.message}. Your text is still in the editor; copy it before reloading.` : `Save failed: ${e.message}`, 8000);
    return false;
  } finally {
    S.saving = false;
    if (S.dirty) { clearTimeout(saveTimer); saveTimer = setTimeout(flush, 1500); }
  }
}

function insertOpening() {
  const opening = $("r-opening-text").value.trim();
  const t = $("r-text").value;
  if (!opening || !OPENING_RE.test(t)) return;
  $("r-text").value = t.replace(OPENING_RE, opening);
  $("r-opening-text").value = "";
  $("r-insert").disabled = true;
  onEdit();
  toast("Opening placed in the letter. Read it in context and edit freely.");
}

// ------------------------------------------------------------------ actions

async function approve() {
  if (!(await flush())) return;
  try {
    await api(`/ui/api/review/${S.data.job.id}/approve`, { text: $("r-text").value, base_hash: S.hash, cv_read: $("r-cvread").checked });
    toast("Approved: letter rendered. It moves to Applications in step 9.");
    await loadQueue();
    const next = S.jobs.find((j) => j.state === "ready_for_review");
    await select(next ? next.id : S.data.job.id);
  } catch (e) {
    if (e.data && e.data.checks) applyChecks({ checks: e.data.checks, prose: $("r-prose").textContent });
    toast(e.message, 8000);
  }
}

async function simple(path, msg) {
  try { await api(`/ui/api/review/${S.data.job.id}/${path}`, {}); toast(msg); }
  catch (e) { toast(e.message, 6000); return false; }
  await loadQueue();
  return true;
}

async function retry() { if (await simple("retry", "Drafting retried")) select(S.data.job.id); }

async function rebuild() {
  const v = $("r-variant").value;
  if (!(await flush())) return;
  $("r-rebuild").disabled = true;
  setSave("Rebuilding CV…");
  try {
    const r = await api(`/ui/api/review/${S.data.job.id}/cv`, { variant: v });
    toast(`CV rebuilt as ${r.variant}. Letter: ${r.letter_note}.`, 6000);
  } catch (e) { toast(e.message, 6000); }
  await loadQueue();
  await select(S.data.job.id);
}

function wire() {
  $("queue-q").addEventListener("input", () => { S.filter = $("queue-q").value.trim(); renderQueue(); });
  $("r-text").addEventListener("input", onEdit);
  $("r-opening-text").addEventListener("input", () => { $("r-insert").disabled = !$("r-opening-text").value.trim(); });
  $("r-insert").addEventListener("click", insertOpening);
  $("r-cvread").addEventListener("change", updateApprove);
  $("r-approve").addEventListener("click", approve);
  $("r-variant").addEventListener("change", () => { $("r-rebuild").disabled = !S.data?.cv || $("r-variant").value === S.data.cv.variant; });
  $("r-rebuild").addEventListener("click", rebuild);
  $("r-preview-toggle").addEventListener("change", () => {
    const on = $("r-preview-toggle").checked;
    $("r-prose").hidden = !on; $("r-text").hidden = on;
  });
  $("r-reopen").addEventListener("click", async () => { if (await simple("reopen", "Reopened for editing")) select(S.data.job.id); });
  $("r-drop").addEventListener("click", async () => {
    if (!(await confirmDialog(`Drop “${S.data.job.company} — ${S.data.job.title}”? It is marked skipped; its files stay on disk.`))) return;
    if (await simple("drop", "Dropped")) {
      const next = S.jobs.find((j) => j.state === "ready_for_review");
      if (next) select(next.id); else { $("pane").hidden = true; $("pane-empty").hidden = false; S.data = null; }
    }
  });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); flush(); }
  });
  window.addEventListener("beforeunload", (e) => { if (S.dirty) { flush(); e.preventDefault(); } });
}

wire();
loadQueue().then(() => {
  const want = Number(location.hash.slice(1));
  const first = S.jobs.find((j) => j.id === want) || S.jobs.find((j) => j.state === "ready_for_review") || S.jobs[0];
  if (first) select(first.id);
}).catch((e) => { $("pane-empty").textContent = `Could not reach the engine: ${e.message}`; });
