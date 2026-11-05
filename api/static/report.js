// Job engine: the report (Stage 6). Single-series charts: one validated hue (--viz), values
// always printed beside each bar (that text doubles as the table view), native tooltips on hover.
// Geometry is set through the CSSOM (el.style.*), which the page's CSP allows; no style attributes.
"use strict";

const $ = (id) => document.getElementById(id);
const pct = (x) => `${Math.round(x * 100)}%`;

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) if (c) n.append(c);
  return n;
}

function countBar(label, n, max, valueText, tip) {
  const bar = el("div", { class: "bar hit", title: tip || `${label}: ${n}`, role: "img", "aria-label": tip || `${label}: ${n}` });
  const fill = el("div", { class: "fill" });
  fill.style.width = `${max ? (100 * n) / max : 0}%`;
  bar.append(fill);
  return el("div", { class: "brow" }, el("span", { class: "lab", text: label }), bar, el("span", { class: "val", text: valueText ?? String(n) }));
}

// A proportion is drawn as its 95% interval (soft band) with the point estimate on top.
function intervalBar(label, w, showPoint = true) {
  const tip = w.n ? `${label}: ${w.k}/${w.n}, ${pct(w.p)} (95% interval ${pct(w.lo)}–${pct(w.hi)})` : `${label}: no data`;
  const bar = el("div", { class: "bar hit", title: tip, role: "img", "aria-label": tip });
  if (w.n) {
    const r = el("div", { class: "range" });
    r.style.left = `${100 * w.lo}%`; r.style.width = `${Math.max(0.5, 100 * (w.hi - w.lo))}%`;
    bar.append(r);
    if (showPoint) { const p = el("div", { class: "point" }); p.style.left = `${100 * w.p}%`; bar.append(p); }
  }
  const val = !w.n ? "—" : showPoint ? `${w.k}/${w.n} · ${pct(w.p)} [${pct(w.lo)}–${pct(w.hi)}]` : `${w.k}/${w.n} · [${pct(w.lo)}–${pct(w.hi)}]`;
  return el("div", { class: "brow" }, el("span", { class: "lab", text: label }), bar, el("span", { class: "val", text: val }));
}

function tiles(w) {
  const items = [["discovered", w.discovered], ["decided", w.decided], ["pursued", w.pursued],
                 ["approved", w.approved], ["sent", w.sent], ["replies", w.replies]];
  $("week").replaceChildren(...items.map(([l, v]) => el("div", { class: "tile" }, el("div", { class: "v", text: String(v ?? 0) }), el("div", { class: "l", text: l }))));
}

function rates(d) {
  const p = $("rates");
  p.replaceChildren();
  const o = d.outcomes;
  p.append(el("div", { class: "note", text:
    `${d.resolved} resolved (${o.reply + o.positive} replied, ${o.no_reply} no reply) · ${o.censored} still inside the ${d.rules.window_days}-day window, not counted · ${o.withdrawn} withdrawn, left out` }));
  if (!d.rates_reported) {
    p.append(el("div", { class: "hero" }, el("b", { text: "Not reported as a rate yet. " }),
      `${d.needed_for_rates} more resolved application${d.needed_for_rates === 1 ? "" : "s"} needed (${d.rules.min_n} in total). A number now would look like a finding and be an anecdote.`));
    if (d.resolved) {
      p.append(el("div", { class: "note", text: "For scale, this is how wide the 95% interval is at today's n. It spans most of the range, which is the point:" }));
      p.append(intervalBar("any reply", d.any_reply, false));
      p.append(intervalBar("interview or offer", d.interview, false));
    }
  } else {
    p.append(intervalBar("any reply", d.any_reply));
    p.append(intervalBar("interview or offer", d.interview));
  }
  if (d.time_to_reply) {
    const t = d.time_to_reply;
    p.append(el("div", { class: "note", text: `Time to first reply: median ${t.median} days, range ${t.min}–${t.max}, n=${t.n}.` }));
  }
}

function funnel(d) {
  const max = Math.max(...d.funnel.map((s) => s.n), 1);
  const rows = d.funnel.map((s, i) => {
    const prev = i ? d.funnel[i - 1].n : null;
    // Only print "% of previous" when the stages nest; V1 imports can break nesting.
    const of = prev && s.n <= prev ? ` · ${pct(s.n / prev)} of previous` : "";
    return countBar(s.stage, s.n, max, `${s.n}${of}`);
  });
  $("funnel").replaceChildren(...rows);
}

function breakdowns(d) {
  if (!d.by) { $("sec-by").hidden = true; return; }
  const names = { source: "by source", archetype: "by role profile", cv_variant: "by CV variant", score_bucket: "by score at decision" };
  const out = [];
  for (const [k, b] of Object.entries(d.by)) {
    out.push(el("div", { class: "subhead", text: names[k] || k }));
    for (const r of b.rows) out.push(intervalBar(r.group, r.any_reply));
    if (b.verdict) out.push(el("div", { class: "verdict", text: b.verdict }));
  }
  $("by").replaceChildren(...out);
  $("sec-by").hidden = false;
}

function skills(d) {
  const s = d.missing_skills;
  if (!s.top.length) { $("skills").replaceChildren(el("div", { class: "note", text: "Nothing missing so far." })); return; }
  const max = s.top[0].jobs;
  $("skills").replaceChildren(
    el("div", { class: "note", text: `Counted across the latest CV of ${s.jobs_with_cv} jobs you pursued. A skill high on this list is the market's curriculum: either write the fact that evidences it, or learn it.` }),
    ...s.top.map((t) => countBar(t.skill, t.jobs, max, `${t.jobs} job${t.jobs === 1 ? "" : "s"}`, `${t.skill}: asked for by ${t.jobs} pursued job(s), evidenced by no fact`)));
}

function gate1(d) {
  $("gate1").replaceChildren(
    el("div", { class: "note", text: "Every Pursue/Skip is a label. These are the shares you pursued, with intervals. Use them to tune each role profile's match text, not to judge yourself." }),
    ...d.gate1.map((g) => intervalBar(g.archetype, g.pursue)));
}

async function load() {
  const r = await fetch("/ui/api/report");
  if (!r.ok) throw new Error(String(r.status));
  const d = await r.json();
  $("summary").textContent = `as of ${d.as_of}`;
  tiles(d.week); rates(d); funnel(d); breakdowns(d); skills(d); gate1(d);
  $("warn").replaceChildren(...d.warnings.map((w) => el("div", { class: "note warn", text: w })));
  $("sec-warn").hidden = !d.warnings.length;
  $("rules").textContent = `Rules: no rate below ${d.rules.min_n} resolved applications; no reply within ${d.rules.window_days} days is "not yet observed", not a rejection; every proportion carries a Wilson 95% interval. "Any reply" includes rejections; "interview or offer" does not.`;
  $("loading").hidden = true;
}

load().catch((e) => { $("loading").textContent = `Could not load the report: ${e.message}`; });
