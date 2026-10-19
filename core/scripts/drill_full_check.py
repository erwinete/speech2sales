import httpx

BASE = "http://localhost:8000"
KEY = "dev-insecure-token"
H = {"X-Api-Key": KEY}

top = httpx.get(f"{BASE}/api/v1/risks/top?limit=1", headers=H, timeout=10).json()
row = top["items"][0]
cid = row["contact_id"]
print("risks/top contact:", cid, "| score:", row["score"], "| recent_call_ids:", len(row.get("recent_call_ids", [])))

r = httpx.get(f"{BASE}/api/v1/contacts/{cid}/calls", headers=H, timeout=10)
print("contact calls:", r.status_code, "| total:", r.json().get("total"))

cl = httpx.get(f"{BASE}/api/v1/insights/objection-clusters?days=90", headers=H, timeout=30).json()
print("clusters:", len(cl.get("clusters", [])))
for c in cl.get("clusters", [])[:2]:
    print("  size:", c["size"], "| calls:", [x["call_id"][:8] for x in c.get("calls", [])])
