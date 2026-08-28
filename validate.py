#!/usr/bin/env python3
"""Validate the fact bank.

Run before any CV render, article draft, or n8n job that reads this directory:

    python validate.py            # validate + coverage report
    python validate.py --quiet    # errors only, for CI / n8n

Exit codes:  0 = clean (warnings allowed)   1 = errors found   2 = could not load

Why a validator at all: this bank is hand-edited over months, and its failure mode is not
a crash. It is a typo'd skill tag that silently narrows retrieval, or a fact confirmed
without evidence that ends up in a CV. Both are invisible without a check like this.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required:  pip install pyyaml")

HERE = Path(__file__).parent

FACT_REQUIRED = ["id", "entity", "type", "claim", "skills", "archetypes", "strength", "status"]
ENTITY_REQUIRED = ["id", "kind", "name", "authorship"]

FACT_TYPES = {"achievement", "insight", "artifact", "responsibility", "metric"}
ENTITY_KINDS = {"project", "role", "education", "credential"}
STATUSES = {"draft", "confirmed"}
AUTHORSHIPS = {"sole", "co-authored", "team"}
SCOPES = {"created", "operated", "contributed"}
CONTRIBUTIONS = {"led", "joint", "supported"}

# Verbs that claim you brought something into existence. The authorship check guards
# team-vs-sole credit; this one guards creator-vs-operator, which is a different and more
# common inflation -- "I worked inside a good system" quietly becoming "I built it".
# Only checked on facts that declare `scope`. "established" was deliberately REMOVED from
# this list: it is far more often an adjective ("an established system") than a claim, and
# a check that cries wolf gets switched off. Third time this precision tradeoff has come up.
CREATOR_VERBS = ["redesigned", "rebuilt", "introduced", "overhauled",
                 "transformed", "founded", "launched", "architected", "pioneered",
                 "created", "designed", "built"]

# Past-tense verbs that typically open a claim. Used only by the "two claims in one"
# heuristic below -- deliberately narrow, to keep that check's false-positive rate low.
CLAIM_VERBS = "|".join([
    "built", "designed", "shipped", "wrote", "led", "owned", "decided", "developed",
    "implemented", "analysed", "analyzed", "investigated", "measured", "showed",
    "demonstrated", "established", "diagnosed", "validated", "benchmarked", "compared",
    "reduced", "improved", "delivered", "deployed", "automated", "set", "created",
    "contributed", "supported", "documented", "presented", "trained", "tuned",
])

def clean_text(x) -> str:
    return " ".join(str(x or "").split())


errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def load(name: str) -> dict:
    path = HERE / name
    if not path.exists():
        sys.exit(f"missing file: {path}")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        sys.exit(f"{name} is not valid YAML:\n{e}")


def build_skill_index(vocab: dict) -> tuple[set[str], dict[str, str]]:
    """Return (canonical ids, alias -> canonical id)."""
    canonical, alias_map = set(), {}
    for s in vocab.get("skills", []):
        sid = s["id"]
        canonical.add(sid)
        for a in s.get("aliases", []) or []:
            if a in alias_map and alias_map[a] != sid:
                err(f"vocab: alias '{a}' maps to both '{alias_map[a]}' and '{sid}'")
            alias_map[a] = sid
    return canonical, alias_map


def check_entities(entities: list[dict]) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for e in entities:
        eid = e.get("id", "<no id>")
        for f in ENTITY_REQUIRED:
            if e.get(f) in (None, ""):
                err(f"entity {eid}: missing required field '{f}'")
        if eid in by_id:
            err(f"entity {eid}: duplicate id")
        by_id[eid] = e

        if e.get("kind") not in ENTITY_KINDS:
            err(f"entity {eid}: kind '{e.get('kind')}' not in {sorted(ENTITY_KINDS)}")
        if e.get("authorship") not in AUTHORSHIPS:
            err(f"entity {eid}: authorship '{e.get('authorship')}' not in {sorted(AUTHORSHIPS)}")

        # Team work with nobody named is the setup for accidental over-claiming.
        if e.get("authorship") in {"team", "co-authored"} and not (e.get("collaborators") or []):
            warn(f"entity {eid}: authorship is '{e['authorship']}' but collaborators is empty "
                 f"-- name them, so 'we' is not a vague gesture")

        start, end = e.get("start"), e.get("end")
        if start and end and str(end) < str(start):
            err(f"entity {eid}: end ({end}) precedes start ({start})")
    return by_id


def check_facts(facts, entities_by_id, canonical, alias_map, profile):
    archetype_ids = {a["id"] for a in profile.get("archetypes", [])}
    territory_ids = {t["id"] for t in profile.get("territories", [])}
    deny_terms = [t.lower() for t in profile.get("deny_list", {}).get("terms", [])]
    forbidden = profile.get("forbidden_verbs", {}) or {}

    seen: set[str] = set()
    for f in facts:
        fid = f.get("id", "<no id>")
        for field in FACT_REQUIRED:
            if field not in f or f.get(field) in (None, ""):
                err(f"fact {fid}: missing required field '{field}'")
        # An empty list is present-but-empty: not a schema error, but a fact tagged with
        # no skills and no archetype can never be retrieved by Stage 3. It is dead weight.
        if not (f.get("skills") or []) and not (f.get("archetypes") or []):
            warn(f"fact {fid}: no skills and no archetypes -- unreachable by retrieval. "
                 f"Tag it, or delete it and buy the space back.")
        if fid in seen:
            err(f"fact {fid}: duplicate id")
        seen.add(fid)

        if f.get("type") not in FACT_TYPES:
            err(f"fact {fid}: type '{f.get('type')}' not in {sorted(FACT_TYPES)}")
        if f.get("status") not in STATUSES:
            err(f"fact {fid}: status '{f.get('status')}' not in {sorted(STATUSES)}")
        if f.get("strength") not in (1, 2, 3):
            err(f"fact {fid}: strength must be 1, 2 or 3 (got {f.get('strength')!r})")

        # --- referential integrity ---
        entity = entities_by_id.get(f.get("entity"))
        if entity is None:
            err(f"fact {fid}: entity '{f.get('entity')}' does not exist in entities.yaml")

        for s in f.get("skills") or []:
            if s in alias_map:
                err(f"fact {fid}: skill '{s}' is an alias — use canonical id '{alias_map[s]}'")
            elif s not in canonical:
                err(f"fact {fid}: skill '{s}' is not in vocab.yaml "
                    f"(add it deliberately, or fix the tag)")

        for a in f.get("archetypes") or []:
            if a not in archetype_ids:
                err(f"fact {fid}: archetype '{a}' not defined in profile.yaml")

        terr = f.get("territory")
        if terr and terr not in territory_ids:
            err(f"fact {fid}: territory '{terr}' not defined in profile.yaml")

        text = f"{f.get('claim', '')} {f.get('outcome', '')}"
        low = text.lower()

        # --- the guardrails that matter ---
        for term in deny_terms:
            if term in low:
                level = err if f.get("status") == "confirmed" else warn
                level(f"fact {fid}: contains deny-list term '{term}'")

        if entity is not None:
            for verb in forbidden.get(entity.get("authorship"), []) or []:
                if re.search(rf"\b{re.escape(verb.lower())}\b", low):
                    err(f"fact {fid}: uses '{verb}' but entity {entity['id']} is "
                        f"'{entity['authorship']}' -- that claims credit you did not solely earn")

        # --- quality nudges ---
        contribution = f.get("contribution")
        if contribution and contribution not in CONTRIBUTIONS:
            err(f"fact {fid}: contribution '{contribution}' not in {sorted(CONTRIBUTIONS)}")
        if contribution and (entity or {}).get("authorship") == "sole":
            warn(f"fact {fid}: contribution is set but entity {entity['id']} is sole-authored "
                 f"-- the field only means something on shared work")
        if (entity or {}).get("authorship") in ("co-authored", "team") and not contribution:
            warn(f"fact {fid}: on {entity['authorship']} work with no contribution set "
                 f"-- say whether you led it, shared it, or supported it")

        scope = f.get("scope")
        if scope and scope not in SCOPES:
            err(f"fact {fid}: scope '{scope}' not in {sorted(SCOPES)}")
        if scope in ("operated", "contributed"):
            claim_text = f"{clean_text(f.get('claim'))} {clean_text(f.get('claim_short'))}".lower()
            for verb in CREATOR_VERBS:
                if re.search(r"\b" + verb + r"\b", claim_text):
                    warn(f"fact {fid}: scope is '{scope}' but the claim says '{verb}' "
                         f"-- that reads as having created it. Use an operator verb.")
                    break

        if f.get("status") == "confirmed" and not f.get("evidence"):
            err(f"fact {fid}: confirmed facts must carry evidence")
        # Coursework and credentials do not have outcomes in the way work does -- a module
        # you took did not change anything. Exempting them keeps the warning meaningful
        # everywhere it still fires.
        if not f.get("outcome") and (entity or {}).get("kind") not in ("education", "credential"):
            warn(f"fact {fid}: no outcome -- 'what changed' is the half that makes a bullet land")
        if f.get("type") == "metric" and not (f.get("metrics") or []):
            warn(f"fact {fid}: type is 'metric' but no structured metrics recorded")
        # "One claim per fact" check. The naive version -- warn on any " and " -- fired on
        # 75% of facts, because "X and Y" as a noun list is fine. A check that cries wolf
        # gets switched off, so this one only fires when " and " is followed by a second
        # claim VERB, which is the case that actually means two facts in one.
        if re.search(rf"\band\s+({CLAIM_VERBS})\b", f.get("claim", ""), re.IGNORECASE):
            warn(f"fact {fid}: claim looks like two claims joined by 'and' -- consider splitting")

        for m in f.get("metrics") or []:
            if not isinstance(m, dict) or "name" not in m or "value" not in m:
                err(f"fact {fid}: each metric needs at least 'name' and 'value' (got {m!r})")


def report(facts, entities, canonical, cv_claimed):
    print("\n" + "=" * 68)
    print("COVERAGE")
    print("=" * 68)

    status = Counter(f.get("status") for f in facts)
    print(f"\n  facts: {len(facts)} total  "
          f"({status.get('confirmed', 0)} confirmed, {status.get('draft', 0)} draft)")
    print(f"  entities: {len(entities)}")

    print("\n  by archetype (confirmed / total):")
    for arch in sorted({a for f in facts for a in (f.get("archetypes") or [])}):
        tot = [f for f in facts if arch in (f.get("archetypes") or [])]
        con = [f for f in tot if f.get("status") == "confirmed"]
        lead = [f for f in tot if f.get("strength") == 3]
        print(f"    {arch:<16} {len(con):>3} / {len(tot):<3}   ({len(lead)} lead-with-this)")

    by_kind = defaultdict(list)
    for e in entities:
        by_kind[e.get("kind")].append(e)
    counts = Counter(f.get("entity") for f in facts)
    print("\n  facts per entity:")
    for kind in sorted(by_kind):
        for e in by_kind[kind]:
            n = counts.get(e["id"], 0)
            flag = "   <-- no facts yet" if n == 0 else ""
            print(f"    [{kind:<9}] {e['id']:<22} {n:>3}{flag}")

    used = {s for f in facts for s in (f.get("skills") or [])}
    unevidenced = sorted(cv_claimed - used)
    if unevidenced:
        print("")
        print(f"  !! {len(unevidenced)} skill(s) claimed on your CV with NO fact to back them:")
        for s in unevidenced:
            print(f"       {s}")
        print("     Each is a question you could be asked and cannot answer with a story.")
        print("     Either write the fact that evidences it, or cut it from the CV.")

    unused = sorted(canonical - used - cv_claimed)
    if unused:
        print(f"\n  {len(unused)} vocab skills with no facts attached:")
        print("    " + ", ".join(unused[:14]) + (" ..." if len(unused) > 14 else ""))
        print("    (each is either a gap in the bank or a skill you should stop claiming)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="errors only")
    args = ap.parse_args()

    profile = load("profile.yaml")
    vocab = load("vocab.yaml")
    entities_doc = load("entities.yaml")
    facts_doc = load("facts.yaml")

    entities = entities_doc.get("entities") or []
    facts = facts_doc.get("facts") or []

    canonical, alias_map = build_skill_index(vocab)
    cv_claimed = {s["id"] for s in vocab.get("skills", []) if s.get("cv_claimed")}
    for a in profile.get("archetypes", []) or []:
        for field in ("profile", "match_text"):
            val = (a.get(field) or "").strip()
            if not val or val.startswith("TODO"):
                warn(f"archetype {a['id']}: '{field}' is missing or still a TODO "
                     f"-- Stage 2b cannot score jobs without match_text, and the CV "
                     f"renders with no opening paragraph without profile")

    entities_by_id = check_entities(entities)
    check_facts(facts, entities_by_id, canonical, alias_map, profile)

    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors:
            print(f"  x {e}")
    if warnings and not args.quiet:
        print(f"\nWARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  ! {w}")

    if not args.quiet:
        report(facts, entities, canonical, cv_claimed)

    print()
    if errors:
        print(f"FAILED -- {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"OK -- 0 errors, {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
