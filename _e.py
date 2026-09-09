import json, yaml, sys
from pathlib import Path
sys.stdout.reconfigure(errors="replace")
sc = json.loads(Path(".state/scores.json").read_text(encoding="utf-8"))
pre = set(json.loads(Path("_pre_jobs.json").read_text(encoding="utf-8")))

# How many of the 32 new ones are actually reachable from Berlin?
berlin, germany, other = [], [], []
for p in Path("jobs").glob("*.yaml"):
    if p.stem in pre or p.stem not in sc:
        continue
    j = yaml.safe_load(p.read_text(encoding="utf-8"))
    loc = str(j.get("location") or "").lower()
    row = (sc[p.stem]["relative"], str(j.get("company") or "?")[:22], str(j.get("title"))[:44])
    if "berlin" in loc:
        berlin.append(row)
    elif any(x in loc for x in ("german", "hamburg", "münchen", "munich", "köln", "cologne",
                                "düsseldorf", "frankfurt", "saxony", "remote")):
        germany.append(row)
    else:
        other.append(row)
for label, rows in (("BERLIN", berlin), ("GERMANY / REMOTE-DE", germany), ("ELSEWHERE", other)):
    print(f"\n{label}  ({len(rows)})")
    for r in sorted(rows, reverse=True)[:8]:
        print(f"   [{r[0]:>3}] {r[1]:<22} {r[2]}")

print("\n\nFULL DESCRIPTION — Enpal Analytics Engineer (m/f/d)")
print("=" * 92)
for p in Path("jobs").glob("*.yaml"):
    j = yaml.safe_load(p.read_text(encoding="utf-8"))
    if j.get("company") == "Enpal" and "Analytics Engineer (m/f/d)" in str(j.get("title")):
        d = " ".join(str(j.get("description") or "").split())
        print(d[:1900])
        break
