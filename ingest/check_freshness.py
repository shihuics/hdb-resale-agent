import os, pathlib, requests

URL = "https://api-production.data.gov.sg/v2/public/api/collections/189/metadata"
STATE = pathlib.Path("state/last_updated.txt")

latest = requests.get(URL, timeout=30).json()["data"]["collectionMetadata"]["lastUpdatedAt"]
previous = STATE.read_text().strip() if STATE.exists() else ""
changed = latest != previous
if changed:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(latest)

with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
    f.write(f"changed={'true' if changed else 'false'}\n")
print(latest, "changed" if changed else "unchanged")