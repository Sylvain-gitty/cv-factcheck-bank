import json, sys
sys.stdout.reconfigure(errors="replace")
d = json.load(open("/tmp/lv.json", encoding="utf-8"))
c = d.get("categories") or {}
print("title    :", d.get("text"))
print("location :", c.get("location"), "| team:", c.get("team"), "| type:", c.get("commitment"))
print("workplace:", d.get("workplaceType"))
print("url      :", d.get("hostedUrl"))
desc = d.get("descriptionPlain") or d.get("description") or ""
lists = " ".join(l.get("text", "") + " " + str(l.get("content", ""))
                 for l in (d.get("lists") or []))
print("desc     :", len(desc), "chars | lists:", len(lists), "chars")
print("\n--- DESCRIPTION ---")
print(" ".join(desc.split())[:1500])
