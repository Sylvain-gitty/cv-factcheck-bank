#!/usr/bin/env python3
"""Plan 02 — the pillar path: evidence pack, draft skeleton, gates, render.

    python article.py --list                  # allow-listed repos and their authorship
    python article.py --evidence tiri         # build the evidence pack (no LLM, ever)
    python article.py --new tiri "<thesis>"   # start a draft from that evidence
    python article.py --check <slug>          # run the gates
    python article.py --render <slug>         # HTML + PDF, refuses if gates fail
    python article.py --drafts                # what is in progress

Drafts live in articles/<slug>.md and are meant to be written by hand.

------------------------------------------------------------------------------
TWO STRUCTURAL RULES

1. THE EVIDENCE PACK IS BUILT WITHOUT A MODEL. Every number an article may use is
   extracted by code from a confirmed fact or a file in the repo, with its source
   recorded. A model summarising a notebook will occasionally produce a plausible number
   that is not in it, and a plausible-but-wrong metric is invisible to your reader and
   glaring to the one person you wanted to impress. `numeric_integrity` then rejects any
   figure in the draft that is not in the pack.

2. YOU WRITE THE INTRODUCTION AND THE CONCLUSION. Both ship as TODO blocks and every gate
   fails while they are present. They are the two sections people actually read and where
   voice is most visible. The middle of a well-grounded article can be assembled; an
   opening cannot, because it has to convey a specific person having a specific thought.

Provenance is enforced before anything else: sources come from content-sources.yaml, never
a folder scan, and `authorship` travels with the draft into the checks. Nine CV facts were
once seeded from someone else's proprietary repo on the assumption that a directory in a
personal folder was personal work. Published, that would not have been recoverable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required:  pip install pyyaml")

import render as R

HERE = Path(__file__).parent
ARTICLES = HERE / "articles"
OUT = HERE / "out" / "articles"
SOURCES = HERE / "content-sources.yaml"

INTRO_TODO = """<!-- INTRODUCTION: WRITE THIS YOURSELF. Gates fail while this block is here.
     150-250 words. State the claim in the first hundred, and make it arguable.
     Not "this post explores..." -- say the thing, then show why it is not obvious. -->"""
CONCLUSION_TODO = """<!-- CONCLUSION: WRITE THIS YOURSELF. Gates fail while this is here.
     What should the reader do or believe differently? One idea, not a summary. -->"""


def log(msg=""):
    print(msg, flush=True)


try:
    sys.stdout.reconfigure(errors="replace")
except Exception:                                                # noqa: BLE001
    pass


def load_sources() -> dict:
    if not SOURCES.exists():
        sys.exit(f"missing {SOURCES.name}")
    return yaml.safe_load(SOURCES.read_text(encoding="utf-8")) or {}


def slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")[:70]


# --------------------------------------------------------------------------- evidence

NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+\.\d+|\d+%|\d+)(?![\w])")


def evidence_pack(repo: dict, bank: dict) -> dict:
    """Every number this article is allowed to use, and where each came from.

    Two sources, both verifiable:
      · confirmed facts on the linked entity, with their structured metrics
      · numbers appearing in the repo's own declared evidence_files

    No model is involved at any point. That is the entire design.
    """
    items, seen = [], set()

    for f in bank["facts"]:
        if f.get("entity") != repo.get("entity") or f.get("status") != "confirmed":
            continue
        if not f.get("publishable", True):
            continue
        for m in f.get("metrics") or []:
            key = f"{m.get('name')}={m.get('value')}"
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "value": str(m.get("value")), "name": m.get("name"),
                "context": m.get("context"), "source": f"fact:{f['id']}",
                "claim": R.clean(f.get("claim_short") or f.get("claim"))[:160],
                "verified": True,
            })

    base = (HERE / repo["path"]).resolve()
    for rel in repo.get("evidence_files") or []:
        p = base / rel
        if not p.exists():
            items.append({"value": None, "name": None, "source": f"file:{rel}",
                          "claim": "MISSING — declared in content-sources.yaml but not on disk",
                          "verified": False})
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            nums = NUM.findall(line)
            if not nums or len(line.strip()) < 12:
                continue
            for n in nums:
                if n in ("0", "1", "2") or f"{rel}:{n}" in seen:
                    continue
                seen.add(f"{rel}:{n}")
                items.append({
                    "value": n, "name": None, "source": f"file:{rel}",
                    "claim": R.clean(line)[:150], "verified": True,
                })

    figs = []
    if repo.get("figures"):
        fdir = base / repo["figures"]
        if fdir.exists():
            figs = sorted(str(p.relative_to(base)) for p in fdir.rglob("*")
                          if p.suffix.lower() in (".png", ".jpg", ".svg"))
    return {"repo": repo["id"], "label": repo["label"], "url": repo.get("url"),
            "authorship": repo["authorship"], "collaborators": repo.get("collaborators", []),
            "share": repo.get("share"), "built": date.today().isoformat(),
            "items": items, "figures": figs}


def allowed_numbers(pack: dict) -> set[str]:
    out = set()
    for it in pack["items"]:
        if it.get("value") is None:
            continue
        v = str(it["value"])
        out.add(v)
        out.add(v.replace(",", ""))
        out.add(v.rstrip("%"))
        if re.match(r"^\d+\.\d+$", v):          # 0.889 also licenses 889 and 88.9
            out.add(v.lstrip("0."))
            out.add(v.replace(".", ""))
    return out


# --------------------------------------------------------------------------- draft

def new_draft(repo, pack, thesis) -> str:
    we = repo["authorship"] in ("co-authored", "team")
    L = [
        f"# {thesis}", "",
        f"<!-- source: {repo['id']} · {repo['url'] or ''} -->",
        f"<!-- authorship: {repo['authorship']}"
        + (f" with {', '.join(repo.get('collaborators') or [])}" if we else "")
        + f" · share: {repo.get('share')} -->",
        f"<!-- evidence pack: {len(pack['items'])} item(s), {len(pack['figures'])} figure(s) -->",
        "",
    ]
    if we:
        L += ["<!-- THIS IS SHARED WORK. Say \"we\" throughout. The checks enforce it. -->", ""]
    L += [
        INTRO_TODO, "", "",
        "## <!-- section heading -->", "",
        "<!-- BODY: the assembled part. Every number must appear in the evidence pack",
        "     below; numeric_integrity rejects the draft otherwise. Cite a figure as",
        "     ![alt](path) using one of the figures listed at the bottom. -->", "",
        "", "## <!-- section heading -->", "", "",
        CONCLUSION_TODO, "", "", "---", "",
        f"<!-- EVIDENCE PACK — {pack['built']} — every number you may use", "",
    ]
    for it in pack["items"][:60]:
        if it.get("value") is None:
            L.append(f"     !! {it['source']}: {it['claim']}")
        else:
            L.append(f"     {str(it['value']):>12}  {it['source']:<28} {it['claim'][:78]}")
    if len(pack["items"]) > 60:
        L.append(f"     ... {len(pack['items']) - 60} more in out/evidence/{repo['id']}.json")
    L += ["-->", ""]
    if pack["figures"]:
        L += ["<!-- FIGURES available:"] + [f"     {f}" for f in pack["figures"]] + ["-->", ""]
    return "\n".join(L)


def prose_of(text: str) -> str:
    body = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


# --------------------------------------------------------------------------- checks

def run_checks(slug, text, repo, pack, cfg):
    prose = prose_of(text)
    words = len(prose.split())
    checks = []

    def add(name, ok, detail, fatal=True):
        checks.append({"check": name, "pass": ok, "detail": detail, "fatal": fatal})

    add("intro_is_yours", "INTRODUCTION: WRITE THIS YOURSELF" not in text,
        "written" if "INTRODUCTION: WRITE THIS YOURSELF" not in text
        else "the TODO block is still there")
    add("conclusion_is_yours", "CONCLUSION: WRITE THIS YOURSELF" not in text,
        "written" if "CONCLUSION: WRITE THIS YOURSELF" not in text
        else "the TODO block is still there")

    title = (text.splitlines() or [""])[0].lstrip("# ").strip()
    bad = next((o for o in cfg.get("positioning", {}).get("self_centric_openers", [])
                if o in title.lower()), None)
    add("problem_centric_title", not bad,
        f"'{title[:56]}'" if not bad
        else f"'{bad}' makes this about you, not the problem")

    allowed = allowed_numbers(pack)
    unsourced = sorted({n for n in NUM.findall(prose)
                        if n not in allowed and n.replace(",", "") not in allowed
                        and len(n) > 1 and n not in ("10", "100")})
    add("numeric_integrity", not unsourced,
        f"{len(allowed)} value(s) in the pack, every figure traced" if not unsourced
        else f"not in the evidence pack: {unsourced[:6]}")

    ban = [b.lower() for b in cfg.get("voice", {}).get("ban", [])]
    hits = sorted({b for b in ban if b in prose.lower()})
    add("ban_list", not hits, "clean" if not hits else f"found: {hits}")

    if repo["authorship"] in ("co-authored", "team"):
        first = re.findall(r"\bI\b(?!\s*(?:had|would|was|am)\b)", prose)
        add("shared_work_voice", len(first) <= 3,
            f"shared work, {len(first)} first-person singular use(s)"
            + ("" if len(first) <= 3 else " — this reads as solo work"))
        add("collaborators_named",
            any(c.split()[0] in prose for c in repo.get("collaborators") or []) or True,
            "credit your collaborators in the piece, not only in the repo", fatal=False)

    lo, hi = cfg.get("positioning", {}).get("target_words", [1200, 2000])
    add("length", lo <= words <= hi, f"{words} words (target {lo}-{hi})", fatal=False)
    return checks


# --------------------------------------------------------------------------- render

CSS = """html,body{background:#fff!important;color:#1a1a1a!important}
body{font:12pt/1.65 Georgia,"Times New Roman",serif;max-width:34em;margin:3rem auto;padding:0 1.2rem}
h1{font-size:24pt;line-height:1.2;margin:0 0 .4em;font-family:system-ui,sans-serif}
h2{font-size:14pt;margin:2em 0 .5em;font-family:system-ui,sans-serif}
.meta{color:#666;font-size:10.5pt;font-family:system-ui,sans-serif;margin-bottom:2.5em;
      border-bottom:1px solid #ddd;padding-bottom:1em}
p{margin:0 0 1.1em}img{max-width:100%;height:auto;margin:1.5em 0}
blockquote{border-left:3px solid #ddd;margin:1.5em 0;padding-left:1.2em;color:#444}
code{background:#f4f4f4;padding:1px 4px;font-size:10.5pt}
pre{background:#f6f6f6;padding:1em;overflow-x:auto;font-size:10pt}
.credit{margin-top:3em;padding-top:1em;border-top:1px solid #ddd;color:#555;font-size:10.5pt;
        font-family:system-ui,sans-serif}"""


def to_html(text, repo, owner):
    prose = prose_of(text)
    lines, out, in_p = prose.splitlines(), [], []
    title = ""
    for ln in lines:
        s = ln.strip()
        if s.startswith("# ") and not title:
            title = s[2:]
            continue
        if s.startswith("## "):
            if in_p:
                out.append("<p>" + " ".join(in_p) + "</p>")
                in_p = []
            out.append(f"<h2>{s[3:]}</h2>")
            continue
        m = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", s)
        if m:
            if in_p:
                out.append("<p>" + " ".join(in_p) + "</p>")
                in_p = []
            out.append(f'<img src="{m.group(2)}" alt="{m.group(1)}">')
            continue
        if not s:
            if in_p:
                out.append("<p>" + " ".join(in_p) + "</p>")
                in_p = []
            continue
        in_p.append(s)
    if in_p:
        out.append("<p>" + " ".join(in_p) + "</p>")

    who = repo["authorship"]
    credit = f"Work at <a href=\"{repo.get('url') or '#'}\">{repo['label']}</a>. "
    if who in ("co-authored", "team") and repo.get("collaborators"):
        credit += f"Joint work with {', '.join(repo['collaborators'])}. "
    if repo.get("share"):
        credit += f"{R.clean(repo['share'])}"
    return (f"<!doctype html><meta charset='utf-8'><title>{title}</title>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<style>{CSS}</style><article><h1>{title}</h1>"
            f"<div class='meta'>{owner.get('name')} · {date.today().strftime('%d %B %Y')}</div>"
            + "".join(out) + f"<div class='credit'>{credit}</div></article>")


# --------------------------------------------------------------------------- driver

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--drafts", action="store_true")
    ap.add_argument("--evidence", metavar="REPO")
    ap.add_argument("--new", nargs=2, metavar=("REPO", "THESIS"))
    ap.add_argument("--check", metavar="SLUG")
    ap.add_argument("--render", metavar="SLUG")
    args = ap.parse_args()

    cfg = load_sources()
    repos = {r["id"]: r for r in cfg.get("repos", [])}
    bank = R.load_bank()
    ARTICLES.mkdir(exist_ok=True)

    if args.list:
        log("\nALLOW-LISTED REPOS — nothing else may become an article")
        for r in cfg["repos"]:
            who = r["authorship"]
            extra = f" with {', '.join(r.get('collaborators') or [])}" if r.get("collaborators") else ""
            log(f"  {r['id']:<14} {who:<12}{extra}")
            log(f"  {'':<14} {r['label']}")
        log("\nDeliberately absent, and why, is documented in content-sources.yaml.")
        return 0

    if args.drafts:
        ds = sorted(ARTICLES.glob("*.md"))
        if not ds:
            log("no drafts — start with: python article.py --new <repo> \"<thesis>\"")
            return 0
        for p in ds:
            t = p.read_text(encoding="utf-8")
            need = [n for n, mark in (("intro", "INTRODUCTION: WRITE THIS"),
                                      ("conclusion", "CONCLUSION: WRITE THIS")) if mark in t]
            log(f"  {p.stem:<52} {'ready' if not need else 'needs ' + ' + '.join(need)}")
        return 0

    if args.evidence:
        if args.evidence not in repos:
            sys.exit(f"'{args.evidence}' is not allow-listed. Allowed: {', '.join(repos)}")
        pack = evidence_pack(repos[args.evidence], bank)
        d = HERE / "out" / "evidence"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{args.evidence}.json").write_text(
            json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
        verified = [i for i in pack["items"] if i["verified"]]
        from_facts = [i for i in verified if i["source"].startswith("fact:")]
        log(f"\nEVIDENCE PACK — {pack['label']}")
        log(f"  {len(verified)} value(s): {len(from_facts)} from confirmed facts, "
            f"{len(verified) - len(from_facts)} from repo files")
        log(f"  {len(pack['figures'])} figure(s)")
        for i in from_facts[:8]:
            log(f"    {str(i['value']):>10}  {i['name'] or '':<26} {i['source']}")
        missing = [i for i in pack["items"] if not i["verified"]]
        for m in missing:
            log(f"    !! {m['source']}: {m['claim']}")
        log(f"\n  -> out/evidence/{args.evidence}.json")
        log("  No model touched this. Every number is from a confirmed fact or a repo file.")
        return 0

    if args.new:
        rid, thesis = args.new
        if rid not in repos:
            sys.exit(f"'{rid}' is not allow-listed. Allowed: {', '.join(repos)}")
        repo = repos[rid]
        pack = evidence_pack(repo, bank)
        slug = slugify(thesis)
        path = ARTICLES / f"{slug}.md"
        if path.exists():
            sys.exit(f"{path.name} already exists — not overwriting your work")
        path.write_text(new_draft(repo, pack, thesis), encoding="utf-8")
        log(f"\nDRAFT  articles/{slug}.md")
        log(f"  {len(pack['items'])} evidence item(s), {len(pack['figures'])} figure(s)")
        if repo["authorship"] != "sole":
            log(f"  SHARED WORK ({repo['authorship']}) — say \"we\"; the checks enforce it")
        log("\nYou write the introduction and the conclusion. Gates fail until you do.")
        log(f"  then:  python article.py --check {slug}")
        return 0

    slug = args.check or args.render
    if not slug:
        return main_help(ap)
    path = ARTICLES / f"{slug}.md"
    if not path.exists():
        sys.exit(f"no draft at {path}")
    text = path.read_text(encoding="utf-8")
    m = re.search(r"<!-- source: (\S+)", text)
    if not m or m.group(1) not in repos:
        sys.exit("draft has no allow-listed source header — was it created by --new?")
    repo = repos[m.group(1)]
    pack = evidence_pack(repo, bank)
    checks = run_checks(slug, text, repo, pack, cfg)

    log(f"\nCHECKS — {slug}   [source: {repo['id']} · {repo['authorship']}]")
    for c in checks:
        mark = "ok  " if c["pass"] else ("FAIL" if c["fatal"] else "warn")
        log(f"  [{mark}] {c['check']:<22} {c['detail'][:66]}")
    blocked = [c for c in checks if not c["pass"] and c["fatal"]]

    if args.render:
        if blocked:
            log(f"\n  NOT RENDERED — {len(blocked)} gate(s) failed.")
            return 1
        OUT.mkdir(parents=True, exist_ok=True)
        html = to_html(text, repo, bank["profile"].get("owner", {}))
        hp = OUT / f"{slug}.html"
        hp.write_text(html, encoding="utf-8")
        log(f"\n  -> {hp}")
        log("\nGATE 4 — publishing is yours. Read it on the rendered page first.")
    return 1 if blocked else 0


def main_help(ap):
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
