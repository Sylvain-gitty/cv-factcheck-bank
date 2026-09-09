import json, yaml
from pathlib import Path
pre = set(json.loads(Path("_pre_jobs.json").read_text(encoding="utf-8")))
sc = json.loads(Path(".state/scores.json").read_text(encoding="utf-8"))
jobs = {p.stem: yaml.safe_load(p.read_text(encoding="utf-8"))
        for p in Path("jobs").glob("*.yaml")}
new = [s for s in sc if s not in pre]
new.sort(key=lambda s: -sc[s]["relative"])
print(f"{len(new)} NEW postings since 1 September, ranked\n")
print(f"{'':>5} {'score':>5}  {'archetype':<28} {'location':<26} title")
print("-" * 118)
for s in new[:18]:
    j, v = jobs[s], sc[s]
    amb = "~" if not v["archetype_confident"] else " "
    src = str(j.get("source", "")).replace("greenhouse-", "gh:").replace("ashby-", "ah:")
    print(f"{amb:>2}{v['relative']:>6}  {str(v['archetype_label'])[:28]:<28} "
          f"{str(j.get('location') or '-')[:26]:<26} {str(j.get('title'))[:40]}")
    print(f"{'':>10}{src:<20} {str(j.get('company') or '?')[:28]}")
