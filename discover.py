#!/usr/bin/env python3
"""Stage 1 — job discovery: fetch, normalise, deduplicate, filter.

    python discover.py                    # every enabled source
    python discover.py --source remoteok  # one source
    python discover.py --dry-run          # show what would be written, write nothing
    python discover.py --list             # sources and their status
    python discover.py --reset-seen       # forget dedup history

Writes one YAML per surviving job into jobs/, in exactly the shape tailor.py consumes:

    python discover.py && python tailor.py jobs/<slug>.yaml

------------------------------------------------------------------------------
DESIGN NOTES

NO SCRAPING. Every source is an official API, a published RSS feed, or an alert email you
subscribed to. Not because scraping is difficult, but because the downside is losing the
account you are job-searching with, mid-search. See sources.yaml for what was tested and
what each site actually permits.

THE FILTER IS DELIBERATELY STUPID AND FREE. Stage 2a is string matching on titles and
descriptions -- no model, no API call. It removes the majority of postings for nothing,
which is what makes it affordable to be more careful later. Kill cheaply, then think
expensively.

DEDUPLICATION IS THE REAL WORK HERE. The same job appears on five boards with five
different ids and slightly different titles. Two layers: an exact hash of normalised
company+title+location, and a near-duplicate check for the same company posting almost the
same title within a fortnight. Neither is clever. Both are necessary, and normalising
company names is where the fiddly cases live -- "Zalando SE", "Zalando", "zalando.de".
Ship the 90% version, watch what leaks, fix only what actually appears.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required:  pip install pyyaml")

HERE = Path(__file__).parent
JOBS = HERE / "jobs"
STATE = HERE / ".state"
SEEN = STATE / "seen.json"

UA = "Mozilla/5.0 (compatible; cv-fact-bank job discovery; +https://github.com/Sylvain-gitty)"
LEGAL_SUFFIXES = r"\b(gmbh|ag|se|ug|kg|ohg|mbh|inc|llc|ltd|limited|bv|nv|sarl|sas|sa|oy|ab|as|aps|plc|co|corp|company|group|holding|international|deutschland|germany)\b"


# --------------------------------------------------------------------------- helpers

try:                                    # job titles are UTF-8; Windows consoles are cp1252
    sys.stdout.reconfigure(errors="replace")
except Exception:                       # noqa: BLE001
    pass


def log(msg=""):
    print(msg, flush=True)


def strip_html(text) -> str:
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", str(text), flags=re.I)
    text = re.sub(r"</p>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", unescape(text)).strip()


def norm_company(name) -> str:
    """Normalise a company name for deduplication.

    Lowercase, strip legal suffixes, strip punctuation. This gets ~90% of real cases in
    ten lines. Do not gold-plate it -- run it, look at what still slips through, and fix
    only the failures you actually observe.
    """
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"https?://|www\.|\.(com|de|io|ai|co|org|net)\b", " ", s)
    s = re.sub(LEGAL_SUFFIXES, " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def norm_title(title) -> str:
    s = unicodedata.normalize("NFKD", str(title or "")).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"\((m/w/d|w/m/d|m/f/d|f/m/d|all genders|d/f/m)\)", " ", s)
    s = re.sub(r"\b(m/w/d|w/m/d|m/f/d|f/m/d|mwd)\b", " ", s)
    s = re.sub(r"[^a-z0-9+#]+", " ", s)
    return " ".join(s.split())


def job_key(company, title, location) -> str:
    raw = f"{norm_company(company)}|{norm_title(title)}|{norm_title(location)[:24]}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def slugify(*parts) -> str:
    s = unicodedata.normalize("NFKD", " ".join(str(p or "") for p in parts))
    s = s.encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")[:70] or "job"


def fetch(url, headers=None, timeout=45) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def dig(obj, path):
    """Read a possibly nested field. Falls back to str() for dicts like {'name': ...}."""
    if obj is None or path is None:
        return None
    cur = obj
    for part in str(path).split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    if isinstance(cur, dict):
        for k in ("name", "title", "label", "value", "ort", "arbeitgeber"):
            if k in cur:
                return cur[k]
        return json.dumps(cur, ensure_ascii=False)
    if isinstance(cur, list):
        return ", ".join(str(x) for x in cur if not isinstance(x, (dict, list)))
    return cur


# --------------------------------------------------------------------------- adapters

def from_json_api(src) -> list[dict]:
    url = src["url"]
    if src.get("params"):
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(src["params"])
    headers = {}
    if src.get("auth_env"):
        import os
        key = os.environ.get(src["auth_env"])
        if not key:
            raise RuntimeError(f"{src['auth_env']} not set in the environment")
        headers[src.get("auth_header", "X-API-Key")] = key

    payload = json.loads(fetch(url, headers))
    records = payload.get(src["root"], []) if src.get("root") else payload
    if not isinstance(records, list):
        raise RuntimeError(f"expected a list of jobs, got {type(records).__name__}")
    if src.get("skip_first_record"):
        records = records[1:]

    m, out = src.get("map", {}), []
    for r in records:
        if not isinstance(r, dict):
            continue
        out.append({
            "title": dig(r, m.get("title")),
            "company": dig(r, m.get("company")),
            "location": dig(r, m.get("location")),
            "url": dig(r, m.get("url")),
            "posted_at": dig(r, m.get("posted_at")),
            "description": strip_html(dig(r, m.get("description"))),
            "salary_raw": dig(r, m.get("salary_raw")),
            "tags": dig(r, m.get("tags")),
        })
    return out


def from_rss(src) -> list[dict]:
    root = ET.fromstring(fetch(src["url"]))
    out = []
    for item in root.iter("item"):
        def t(tag):
            el = item.find(tag)
            return el.text if el is not None else None
        desc = t("description") or ""
        enc = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
        if enc is not None and enc.text and len(enc.text) > len(desc):
            desc = enc.text
        title = t("title") or ""
        # Feeds commonly pack "Role at Company" or "Role – Company" into the title.
        company = None
        for sep in (" at ", " @ ", " – ", " — "):
            if sep in title:
                title, company = title.split(sep, 1)[0].strip(), title.split(sep, 1)[1].strip()
                break
        out.append({
            "title": title,
            "company": company,
            "location": None,
            "url": t("link"),
            "posted_at": t("pubDate"),
            "description": strip_html(desc),
            "salary_raw": None,
            "tags": ", ".join(c.text for c in item.findall("category") if c.text) or None,
        })
    return out


ADAPTERS = {"json_api": from_json_api, "rss": from_rss}


# --------------------------------------------------------------------------- filtering

def passes_rules(job, rules) -> tuple[bool, str]:
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "").lower()
    loc = (job.get("location") or "").lower()

    if not job.get("title") or not job.get("url"):
        return False, "missing title or url"

    # WORD BOUNDARIES, not substrings. The first version matched "ai" inside "retail",
    # "maintenance", "captain" and "mail", which is how a Bell Captain and a Rural Mail
    # Carrier reached the shortlist. Short tokens are exactly where naive `in` fails.
    require = rules.get("require_any_in_title", [])
    if require and not any(
            re.search(r'\b' + re.escape(t.lower().strip()) + r'\b', title) for t in require):
        return False, "title matches no target role term"

    for term in rules.get("drop_title_contains", []):
        if term.lower() in title:
            return False, f"title contains '{term}'"
    for term in rules.get("drop_description_contains", []):
        if term.lower() in desc:
            return False, f"description contains '{term}'"
    for lock in rules.get("drop_if_region_locked", []):
        if lock.lower() in desc or lock.lower() in loc:
            return False, f"region-locked: '{lock}'"

    if len(desc) < rules.get("min_description_chars", 0):
        return False, f"description too short ({len(desc)} chars)"

    allow = [c.lower() for c in rules.get("countries_allow", [])]
    if allow and loc:
        remote = job.get("remote_flag") or "remote" in loc or "anywhere" in loc
        hit = remote and "remote" in allow
        hit = hit or any(a in loc for a in ("de", "germany", "deutschland") if "de" in allow)
        hit = hit or ("eu" in allow and any(
            w in loc for w in ("europe", "eu", "berlin", "munich", "hamburg", "amsterdam")))
        if not hit:
            return False, f"location '{job.get('location')}' outside allowed regions"
    return True, ""


def near_duplicate(job, kept) -> str | None:
    """Same company, near-identical title, close in time. Word-overlap, not embeddings."""
    c, t = norm_company(job["company"]), set(norm_title(job["title"]).split())
    if not c or not t:
        return None
    for other in kept:
        if norm_company(other["company"]) != c:
            continue
        ot = set(norm_title(other["title"]).split())
        if not ot:
            continue
        overlap = len(t & ot) / max(len(t), len(ot))
        if overlap >= 0.8:
            return other["job_id"]
    return None


# --------------------------------------------------------------------------- driver

def load_seen() -> dict:
    if SEEN.exists():
        return json.loads(SEEN.read_text(encoding="utf-8"))
    return {}


def prune_seen(seen, days=60) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return {k: v for k, v in seen.items() if v.get("first_seen", "") >= cutoff}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", help="only these source ids")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--reset-seen", action="store_true")
    ap.add_argument("--limit", type=int, default=40, help="max new jobs written per run")
    args = ap.parse_args()

    cfg = yaml.safe_load((HERE / "sources.yaml").read_text(encoding="utf-8"))
    rules = cfg.get("rules", {})
    sources = cfg.get("sources", [])

    if args.list:
        log("\nFETCHED SOURCES")
        for s in sources:
            mark = "on " if s.get("enabled") else "off"
            log(f"  [{mark}] {s['id']:<18} {s['type']:<9} {s['label']}")
        log("\nEMAIL-ALERT SOURCES (n8n IMAP trigger owns these, not this script)")
        for s in cfg.get("email_alert_sources", []):
            log(f"        {s['id']:<18} {'email':<9} {s['label']}")
        boards = cfg.get("company_boards") or []
        log(f"\nCOMPANY BOARDS: {len(boards)} configured"
            + ("  <-- the highest-signal tier, and it is empty" if not boards else ""))
        return 0

    if args.reset_seen and SEEN.exists():
        SEEN.unlink()
        log("dedup history cleared")

    seen = prune_seen(load_seen())
    JOBS.mkdir(exist_ok=True)
    STATE.mkdir(exist_ok=True)

    kept, stats = [], []
    for src in sources:
        if not src.get("enabled"):
            continue
        if args.source and src["id"] not in args.source:
            continue
        log(f"\n{src['label']}  [{src['id']}]")
        try:
            raw = ADAPTERS[src["type"]](src)
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            log(f"  network error: {e}  -- skipped, other sources continue")
            stats.append((src["id"], 0, 0, 0, "network error"))
            continue
        except Exception as e:                                   # noqa: BLE001
            log(f"  failed: {type(e).__name__}: {e}")
            stats.append((src["id"], 0, 0, 0, str(e)[:40]))
            continue

        dropped_rules = dropped_dupe = 0
        new_here = []
        for job in raw:
            job = {**src.get("defaults", {}), **{k: v for k, v in job.items() if v is not None}}
            job["source"] = src["id"]
            ok, why = passes_rules(job, rules)
            if not ok:
                dropped_rules += 1
                continue
            job["job_id"] = job_key(job.get("company"), job["title"], job.get("location"))
            if job["job_id"] in seen:
                dropped_dupe += 1
                continue
            dup = near_duplicate(job, kept + new_here)
            if dup:
                dropped_dupe += 1
                continue
            new_here.append(job)

        kept.extend(new_here)
        log(f"  {len(raw)} fetched | {dropped_rules} filtered | {dropped_dupe} duplicate "
            f"| {len(new_here)} new")
        stats.append((src["id"], len(raw), dropped_rules, dropped_dupe, ""))

    kept.sort(key=lambda j: str(j.get("posted_at") or ""), reverse=True)
    kept = kept[:args.limit]

    log(f"\n{'=' * 66}\n{len(kept)} new job(s)")
    written = 0
    for job in kept:
        slug = slugify(job.get("company"), job.get("title"))
        path = JOBS / f"{slug}.yaml"
        log(f"  {job.get('company') or '?':<26.26} {job['title'][:44]}")
        if args.dry_run:
            continue
        doc = {
            "title": job["title"], "company": job.get("company"),
            "location": job.get("location"), "url": job.get("url"),
            "source": job["source"], "language": job.get("language", "en"),
            "posted": str(job.get("posted_at") or ""),
            "salary_raw": job.get("salary_raw"), "tags": job.get("tags"),
            "description": job.get("description", ""),
            # requirements deliberately left out: tailor.py extracts them heuristically,
            # and Plan 01 Stage 2c will fill them properly once it exists.
        }
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False,
                                       default_flow_style=False, width=95), encoding="utf-8")
        seen[job["job_id"]] = {"first_seen": datetime.now(timezone.utc).isoformat(),
                               "source": job["source"], "slug": slug}
        written += 1

    if not args.dry_run:
        SEEN.write_text(json.dumps(seen, indent=2), encoding="utf-8")
        log(f"\nwrote {written} file(s) to jobs/   ({len(seen)} ids in dedup history)")
        if written:
            log("\nNext:  python tailor.py jobs/<slug>.yaml --explain")
            log("Stage 2a has run. Reading these and deciding which to pursue is Gate 1,")
            log("and it is yours -- every keep/skip is also a training label for later.")
    else:
        log("\ndry run: nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
