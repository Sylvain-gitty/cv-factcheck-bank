import json
from pathlib import Path
jobs = sorted(p.stem for p in Path("jobs").glob("*.yaml"))
Path("../../../AppData/Local/Temp/claude/pre_jobs.json").parent.mkdir(parents=True, exist_ok=True)
Path("_pre_jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
seen = Path(".state/seen.json")
n_seen = len(json.loads(seen.read_text(encoding="utf-8"))) if seen.exists() else 0
print(f"before this run: {len(jobs)} job file(s), {n_seen} id(s) in dedup history")
sc = Path(".state/scores.json")
if sc.exists():
    d = json.loads(sc.read_text(encoding="utf-8"))
    top = sorted(d, key=lambda x: -d[x]["relative"])[:3]
    print("previous top 3:")
    for s in top:
        print(f"  [{d[s]['relative']:>3}] {s[:60]}")
