"""Download LTA MRT/LRT station exit locations and save them as a dbt seed.

Source: "LTA MRT Station Exit (GEOJSON)" on data.gov.sg (updated about every 6 months).
Output: dbt/seeds/mrt_exits.csv with one row per station exit.

Run from the repo root:
    python ingest/get_mrt_exits.py
"""
import csv, json, pathlib, re, time
import requests

DATASET_ID = "d_b39d3a0871985372d7e1637193335da5"
BASE = f"https://api-open.data.gov.sg/v1/public/api/datasets/{DATASET_ID}"
OUT = pathlib.Path("dbt/seeds/mrt_exits.csv")


def download_geojson():
    # Same two-step flow as ingest/download.py: start the download, then poll for a link
    requests.get(f"{BASE}/initiate-download", timeout=30).raise_for_status()
    url, resp = None, None
    for _ in range(10):
        resp = requests.get(f"{BASE}/poll-download", timeout=30).json()
        url = (resp.get("data") or {}).get("url")
        if url:
            break
        time.sleep(3)
    if not url:
        raise SystemExit(f"No download URL returned: {resp}")
    return requests.get(url, timeout=120).json()


def field(props, name):
    """Read a property directly, or from the HTML table some data.gov.sg GeoJSON files use."""
    if props.get(name):
        return str(props[name]).strip()
    desc = props.get("Description") or ""
    m = re.search(rf"<th>{name}</th>\s*<td>(.*?)</td>", desc, re.S)
    return m.group(1).strip() if m else ""


def main():
    data = download_geojson()
    rows = []
    for f in data.get("features", []):
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        if not (1.1 < lat < 1.5 and 103.5 < lon < 104.1):
            raise SystemExit(f"Unexpected coordinates {lat}, {lon}: the file may not be in "
                             "latitude/longitude. Stop and check the dataset format.")
        props = f.get("properties") or {}
        station = field(props, "STATION_NA").upper()
        if not station:
            continue
        rows.append({
            "station": station,
            "exit_code": field(props, "EXIT_CODE"),
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "is_lrt": "true" if "LRT" in station and "MRT" not in station else "false",
        })

    if not rows:
        raise SystemExit("No station exits found. Check the dataset on data.gov.sg.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    stations = {r["station"] for r in rows}
    lrt = {r["station"] for r in rows if r["is_lrt"] == "true"}
    print(f"Saved {len(rows)} exits across {len(stations)} stations "
          f"({len(lrt)} LRT) to {OUT}")


if __name__ == "__main__":
    main()