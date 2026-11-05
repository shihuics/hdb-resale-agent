"""Look up latitude/longitude for every HDB block in the resale data, using OneMap.

OneMap is the Singapore government's map service. Its search API needs no account.
Results are saved to dbt/seeds/block_coords.csv and REUSED on later runs, so only
new blocks are looked up. You can stop it (Ctrl + C) and run it again to continue.

Run from the repo root (quit any DuckDB session first):
    python ingest/geocode_blocks.py                 # all blocks not yet looked up
    python ingest/geocode_blocks.py --limit 50      # quick test on 50 blocks
    python ingest/geocode_blocks.py --retry-missing # try again for blocks not found before
"""
import argparse, csv, difflib, pathlib, re, sys, time
import duckdb
import requests

sys.path.insert(0, "agent")
from sql_agent import DB

URL = "https://www.onemap.gov.sg/api/common/elastic/search"
OUT = pathlib.Path("dbt/seeds/block_coords.csv")
FIELDS = ["block", "street_name", "postal", "latitude", "longitude", "match"]
PAUSE = 0.3  # seconds between calls, to stay well under OneMap's rate limit

# HDB data abbreviates street names; OneMap spells them out
ABBREV = {
    "AVE": "AVENUE", "ST": "STREET", "RD": "ROAD", "DR": "DRIVE", "CRES": "CRESCENT",
    "NTH": "NORTH", "STH": "SOUTH", "CTRL": "CENTRAL", "JLN": "JALAN", "BT": "BUKIT",
    "C'WEALTH": "COMMONWEALTH", "CL": "CLOSE", "PL": "PLACE", "LOR": "LORONG",
    "TER": "TERRACE", "UPP": "UPPER", "KG": "KAMPONG", "TG": "TANJONG", "PK": "PARK",
    "GDNS": "GARDENS", "HTS": "HEIGHTS", "CTR": "CENTRE", "MKT": "MARKET", "SQ": "SQUARE",
    "BLVD": "BOULEVARD", "VW": "VIEW", "MT": "MOUNT", "HWY": "HIGHWAY",
}


def expand(street):
    return " ".join(ABBREV.get(w, w) for w in street.upper().split())


def blocks_in_data():
    con = duckdb.connect(DB, read_only=True)
    try:
        return con.execute(
            "SELECT DISTINCT block, street_name FROM fct_resale ORDER BY 2, 1").fetchall()
    finally:
        con.close()


def load_existing():
    if not OUT.exists():
        return []
    with OUT.open() as fh:
        return list(csv.DictReader(fh))


def search(session, text):
    params = {"searchVal": text, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1}
    for attempt in range(4):
        try:
            r = session.get(URL, params=params, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json().get("results", [])
        except (requests.RequestException, ValueError):
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))  # back off, then retry


def lookup(session, block, street):
    """Return (postal, lat, lon, match) for one block."""
    wanted = expand(street)
    results = search(session, f"{block} {street}")
    same_block = [x for x in results if str(x.get("BLK_NO", "")).upper() == block.upper()]
    if not same_block:
        return "", "", "", "not_found"

    def road_score(x):
        return difflib.SequenceMatcher(None, wanted, str(x.get("ROAD_NAME", "")).upper()).ratio()

    best = max(same_block, key=road_score)
    match = "exact" if road_score(best) >= 0.8 else "check"
    return (str(best.get("POSTAL", "")), best.get("LATITUDE", ""),
            best.get("LONGITUDE", ""), match)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--limit", type=int, help="only look up this many blocks (for testing)")
    p.add_argument("--retry-missing", action="store_true", help="retry blocks not found last time")
    args = p.parse_args()

    existing = load_existing()
    if args.retry_missing:
        existing = [r for r in existing if r["match"] != "not_found"]
    done = {(r["block"], r["street_name"]) for r in existing}
    todo = [b for b in blocks_in_data() if b not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(done)} blocks already saved, {len(todo)} to look up "
          f"(about {len(todo) * (PAUSE + 0.2) / 60:.0f} min)")
    if not todo:
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Rewrite the kept rows, then append new ones as we go (so progress survives a stop)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(existing)
        fh.flush()

        session = requests.Session()
        counts = {"exact": 0, "check": 0, "not_found": 0}
        for i, (block, street) in enumerate(todo, 1):
            postal, lat, lon, match = lookup(session, block, street)
            counts[match] += 1
            w.writerow({"block": block, "street_name": street, "postal": postal,
                        "latitude": lat, "longitude": lon, "match": match})
            fh.flush()
            if i % 100 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}  found {counts['exact'] + counts['check']}, "
                      f"not found {counts['not_found']}")
            time.sleep(PAUSE)

    print(f"Saved to {OUT}: {counts['exact']} exact, {counts['check']} to check "
          f"(street name differed), {counts['not_found']} not found")
    if counts["not_found"]:
        print("Blocks not found get no MRT distance. Try --retry-missing later, or check them "
              "on onemap.gov.sg.")


if __name__ == "__main__":
    main()