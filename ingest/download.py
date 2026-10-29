import time, pathlib, requests

DATASET_ID = "d_8b84c4ee58e3cfc0ece0d773c8ca6abc"
BASE = f"https://api-open.data.gov.sg/v1/public/api/datasets/{DATASET_ID}"
OUT = pathlib.Path("data/raw/resale_2017_onwards.csv")

requests.get(f"{BASE}/initiate-download", timeout=30).raise_for_status()
url = None
for _ in range(10):
    resp = requests.get(f"{BASE}/poll-download", timeout=30).json()
    url = (resp.get("data") or {}).get("url")
    if url:
        break
    time.sleep(3)
if not url:
    raise SystemExit(f"No download URL returned: {resp}")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_bytes(requests.get(url, timeout=120).content)
print(f"Saved {OUT} ({OUT.stat().st_size/1e6:.1f} MB)")