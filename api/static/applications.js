// Job engine: Applications (Stage 5, Gate 4, follow-ups, outcomes).
// There is no submit here. "I sent it" records something you did on the employer's site.
"use strict";

const $ = (id) => document.getElementById(id);
let DATA = null;

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Job-Engine": "1" },
    body: JSON.stringify(body),
  };
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.detail || `${r.status}`); e.status = r.status; throw e; }
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

let toastTimer = null, undoFn = null;
function toast(msg, undo = null, ms = 5000) {
  $("toast-msg").textContent = msg;
  undoFn = undo;
  $("toast-undo").hidden = !undo;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; undoFn = null; }, undo ? 8000 : ms);
}

const today = () => new Date().toISOString().slice(0, 10);
const fmt = (d) => d ? new Date(d).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";

async function act(path, body, msg, undo) {
  try { await api(path, body); toast(msg, undo); }
  catch (e) { toast(e.message, null, 8000); }
  await load();
}

// ------------------------------------------------------------------ render

function head(a) {
  return el("div", { class: "arow" },
    el("div", { class: "grow" },
      el("div", { class: "title" }, el("a", { href: a.url || "#", target: "_blank", rel: "noopener", text: a.title })),
      el("div", { class: "meta", text: [a.company, a.source, a.cv_variant ? `CV ${a.cv_variant}` : null].filter(Boolean).join(" · ") })));
}

function fileLinks(a) {
  const order = (n) => (n.endsWith(".pdf") ? 0 : n.endsWith(".html") ? 1 : 2);
  const fs = [...a.files].sort((x, y) => order(x.name) - order(y.name) || x.name.localeCompare(y.name));
  return el("div", { class: "files" },
    ...fs.filter((f) => f.name !== "CHECKLIST.md").map((f) =>
      el("a", { href: `/ui/files/package/${a.id}/${encodeURIComponent(f.name)}`, target: "_blank", rel: "noopener", text: f.name })));
}

function checklistToggle(a) {
  const box = el("pre", { class: "checklist", hidden: true });
  const btn = el("button", { class: "linkbtn", type: "button", text: "Show checklist + screening answers", onclick: async () => {
    if (box.hidden && !box.textContent) {
      const d = await api(`/ui/api/applications/${a.id}/checklist`);
      box.textContent = d.text || "No CHECKLIST.md in this package.";
    }
    box.hidden = !box.hidden;
    btn.textContent = box.hidden ? "Show checklist + screening answers" : "Hide checklist";
  } });
  return [btn, box];
}

function readyCard(a) {
  const dateIn = el("input", { type: "date", value: today(), max: today(), "aria-label": "Date you sent it" });
  const pdfNote = a.pdf_pending ? el("div", { class: "note warn", text: `PDFs are being printed by the desktop helper (${a.pdf_pending} left). Refresh in a minute.` })
                : a.pdf_error ? el("div", { class: "note bad", text: `PDF printing failed: ${a.pdf_error}. Open the HTML and print it with Ctrl+P instead.` })
                : !a.files.some((f) => f.name.endsWith(".pdf")) ? el("div", { class: "note warn", text: "No PDFs in this package. Open the HTML files and print them with Ctrl+P." }) : null;
  return el("li", { class: "acard" }, head(a), fileLinks(a), pdfNote, ...checklistToggle(a),
    el("div", { class: "arow" },
      el("span", { class: "note grow", text: "Submit it yourself on the employer's site (link above). Then:" }),
      dateIn,
      el("button", { class: "btn pursue", type: "button", text: "I sent it", onclick: () =>
        act(`/ui/api/applications/${a.id}/sent`, { sent_date: dateIn.value || null },
            `Marked sent. Follow-ups scheduled for day 7 and 14.`, () => act(`/ui/api/applications/${a.id}/unsend`, {}, "Back to ready to send")) })));
}

function approvedCard(a) {
  return el("li", { class: "acard" }, head(a),
    el("div", { class: "note bad", text: a.package_error ? `Packaging failed: ${a.package_error}` : "Approved; the package has not been built yet." }),
    el("div", { class: "arow" }, el("button", { class: "btn", type: "button", text: "Build package", onclick: () =>
      act(`/ui/api/applications/${a.id}/package`, {}, "Packaged") })));
}

const OUTCOME_BTNS = [["replied", "Replied"], ["interview", "Interview"], ["offer", "Offer"], ["rejected", "Rejected"],
                      ["closed", "No reply, close it"], ["withdrawn", "I withdrew"]];

function outcomeRow(a) {
  const notes = el("input", { type: "text", placeholder: "Note (optional): who, what was said", "aria-label": "Note", class: "note-input" });
  const dateIn = el("input", { type: "date", value: today(), max: today(), "aria-label": "Outcome date" });
  return el("div", { class: "arow" }, notes, dateIn,
    el("div", { class: "outcomes" }, ...OUTCOME_BTNS.map(([k, label]) =>
      el("button", { class: k === "interview" || k === "offer" ? "btn pursue" : "btn", type: "button", text: label, onclick: () =>
        act(`/ui/api/applications/${a.id}/outcome`, { outcome: k, outcome_date: dateIn.value || null, notes: notes.value.trim() || null }, `Recorded: ${label.toLowerCase()}`) }))));
}

function sentCard(a) {
  const nf = a.next_follow_up;
  const since = a.days_since_sent != null ? `sent ${fmt(a.sent_date)} · ${a.days_since_sent} day${a.days_since_sent === 1 ? "" : "s"} ago` : "sent";
  return el("li", { class: "acard" }, head(a),
    el("div", { class: "note", text: [since, nf ? `next follow-up ${fmt(nf.due_date)} (${nf.kind})` : null,
                                      a.days_since_sent >= 21 ? "no reply after 21 days counts as no reply in the report" : null].filter(Boolean).join(" · ") }),
    fileLinks(a), outcomeRow(a),
    el("div", { class: "arow" }, el("span", { class: "grow" }),
      el("button", { class: "linkbtn", type: "button", text: "Not sent yet (undo)", onclick: () =>
        act(`/ui/api/applications/${a.id}/unsend`, {}, "Back to ready to send") })));
}

function doneCard(a) {
  return el("li", { class: "acard" }, head(a),
    el("div", { class: "note", text: [`${a.status}`, a.sent_date ? `sent ${fmt(a.sent_date)}` : null,
                                      a.first_reply_date ? `first reply ${fmt(a.first_reply_date)}` : null].filter(Boolean).join(" · ") }),
    a.notes ? el("div", { class: "note", text: a.notes }) : null, outcomeRow(a));
}

function dueCard(f) {
  return el("li", { class: "acard" },
    el("div", { class: "arow" },
      el("div", { class: "grow" },
        el("div", { class: "title", text: `Follow up: ${f.company || "?"} — ${f.title}` }),
        el("div", { class: "meta", text: `${f.kind} reminder, due ${fmt(f.due_date)}. No reply yet? A short, polite nudge.` })),
      el("button", { class: "btn", type: "button", text: "Snooze 3 days", onclick: () => act(`/ui/api/follow-ups/${f.id}`, { action: "snooze" }, "Snoozed 3 days") }),
      el("button", { class: "btn pursue", type: "button", text: "Done", onclick: () => act(`/ui/api/follow-ups/${f.id}`, { action: "done" }, "Follow-up done") })));
}

function fill(sectionId, listId, items, make) {
  $(listId).replaceChildren(...items.map(make));
  $(sectionId).hidden = items.length === 0;
}

async function load() {
  DATA = await api("/ui/api/applications");
  const A = DATA.applications;
  const by = (states) => A.filter((a) => states.includes(a.state));
  const ready = by(["packaged"]), sent = by(["sent"]), done = by(["replied", "interview", "offer", "rejected", "closed"]);
  fill("sec-due", "due", DATA.due, dueCard);
  fill("sec-approved", "approved", by(["approved"]), approvedCard);
  fill("sec-ready", "ready", ready, readyCard);
  fill("sec-sent", "sent", sent, sentCard);
  fill("sec-done", "done", done, doneCard);
  $("done-n").textContent = done.length ? `(${done.length})` : "";
  $("loading").hidden = true;
  $("empty").hidden = A.length > 0;
  $("tab-apps-n").textContent = ready.length ? String(ready.length) : "";
  $("summary").textContent = `${ready.length} ready to send · ${sent.length} waiting · ${DATA.due.length} follow-up${DATA.due.length === 1 ? "" : "s"} due`;
}

$("toast-undo").addEventListener("click", () => { const f = undoFn; undoFn = null; $("toast").hidden = true; if (f) f(); });
load().catch((e) => { $("loading").textContent = `Could not reach the engine: ${e.message}`; });
setInterval(() => { if (document.visibilityState === "visible") load().catch(() => {}); }, 30000);
