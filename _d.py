import json, yaml
from pathlib import Path
sc = json.loads(Path(".state/scores.json").read_text(encoding="utf-8"))
want = ["enpal", "eraneos", "celonis-client-value", "archimed", "joom", "n26-product"]
for p in sorted(Path("jobs").glob("*.yaml")):
    j = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not any(w in p.stem for w in want):
        continue
    v = sc.get(p.stem, {})
    if not v or v.get("relative", 0) < 30:
        continue
    print(f"\n{'='*96}")
    print(f"[{v['relative']}] {j.get('title')}  —  {j.get('company')}")
    print(f"     {j.get('location')}  ·  {j.get('source')}  ·  {v['archetype_label']}")
    print(f"     {j.get('url')}")
    d = " ".join(str(j.get("description") or "").split())
    print("     " + d[:620])
