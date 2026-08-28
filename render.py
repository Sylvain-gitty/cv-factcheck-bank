#!/usr/bin/env python3
"""Render CVs from the fact bank.

    python render.py                      # every variant in render_config.yaml
    python render.py ds pm                # named variants only
    python render.py ds --include-drafts  # while the bank is still unconfirmed
    python render.py --list               # show variants

Output lands in out/:
    <variant>.html         open in a browser, Ctrl+P, "Save as PDF"
    <variant>.md           readable/diffable plain text
    <variant>.trace.json   every rendered bullet -> the fact id it came from

WHAT THIS DOES NOT DO
It does not write. It selects, orders, caps and formats. Every word of every bullet comes
verbatim from facts.yaml. That is the point: a renderer that cannot phrase cannot
hallucinate, and the traceability file proves it line by line.

Later, Plan 01 Stage 3 hands the selection decisions to an LLM per job -- but the LLM
returns fact IDs, and this same renderer produces the document. Content decisions and
document production stay separate.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required:  pip install pyyaml")

HERE = Path(__file__).parent
OUT = HERE / "out"

MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "de": ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"],
}
PRESENT = {"en": "present", "de": "heute"}
DRAFT_BANNER = {
    "en": "DRAFT — contains unconfirmed facts. Do not send.",
    "de": "ENTWURF — enthält unbestätigte Angaben. Nicht versenden.",
}


# --------------------------------------------------------------------------- loading

def load(name: str):
    path = HERE / name
    if not path.exists():
        sys.exit(f"missing file: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_bank() -> dict:
    """The whole bank, loaded once. Shared by render.py and tailor.py."""
    bank = {
        "profile": load("profile.yaml"),
        "vocab": load("vocab.yaml"),
        "entities": load("entities.yaml").get("entities") or [],
        "facts": load("facts.yaml").get("facts") or [],
    }
    bank["entities_by_id"] = {e["id"]: e for e in bank["entities"]}
    bank["facts_by_id"] = {f["id"]: f for f in bank["facts"]}
    return bank


def resolve_variant(variant: dict, defaults: dict) -> dict:
    cfg = dict(defaults)
    cfg.update({k: v for k, v in variant.items() if v is not None or k == "archetype"})
    cfg.setdefault("archetype", None)
    return cfg


def selection_from_ids(fact_ids, bank) -> "Selection":
    """Build a Selection from an explicit, ordered list of fact ids.

    This is the seam Stage 3 plugs into: the selector (BM25, or an LLM) decides WHICH
    facts, and hands over ids. The renderer is unchanged and still cannot phrase anything.
    """
    sel = Selection()
    for fid in fact_ids:
        f = bank["facts_by_id"].get(fid)
        if f is None:
            sel.dropped.append(f"{fid}: no such fact in the bank")
            continue
        if f.get("entity") not in bank["entities_by_id"]:
            sel.dropped.append(f"{fid}: unknown entity {f.get('entity')}")
            continue
        if f.get("contribution") == "supported":
            sel.dropped.append(f"{fid}: contribution is 'supported' -- not rendered")
            continue
        sel.by_entity[f["entity"]].append(f)
    return sel


# --------------------------------------------------------------------------- dates

def date_key(value) -> tuple[int, int]:
    """Sort key. None (ongoing) sorts last -- i.e. most recent."""
    if value in (None, ""):
        return (9999, 99)
    s = str(value)
    year = int(s[:4])
    month = int(s[5:7]) if len(s) >= 7 and s[5:7].isdigit() else 0
    return (year, month)


def fmt_date(value, lang: str) -> str:
    if value in (None, ""):
        return PRESENT[lang]
    s = str(value)
    if len(s) >= 7 and s[5:7].isdigit():
        return f"{MONTHS[lang][int(s[5:7]) - 1]} {s[:4]}"
    return s[:4]


def fmt_range(start, end, lang: str) -> str:
    if start in (None, "") and end in (None, ""):
        return ""
    if start in (None, ""):
        return fmt_date(end, lang)
    return f"{fmt_date(start, lang)} – {fmt_date(end, lang)}"


# --------------------------------------------------------------------------- selection

class Selection:
    """The result of applying one variant's policy to the bank."""

    def __init__(self):
        self.by_entity: dict[str, list[dict]] = defaultdict(list)
        self.dropped: list[str] = []
        self.notes: list[str] = []
        self.trace: list[dict] = []

    @property
    def total(self) -> int:
        return sum(len(v) for v in self.by_entity.values())


def clean(text) -> str:
    """YAML block scalars arrive with newlines; CVs want one line."""
    if not text:
        return ""
    return " ".join(str(text).split())


def select(facts, entities_by_id, cfg, deny_terms) -> Selection:
    sel = Selection()
    arch = cfg["archetype"]
    lang = cfg["language"]

    pool = []
    for f in facts:
        fid = f["id"]
        if f.get("status") != "confirmed" and not cfg["include_drafts"]:
            sel.dropped.append(f"{fid}: status is '{f.get('status')}', not confirmed")
            continue
        if arch and arch not in (f.get("archetypes") or []):
            continue
        if (f.get("strength") or 0) < cfg["min_strength"]:
            sel.dropped.append(f"{fid}: strength {f.get('strength')} below minimum")
            continue
        if f.get("entity") not in entities_by_id:
            sel.dropped.append(f"{fid}: unknown entity")
            continue
        if f.get("contribution") == "supported":
            sel.dropped.append(f"{fid}: contribution is 'supported' -- teammate's work, "
                               f"kept in the bank but never rendered to a CV")
            continue

        # Belt and braces: the validator checks this too, but a deny-list term must never
        # reach a document, and this is the last gate before it becomes a PDF.
        body = f"{clean(f.get('claim'))} {clean(f.get('outcome'))}".lower()
        hit = next((t for t in deny_terms if t in body), None)
        if hit:
            sel.dropped.append(f"{fid}: BLOCKED, contains deny-list term '{hit}'")
            continue

        e = entities_by_id[f["entity"]]
        if e.get("start") in (None, "") or e.get("end") in (None, ""):
            miss = f"{e['id']}: missing start/end date -- sorted as ongoing, which may be wrong"
            if miss not in sel.notes:
                sel.notes.append(miss)
        if lang == "de" and not f.get("claim_de"):
            sel.notes.append(f"{fid}: no claim_de -- falling back to English")
        pool.append(f)

    # Strongest first, then by id so the output is stable across runs.
    pool.sort(key=lambda f: (-(f.get("strength") or 0), f["id"]))

    used = 0
    for f in pool:
        eid = f["entity"]
        if len(sel.by_entity.get(eid, [])) >= cfg["max_facts_per_entity"]:
            sel.dropped.append(f"{f['id']}: entity cap reached for {eid}")
            continue
        if used >= cfg["max_total_facts"]:
            sel.dropped.append(f"{f['id']}: total cap reached")
            continue
        sel.by_entity[eid].append(f)
        used += 1

    return sel


BULLET_CHARS = 190          # above this, a bullet starts costing you a line on the page


def bullet_text(fact, lang: str) -> str:
    """The rendered line. Verbatim from the bank -- never rephrased here.

    Prefers `claim_short` when present. The full `claim` is written for retrieval and for
    precision: unambiguous, self-contained, ~300 characters. A CV bullet wants ~140. Those
    are genuinely different jobs for the same underlying truth.

    Resolving that by letting the renderer compress would put a generator back in the
    document path and reopen the hallucination surface this design closed. So compression
    is a stored, reviewable act instead: you (or Stage 3, with your approval) write
    `claim_short` once, into the bank, where the validator can see it.
    """
    if lang == "de":
        text = clean(fact.get("claim_short_de") or fact.get("claim_de") or fact.get("claim"))
        outcome = clean(fact.get("outcome_short_de") or fact.get("outcome_de")
                        or fact.get("outcome_short") or fact.get("outcome"))
    else:
        text = clean(fact.get("claim_short") or fact.get("claim"))
        outcome = clean(fact.get("outcome_short") or fact.get("outcome"))
    if outcome and outcome.lower() not in ("none", "null"):
        text = f"{text} {outcome}"
    return text


# --------------------------------------------------------------------------- structure

def ordered_entities(sel, entities_by_id, kinds, all_entities=False):
    """Entities to render for one section, most recent first.

    `all_entities` exists for education. A degree is self-evidencing -- the entity line
    (name, institution, dates) IS the claim -- so it must appear whether or not any of its
    facts were selected. Without this, cutting a weak education fact silently deletes the
    degree from the CV, which is a spectacular way to lose an interview.
    """
    if all_entities:
        ents = [e for e in entities_by_id.values() if e.get("kind") in kinds]
    else:
        # Belt and braces: never draw a heading with nothing beneath it. Education is the
        # only section where a bare entity line is meaningful, and it goes through the
        # all_entities branch above.
        ents = [entities_by_id[eid] for eid, fs in sel.by_entity.items()
                if fs and entities_by_id[eid].get("kind") in kinds]
    # Most recent first: by end date, then start date.
    ents.sort(key=lambda e: (date_key(e.get("end")), date_key(e.get("start"))), reverse=True)
    return ents


def entity_title(e, lang: str) -> tuple[str, str, str]:
    """Name, org, dates -- with the team context folded into org for shared work.

    A two-person project rendered as bare bullets reads as solo work. Naming the role
    once in the header ("Data Scientist, 1 of 2") frames every bullet beneath it honestly,
    which is far better than bending each sentence into the passive to avoid overclaiming.
    One honest line beats ten hedged ones.
    """
    name = e.get("name_de") if lang == "de" and e.get("name_de") else e.get("name")
    org = clean(e.get("org") or "")
    role = clean(e.get("role") or "")
    # Show the role whenever it says something the name does not: "1 of 2" on shared work,
    # "Design and direction" where the implementation was not all yours. Skip it when the
    # entity name already IS the job title, which is the case for most employment rows.
    if role and role.lower() not in clean(name).lower() and role.lower() != "sole author":
        org = f"{org} · {role}" if org else role
    return clean(name), org, fmt_range(e.get("start"), e.get("end"), lang)


def collect_skills(sel, vocab, cfg):
    """Skills are DERIVED from the facts that were actually rendered.

    This is the design's quiet win. A hand-maintained skills list drifts away from the
    evidence -- which is exactly how six unbacked claims ended up on the current CV. Here
    the section cannot contain a skill no rendered bullet supports, because it is computed
    from them.
    """
    by_id = {s["id"]: s for s in vocab.get("skills", [])}
    seen = []
    for facts in sel.by_entity.values():
        for f in facts:
            for sid in f.get("skills") or []:
                if sid not in seen:
                    seen.append(sid)
    grouped = defaultdict(list)
    for sid in seen:
        v = by_id.get(sid)
        if v:
            grouped[v.get("group", "working")].append(v.get("label", sid))
    return grouped


# --------------------------------------------------------------------------- HTML

CSS = """
/* A CV is a print document. It is always light, whatever theme the viewer's browser is in
   -- without an explicit background the page inherits a dark one and the dark text becomes
   unreadable on screen and unpredictable in print. */
html, body { background: #ffffff !important; color: #1a1a1a !important; }
@page { size: A4; margin: 13mm 14mm; }
* { box-sizing: border-box; }
body {
  font-family: "Source Sans Pro", "Segoe UI", Calibri, system-ui, sans-serif;
  font-size: 10.2pt; line-height: 1.38;
  max-width: 190mm; margin: 0 auto; padding: 8mm 6mm;
}
.draft {
  background: #b00020; color: #fff; padding: 5px 10px; border-radius: 3px;
  font-weight: 700; letter-spacing: .04em; font-size: 9pt; margin-bottom: 12px;
}
header { border-bottom: 2px solid #1a1a1a; padding-bottom: 7px; margin-bottom: 12px; }
h1 { font-size: 19pt; margin: 0 0 2px; letter-spacing: -.01em; color: #000; }
.headline { font-size: 9.6pt; color: #444; margin-bottom: 4px; }
.contact { font-size: 8.9pt; color: #333; }
.contact span:not(:last-child)::after { content: " | "; color: #aaa; }
h2 {
  font-size: 9.2pt; text-transform: uppercase; letter-spacing: .09em;
  border-bottom: 1px solid #cfcfcf; padding-bottom: 2px;
  margin: 13px 0 7px; color: #000;
}
.entity { margin-bottom: 9px; page-break-inside: avoid; }
/* Title and dates on one line; org and role on a quieter second line. Long project names
   and a role suffix on the same run wrapped badly and shoved the dates out of alignment. */
.entity-head { display: flex; justify-content: space-between; gap: 14px; align-items: baseline; }
.entity-name { font-weight: 700; color: #000; }
.entity-dates { color: #555; font-size: 8.9pt; white-space: nowrap; flex: none; }
.entity-sub { color: #555; font-size: 9.2pt; margin-top: 1px; }
ul { margin: 3px 0 0; padding-left: 15px; }
li { margin-bottom: 2px; }
.profile { text-align: justify; margin: 0; }
.skills dl { margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: 2px 14px; }
.skills dt { font-weight: 600; color: #000; }
.skills dd { margin: 0; }
.langs { margin: 0; }
@media print {
  .draft { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { padding: 0; }
}
"""


def esc(s) -> str:
    return html.escape(str(s or ""))


def render_html(bank, sel, cfg, labels, skill_labels) -> str:
    lang = cfg["language"]
    owner = bank["profile"].get("owner", {})
    ents = bank["entities_by_id"]
    p: list[str] = []

    p.append(f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">')
    p.append(f"<title>{esc(owner.get('name'))} — {esc(cfg['label'])}</title>")
    p.append(f"<style>{CSS}</style></head><body>")

    if cfg["include_drafts"]:
        p.append(f'<div class="draft">{esc(DRAFT_BANNER[lang])}</div>')

    headline = owner.get("headline_de") if lang == "de" else owner.get("headline_en")
    p.append("<header>")
    p.append(f"<h1>{esc(owner.get('name'))}</h1>")
    if headline:
        p.append(f'<div class="headline">{esc(headline)}</div>')
    bits = [owner.get("phone"), owner.get("email"), owner.get("location"),
            owner.get("linkedin"), owner.get("github")]
    p.append('<div class="contact">' + "".join(
        f"<span>{esc(b)}</span>" for b in bits if b) + "</div>")
    p.append("</header>")

    for section in cfg["sections"]:
        title = labels[lang].get(section, section)

        if section == "profile":
            arch = next((a for a in bank["profile"].get("archetypes", [])
                         if a["id"] == cfg["archetype"]), None)
            key = "profile_de" if lang == "de" else "profile"
            text = clean(arch.get(key) or arch.get("profile")) if arch else ""
            if not text or text.startswith("TODO"):
                text = ""
            if text:
                p.append(f"<h2>{esc(title)}</h2><p class='profile'>{esc(text)}</p>")
            continue

        if section == "skills":
            grouped = collect_skills(sel, bank["vocab"], cfg)
            if not grouped:
                continue
            p.append(f"<h2>{esc(title)}</h2><div class='skills'><dl>")
            for g in ["core", "data", "modelling", "evaluation", "ai", "engineering", "working"]:
                if grouped.get(g):
                    p.append(f"<dt>{esc(skill_labels[lang].get(g, g))}</dt>"
                             f"<dd>{esc(', '.join(grouped[g]))}</dd>")
            p.append("</dl></div>")
            continue

        if section == "languages":
            langs = bank["profile"].get("owner", {}).get("languages") or []
            if not langs:
                continue
            key = "level_de" if lang == "de" else "level"
            parts = [f"{esc(l['lang'].capitalize())} — {esc(l.get(key, l.get('level')))}"
                     for l in langs]
            p.append(f"<h2>{esc(title)}</h2><p class='langs'>{' | '.join(parts)}</p>")
            continue

        kinds = {"projects": ["project"], "experience": ["role"],
                 "education": ["education", "credential"]}[section]
        rows = ordered_entities(sel, ents, kinds, all_entities=(section == "education"))
        if not rows:
            continue
        p.append(f"<h2>{esc(title)}</h2>")
        for e in rows:
            name, org, dates = entity_title(e, lang)
            bullets = sel.by_entity.get(e["id"], [])
            p.append('<div class="entity"><div class="entity-head">')
            if bullets or not org:
                p.append(f'<span class="entity-name">{esc(name)}</span>')
                p.append(f'<span class="entity-dates">{esc(dates)}</span></div>')
                if org:
                    p.append(f'<div class="entity-sub">{esc(org)}</div>')
            else:
                # No bullets: fold the org onto the title line rather than spending two.
                p.append(f'<span class="entity-name">{esc(name)}</span>'
                         f'<span class="entity-dates">{esc(dates)}</span></div>')
                p.append(f'<div class="entity-sub">{esc(org)}</div>')
            if sel.by_entity.get(e["id"]):
                p.append("<ul>")
            for f in sel.by_entity.get(e["id"], []):
                line = bullet_text(f, lang)
                p.append(f"<li>{esc(line)}</li>")
                sel.trace.append({"section": section, "entity": e["id"],
                                  "fact_id": f["id"], "text": line})
            if sel.by_entity.get(e["id"]):
                p.append("</ul>")
            p.append("</div>")

    p.append("</body></html>")
    return "\n".join(p)


# Measured against a real browser render at A4 proportions. Every constant below is a
# fraction of one usable A4 page (297mm less 26mm of margins). The previous version
# counted bullet characters only and reported 1.1 pages where the truth was 1.76 -- the
# profile paragraph, the skills grid and the always-rendered education block are together
# worth more than half a page and it ignored all of them.
PAGE = dict(
    base=0.156,          # header block + body padding
    profile_per_char=0.000326,
    skill_row=0.033,
    section_heading=0.0243,
    entity=0.080,        # title + org line + margin + list padding
    bullet_line=0.0233,
    chars_per_line=64,
    languages=0.023,
)


def page_estimate(bank, sel, cfg) -> float:
    """Estimated A4 pages. Calibrated, not guessed -- see PAGE above."""
    import math
    lang = cfg["language"]
    total = PAGE["base"]

    if "profile" in cfg["sections"]:
        arch = next((a for a in bank["profile"].get("archetypes", [])
                     if a["id"] == cfg["archetype"]), None)
        if arch:
            key = "profile_de" if lang == "de" else "profile"
            text = clean(arch.get(key) or arch.get("profile") or "")
            if text and not text.startswith("TODO"):
                total += PAGE["section_heading"] + len(text) * PAGE["profile_per_char"]

    if "skills" in cfg["sections"]:
        groups = collect_skills(sel, bank["vocab"], cfg)
        if groups:
            total += PAGE["section_heading"] + len(groups) * PAGE["skill_row"]

    if "languages" in cfg["sections"] and (bank["profile"].get("owner", {}).get("languages")):
        total += PAGE["section_heading"] + PAGE["languages"]

    ents = bank["entities_by_id"]
    for section in ("projects", "experience", "education"):
        if section not in cfg["sections"]:
            continue
        kinds = {"projects": ["project"], "experience": ["role"],
                 "education": ["education", "credential"]}[section]
        rows = ordered_entities(sel, ents, kinds, all_entities=(section == "education"))
        if not rows:
            continue
        total += PAGE["section_heading"] + len(rows) * PAGE["entity"]

    for b in sel.trace:
        lines = max(1, math.ceil(len(b["text"]) / PAGE["chars_per_line"]))
        total += lines * PAGE["bullet_line"]
    return total


def render_markdown(bank, sel, cfg, labels) -> str:
    lang = cfg["language"]
    owner = bank["profile"].get("owner", {})
    ents = bank["entities_by_id"]
    out = []
    if cfg["include_drafts"]:
        out.append(f"> **{DRAFT_BANNER[lang]}**\n")
    out.append(f"# {owner.get('name')}\n")
    bits = [owner.get("phone"), owner.get("email"), owner.get("location"),
            owner.get("linkedin"), owner.get("github")]
    out.append(" | ".join(str(b) for b in bits if b) + "\n")

    for section in cfg["sections"]:
        if section in ("profile", "skills", "languages"):
            continue
        kinds = {"projects": ["project"], "experience": ["role"],
                 "education": ["education", "credential"]}[section]
        rows = ordered_entities(sel, ents, kinds, all_entities=(section == "education"))
        if not rows:
            continue
        out.append(f"\n## {labels[lang].get(section, section)}\n")
        for e in rows:
            name, org, dates = entity_title(e, lang)
            head = f"**{name}**" + (f" — {org}" if org else "")
            out.append(f"\n{head}  \n*{dates}*\n")
            for f in sel.by_entity.get(e["id"], []):
                out.append(f"- {bullet_text(f, lang)}  <!-- {f['id']} -->")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- driver

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("variants", nargs="*", help="variant ids (default: all)")
    ap.add_argument("--include-drafts", action="store_true",
                    help="render unconfirmed facts, watermarked DRAFT")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    bank = load_bank()
    rc = load("render_config.yaml")
    labels, skill_labels = rc["section_labels"], rc["skill_group_labels"]
    deny = [t.lower() for t in bank["profile"].get("deny_list", {}).get("terms", [])]

    if args.list:
        for v in rc["variants"]:
            print(f"  {v['id']:<10} {v['label']}")
        return 0

    wanted = args.variants or [v["id"] for v in rc["variants"]]
    OUT.mkdir(exist_ok=True)
    any_output = False

    for v in rc["variants"]:
        if v["id"] not in wanted:
            continue
        cfg = resolve_variant(v, rc["defaults"])
        if args.include_drafts:
            cfg["include_drafts"] = True

        sel = select(bank["facts"], bank["entities_by_id"], cfg, deny)

        print(f"\n{'=' * 66}\n{cfg['label']}  [{v['id']}]  lang={cfg['language']}\n{'=' * 66}")
        if sel.total == 0:
            print("  nothing to render.")
            if not cfg["include_drafts"]:
                print("  Every fact is still status: draft. Either confirm some facts, or")
                print("  run with --include-drafts to preview (output is watermarked).")
            continue

        html_doc = render_html(bank, sel, cfg, labels, skill_labels)
        (OUT / f"{v['id']}.html").write_text(html_doc, encoding="utf-8")
        (OUT / f"{v['id']}.md").write_text(
            render_markdown(bank, sel, cfg, labels), encoding="utf-8")
        (OUT / f"{v['id']}.trace.json").write_text(
            json.dumps({"variant": v["id"], "language": cfg["language"],
                        "draft": cfg["include_drafts"], "bullets": sel.trace},
                       indent=2, ensure_ascii=False), encoding="utf-8")
        any_output = True

        blocked = [d for d in sel.dropped if "BLOCKED" in d]
        print(f"  {sel.total} bullets across {len(sel.by_entity)} entities "
              f"-> out/{v['id']}.html")
        est = page_estimate(bank, sel, cfg)
        flag = "  <-- over budget" if est > cfg["page_target"] + 0.25 else ""
        print(f"  estimated length ~{est:.1f} page(s), target {cfg['page_target']}{flag}")
        if blocked:
            print(f"  !! {len(blocked)} fact(s) BLOCKED by the deny-list:")
            for b in blocked:
                print(f"       {b}")
        for n in sel.notes[:6]:
            print(f"  ! {n}")
        if len(sel.notes) > 6:
            print(f"  ! ... and {len(sel.notes) - 6} more")

    if any_output:
        print(f"\n{'=' * 66}")
        print("Open the .html in a browser, then Ctrl+P -> 'Save as PDF'.")
        print("Set margins to Default and enable background graphics for the draft banner.")
        print("Check the .trace.json before sending: every bullet, and the fact behind it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
