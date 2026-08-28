#!/usr/bin/env python3
"""Confirmation worksheet — the human gate, made practical.

    python confirm.py              # generate out/worksheet.md + confirm.txt
    python confirm.py --apply      # flip every ticked fact to status: confirmed
    python confirm.py --status     # what is confirmed, what is not
    python confirm.py --reset      # set everything back to draft

WORKFLOW
    1. python confirm.py
    2. Read out/worksheet.md. Open it in an editor, or print it.
    3. Tick facts in confirm.txt by changing "[ ]" to "[x]".
    4. python confirm.py --apply

Unticked facts are never touched, so you can do this in several sittings and nothing
gets silently promoted. Only draft -> confirmed happens here; going back needs --reset,
which is deliberately blunt.

WHAT YOU ARE ASSERTING when you tick a box:
    - this is true, and stated at the right scope
    - the verb matches what I actually did
    - I can defend it under follow-up questioning
    - the numbers are right

The third is the one people skip. A fact you cannot survive a follow-up on is worse than
no fact at all, because it turns a good interview into a bad one at the worst moment.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required:  pip install pyyaml")

import render as R

HERE = Path(__file__).parent
OUT = HERE / "out"
SHEET = OUT / "worksheet.md"
TICKS = HERE / "confirm.txt"

KIND_ORDER = {"project": 0, "role": 1, "education": 2, "credential": 3}
PASS_LABEL = {
    "project": ("Pass 1 — project facts",
                "I extracted these from your repos and copied the numbers verbatim. Your job "
                "is to check the numbers against the source and confirm the framing is how "
                "you would put it."),
    "role": ("Pass 2 — work history",
             "These came from your Lebenslauf and from the outcomes session. You lived them, "
             "so the question is only whether the scope and the verb are honest."),
    "education": ("Pass 3 — education",
                  "Mostly self-evidencing. Check dates and titles."),
    "credential": ("Pass 3 — education", ""),
}


def bullet(f, lang="en"):
    return R.clean(R.bullet_text(f, lang))


def flag_notes(f, entity):
    """Things worth a second look before ticking. Advisory, never blocking."""
    notes = []
    if entity.get("authorship") in ("team", "co-authored"):
        notes.append(f"team work ({entity['authorship']}) — the bullet must not claim sole credit")
    if f.get("scope") in ("operated", "contributed"):
        notes.append(f"scope is '{f['scope']}' — you operated it, you did not create it")
    if not f.get("outcome") and entity.get("kind") not in ("education", "credential"):
        notes.append("no outcome — the bullet stops at what you did")
    if f.get("evidence") == "interview-defensible":
        notes.append("no written evidence — this rests entirely on your recall")
    nums = re.findall(r"\d[\d,.]*", bullet(f))
    if nums:
        notes.append("contains numbers: " + ", ".join(sorted(set(nums))))
    return notes


def build(bank):
    groups: dict[str, list] = {}
    for f in bank["facts"]:
        e = bank["entities_by_id"].get(f.get("entity"), {})
        groups.setdefault(e.get("kind", "role"), []).append((f, e))
    for k in groups:
        groups[k].sort(key=lambda fe: (
            R.date_key(fe[1].get("end")), -(fe[0].get("strength") or 0)), reverse=True)
    return dict(sorted(groups.items(), key=lambda kv: KIND_ORDER.get(kv[0], 9)))


def write_worksheet(bank, groups):
    total = len(bank["facts"])
    done = sum(1 for f in bank["facts"] if f.get("status") == "confirmed")
    L = [
        "# Fact bank — confirmation worksheet",
        "",
        f"**{done} of {total} confirmed.**  Tick facts in `confirm.txt`, then run "
        "`python confirm.py --apply`.",
        "",
        "Ticking a box asserts four things: it is true and at the right scope, the verb "
        "matches what you did, you can defend it under follow-up, and the numbers are right.",
        "",
        "Nothing renders to a CV until a fact is confirmed. That is the point — this gate "
        "is the reason the rest of the pipeline can be trusted.",
        "",
        "---",
    ]
    for kind, items in groups.items():
        label, blurb = PASS_LABEL.get(kind, (kind.title(), ""))
        L += ["", f"## {label}", ""]
        if blurb:
            L += [blurb, ""]
        last_entity = None
        for f, e in items:
            if e.get("id") != last_entity:
                dates = R.fmt_range(e.get("start"), e.get("end"), "en")
                L += ["", f"### {e.get('name')} — {e.get('org','')}  ",
                      f"*{dates}*" + (f" · authorship: {e.get('authorship')}" if e.get('authorship') != 'sole' else ""),
                      ""]
                last_entity = e.get("id")
            mark = "x" if f.get("status") == "confirmed" else " "
            L += [f"- [{mark}] **`{f['id']}`**  · strength {f.get('strength')}"
                  f" · {', '.join(f.get('archetypes') or []) or 'no archetype'}"]
            L += ["", f"  > {bullet(f)}", ""]
            if f.get("claim_de") or f.get("claim_short_de"):
                L += [f"  > *DE:* {bullet(f, 'de')}", ""]
            L += [f"  - evidence: `{f.get('evidence')}`"]
            for m in f.get("metrics") or []:
                ctx = f" — {m['context']}" if m.get("context") else ""
                L += [f"  - metric: `{m['name']}` = **{m['value']}**{ctx}"]
            for n in flag_notes(f, e):
                L += [f"  - check: {n}"]
            for rel in f.get("related") or []:
                L += [f"  - related: `{rel}` — prepare these together"]
            if f.get("interview_hook"):
                L += ["", f"  **Interview:** {R.clean(f['interview_hook'])}"]
            L += [""]
    SHEET.parent.mkdir(exist_ok=True)
    SHEET.write_text("\n".join(L), encoding="utf-8")


def write_ticks(bank, groups):
    if TICKS.exists():
        existing = {m.group(2): m.group(1).lower() == "x" for m in
                    re.finditer(r"^\[( |x|X)\]\s+(\S+)", TICKS.read_text(encoding="utf-8"), re.M)}
    else:
        existing = {}
    L = ["# Tick a box to confirm that fact, then run: python confirm.py --apply",
         "# Unticked lines are never touched. Read out/worksheet.md alongside this.", ""]
    for kind, items in groups.items():
        L += [f"# ---- {PASS_LABEL.get(kind, (kind, ''))[0]} ----"]
        for f, e in items:
            ticked = f.get("status") == "confirmed" or existing.get(f["id"], False)
            L += [f"[{'x' if ticked else ' '}] {f['id']:<42} # {bullet(f)[:70]}"]
        L += [""]
    TICKS.write_text("\n".join(L), encoding="utf-8")


def apply_ticks() -> int:
    if not TICKS.exists():
        sys.exit("confirm.txt not found — run `python confirm.py` first.")
    ticked = {m.group(1) for m in re.finditer(
        r"^\[[xX]\]\s+(\S+)", TICKS.read_text(encoding="utf-8"), re.M)}
    path = HERE / "facts.yaml"
    s = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    chunks = s.split("\n  - id: ")
    out, changed = [chunks[0]], []
    for ch in chunks[1:]:
        fid = ch.split("\n", 1)[0].strip()
        if fid in ticked and re.search(r"^    status: draft$", ch, re.M):
            ch = re.sub(r"^    status: draft$", "    status: confirmed", ch, count=1, flags=re.M)
            changed.append(fid)
        out.append(ch)
    path.write_text("\n  - id: ".join(out), encoding="utf-8")
    if changed:
        print(f"confirmed {len(changed)} fact(s):")
        for c in changed:
            print(f"  + {c}")
    else:
        print("nothing to confirm — no newly ticked facts found.")
    print("\nNow run:  python validate.py  &&  python render.py ds")
    return 0


def reset() -> int:
    path = HERE / "facts.yaml"
    s = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    s, n = re.subn(r"^    status: confirmed$", "    status: draft", s, flags=re.M)
    path.write_text(s, encoding="utf-8")
    print(f"reset {n} fact(s) to draft")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    if args.apply:
        return apply_ticks()
    if args.reset:
        return reset()

    bank = R.load_bank()
    groups = build(bank)

    if args.status:
        done = [f for f in bank["facts"] if f.get("status") == "confirmed"]
        todo = [f for f in bank["facts"] if f.get("status") != "confirmed"]
        print(f"\nconfirmed: {len(done)}   draft: {len(todo)}\n")
        for f in todo:
            print(f"  [ ] {f['id']:<42} strength {f.get('strength')}")
        return 0

    write_worksheet(bank, groups)
    write_ticks(bank, groups)
    done = sum(1 for f in bank["facts"] if f.get("status") == "confirmed")
    print(f"\n{len(bank['facts'])} facts, {done} already confirmed.")
    print(f"  worksheet : {SHEET}")
    print(f"  checklist : {TICKS}")
    print("\nRead the worksheet, tick boxes in confirm.txt, then: python confirm.py --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
