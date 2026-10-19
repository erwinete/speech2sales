import httpx

BASE = "http://localhost:8000"
KEY = "dev-insecure-token"

top = httpx.get(f"{BASE}/api/v1/risks/top?limit=1", headers={"X-Api-Key": KEY}, timeout=10).json()
cid = top["items"][0]["contact_id"]
print("contact:", cid, "| score:", top["items"][0]["score"])

r = httpx.get(f"{BASE}/api/v1/contacts/{cid}/calls", headers={"X-Api-Key": KEY}, timeout=10)
print("contact calls:", r.status_code, "| total:", r.json().get("total"))
