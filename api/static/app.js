// Job engine review app: the inbox (Gate 1).
// All job data is inserted with textContent, never innerHTML: postings are third-party text.
"use strict";

const $ = (id) => document.getElementById(id);
const state = { jobs: [], focus: 0, selected: new Set(), undo: [], filters: { q: "", source: "", archetype: "" } };

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Job-Engine": "1" },
    body: JSON.stringify(body),
  };
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
  return r.json();
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

function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

// Collapsed view: one paragraph. Expanded view: keep paragraphs, drop runs of blank lines.
const oneLine = (t) => String(t || "").replace(/\s+/g, " ").trim();
const tidy = (t) => String(t || "").replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();

function fmtDate(iso) {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

// ------------------------------------------------------------------ summary + banner

async function loadSummary() {
  const s = await api("/ui/api/summary");
  const d = s.digest;
  const waiting = s.by_state.scored || 0;
  const t = s.decided_today || {};
  $("tab-inbox-n").textContent = waiting ? String(waiting) : "";
  const parts = [`${waiting} waiting`];
  if (t.pursued || t.skipped) parts.push(`today: ${t.pursued || 0} pursued, ${t.skipped || 0} skipped`);
  if (d) parts.push(`last run ${ago(d.created_at)}${d.status === "ok" ? ` (+${d.new_count})` : ""}`);
  $("summary").textContent = parts.join(" · ");

  const b = $("run-banner");
  b.replaceChildren();
  b.hidden = true;
  b.className = "banner";
  if (d && d.status === "failed") {
    b.className = "banner bad";
    b.append(`The last run failed ${ago(d.created_at)} in “${d.workflow || "?"}” at “${d.failed_node || "?"}”: ${d.error || ""} `);
    if (d.execution_url) b.append(el("a", { href: d.execution_url, target: "_blank", rel: "noopener", text: "Open in n8n" }));
    b.hidden = false;
  } else if (d && d.sources_failed && d.sources_failed.length) {
    b.textContent = `Sources that failed on the last run: ${d.sources_failed.join(", ")}`;
    b.hidden = false;
  }
}

// ------------------------------------------------------------------ inbox

async function loadInbox() {
  const f = state.filters;
  const qs = new URLSearchParams({ limit: "300" });
  if (f.q) qs.set("q", f.q);
  if (f.source) qs.set("source", f.source);
  if (f.archetype) qs.set("archetype", f.archetype);
  const data = await api(`/ui/api/inbox?${qs}`);
  state.jobs = data.jobs;
  state.selected.clear();
  state.focus = Math.min(state.focus, Math.max(0, state.jobs.length - 1));
  fillFacet($("source"), data.facets.sources, "All sources", f.source);
  fillFacet($("archetype"), data.facets.archetypes, "All profiles", f.archetype);
  state.matching = data.matching;
  state.inboxSize = data.inbox_size;
  render();
}

function renderCount() {
  const m = state.matching, n = state.inboxSize, shown = state.jobs.length;
  let t = m === n ? `${m} job${m === 1 ? "" : "s"}` : `${m} of ${n}`;
  if (m > shown) t += ` (showing ${shown})`;
  $("matching").textContent = t;
}

function fillFacet(select, rows, allLabel, current) {
  const keep = current;
  select.replaceChildren(el("option", { value: "", text: allLabel }));
  for (const r of rows) {
    if (!r.key) continue;
    select.append(el("option", { value: r.key, text: `${r.key} (${r.n})` }));
  }
  if (keep && !rows.some((r) => r.key === keep)) select.append(el("option", { value: keep, text: `${keep} (0)` }));
  select.value = keep;
}

function render() {
  $("loading").hidden = true;
  const list = $("list");
  list.replaceChildren(...state.jobs.map((j, i) => card(j, i)));
  $("empty").hidden = state.jobs.length > 0;
  renderCount();
  $("skip-shown").disabled = state.jobs.length === 0;
  $("skip-shown").textContent = state.jobs.length ? `Skip all shown (${state.jobs.length})` : "Skip all shown";
  updateSelection();
  markFocus(false);
}

function card(j, i) {
  const confident = j.archetype_confident;
  const meta = [j.company || "company unknown", j.location, j.source,
                j.posted_at ? `posted ${fmtDate(j.posted_at)}` : null,
                `found ${ago(j.first_seen)}`].filter(Boolean).join(" · ");
  const snippet = el("div", { class: "snippet", text: oneLine(j.snippet) });
  const more = j.desc_len > 300 ? el("button", { class: "linkbtn", type: "button", text: "More", onclick: () => toggleExpand(i) }) : null;
  const cb = el("input", { type: "checkbox", "aria-label": "Select", onchange: () => toggleSelect(i) });
  if (state.selected.has(j.id)) cb.checked = true;
  return el("li", { class: "card", "data-i": String(i), onclick: (e) => { if (!e.target.closest("button,a,input")) { state.focus = i; markFocus(false); } } },
    cb,
    el("div", { class: "score", title: "Relative to the whole corpus (0-100), not a match %" },
      String(j.relative ?? "–"), el("small", { text: "score" })),
    el("div", { class: "body" },
      el("div", { class: "title" }, el("a", { href: j.url || "#", target: "_blank", rel: "noopener", text: j.title })),
      el("div", { class: "meta" },
        el("span", { class: confident ? "chip" : "chip unsure", title: confident ? "Role profile" : "Two profiles nearly tied", text: j.archetype_label || "?" }),
        meta),
      snippet, more),
    el("div", { class: "actions" },
      el("button", { class: "btn pursue", type: "button", title: "Pursue (p)", text: "Pursue", onclick: () => decide([j.id], "pursue") }),
      el("button", { class: "btn", type: "button", title: "Skip (s)", text: "Skip", onclick: () => decide([j.id], "skip") })));
}

function cards() { return [...$("list").children]; }

function markFocus(scroll = true) {
  cards().forEach((c, i) => c.classList.toggle("focused", i === state.focus));
  const c = cards()[state.focus];
  if (c && scroll) c.scrollIntoView({ block: "nearest" });
}

function toggleSelect(i) {
  const j = state.jobs[i];
  if (!j) return;
  if (state.selected.has(j.id)) state.selected.delete(j.id); else state.selected.add(j.id);
  updateSelection();
}

function updateSelection() {
  cards().forEach((c, i) => {
    const on = state.selected.has(state.jobs[i]?.id);
    c.classList.toggle("selected", on);
    const cb = c.querySelector("input[type=checkbox]");
    if (cb) cb.checked = on;
  });
  const n = state.selected.size;
  $("skip-selected").disabled = n === 0;
  $("skip-selected").textContent = n ? `Skip selected (${n})` : "Skip selected";
}

async function toggleExpand(i) {
  const c = cards()[i], j = state.jobs[i];
  if (!c || !j) return;
  if (!c.classList.contains("expanded") && !j.full) {
    const d = await api(`/ui/api/jobs/${j.id}`);
    j.full = d.description || "";
  }
  const on = c.classList.toggle("expanded");
  c.querySelector(".snippet").textContent = on ? tidy(j.full) : oneLine(j.snippet);
  const more = c.querySelector(".linkbtn");
  if (more) more.textContent = on ? "Less" : "More";
}

// ------------------------------------------------------------------ decisions

async function decide(ids, verdict) {
  if (!ids.length) return;
  // Read labels now: the jobs leave state.jobs before the toast is shown.
  const names = new Map(state.jobs.filter((j) => ids.includes(j.id)).map((j) => [j.id, `${j.company || "?"} — ${j.title}`]));
  const label = (id) => names.get(id) || "";
  let res;
  try {
    res = await api("/ui/api/decisions", { job_ids: ids, verdict });
  } catch (e) {
    toast(`Could not save: ${e.message}`);
    return;
  }
  const done = new Set(res.decided.map((d) => d.job_id));
  // animate out, then drop from the list without a full reload (keeps focus position)
  cards().forEach((c, i) => { if (done.has(state.jobs[i]?.id)) c.classList.add("leaving"); });
  await new Promise((r) => setTimeout(r, 140));
  const before = state.focus;
  state.jobs = state.jobs.filter((j) => !done.has(j.id));
  state.matching -= done.size;
  state.inboxSize -= done.size;
  for (const id of done) state.selected.delete(id);
  state.focus = Math.min(before, Math.max(0, state.jobs.length - 1));
  render();
  markFocus();
  if (res.decided.length) {
    state.undo.push({ ids: res.decided.map((d) => d.decision_id), verdict });
    const what = verdict === "pursue" ? "Pursued" : "Skipped";
    toast(res.decided.length === 1 ? `${what}: ${label(res.decided[0].job_id) || ""}` : `${what} ${res.decided.length} jobs`, true);
  }
  if (res.not_in_inbox.length) toast(`${res.not_in_inbox.length} job(s) were no longer in the inbox`);
  loadSummary().catch(() => {});
}

async function undoLast() {
  const last = state.undo.pop();
  if (!last) { toast("Nothing to undo"); return; }
  try {
    const r = await api("/ui/api/decisions/undo", { decision_ids: last.ids });
    toast(r.refused.length ? `Restored ${r.restored.length}; ${r.refused.length} had already moved on` : `Restored ${r.restored.length} job(s) to the inbox`);
  } catch (e) {
    toast(`Undo failed: ${e.message}`);
    return;
  }
  await loadInbox();
  loadSummary().catch(() => {});
}

let toastTimer = null;
function toast(msg, undoable = false) {
  $("toast-msg").textContent = msg;
  $("toast-undo").hidden = !undoable;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, undoable ? 6000 : 3500);
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

// ------------------------------------------------------------------ wiring

function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

function wire() {
  $("q").addEventListener("input", debounce(() => { state.filters.q = $("q").value.trim(); state.focus = 0; loadInbox(); }, 250));
  $("source").addEventListener("change", () => { state.filters.source = $("source").value; state.focus = 0; loadInbox(); });
  $("archetype").addEventListener("change", () => { state.filters.archetype = $("archetype").value; state.focus = 0; loadInbox(); });
  $("skip-selected").addEventListener("click", async () => {
    const ids = [...state.selected];
    if (ids.length > 1 && !(await confirmDialog(`Skip ${ids.length} selected jobs? You can undo right after.`))) return;
    decide(ids, "skip");
  });
  $("skip-shown").addEventListener("click", async () => {
    const ids = state.jobs.map((j) => j.id);
    const scope = state.filters.q || state.filters.source || state.filters.archetype ? "matching your filters" : "in the inbox";
    if (!(await confirmDialog(`Skip all ${ids.length} jobs ${scope}? You can undo right after.`))) return;
    decide(ids, "skip");
  });
  $("toast-undo").addEventListener("click", undoLast);

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const typing = e.target.matches("input[type=search], input[type=text], select, textarea");
    if (typing) { if (e.key === "Escape") e.target.blur(); return; }
    if ($("confirm").open) return;
    const j = state.jobs[state.focus];
    switch (e.key) {
      case "j": case "ArrowDown": state.focus = Math.min(state.focus + 1, state.jobs.length - 1); markFocus(); break;
      case "k": case "ArrowUp": state.focus = Math.max(state.focus - 1, 0); markFocus(); break;
      case "p": if (j) decide([j.id], "pursue"); break;
      case "s": if (j) decide([j.id], "skip"); break;
      case "x": toggleSelect(state.focus); break;
      case "e": case "Enter": toggleExpand(state.focus); break;
      case "o": if (j && j.url) window.open(j.url, "_blank", "noopener"); break;
      case "u": undoLast(); break;
      case "/": $("q").focus(); break;
      default: return;
    }
    e.preventDefault();
  });
}

wire();
Promise.all([loadSummary(), loadInbox()]).catch((e) => {
  $("loading").textContent = `Could not reach the engine: ${e.message}. Is the stack running?`;
});
// Pick up a run that finished while the page was open.
setInterval(() => loadSummary().catch(() => {}), 60000);
