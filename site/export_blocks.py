"""Export per-block resale prices to site/blocks.json for the map page.

For every block with coordinates, and every flat type sold there in the last
12 months: number of sales, median price, median price per sqm, the price range,
the most recent sales, and the change in price per sqm versus the 12 months before
(only when both periods have enough sales to compare).

Run from the repo root (after `dbt build`):
    python site/export_blocks.py
Then preview locally:
    python -m http.server 8000 --directory site
and open http://localhost:8000
"""
import json, pathlib, sys
import duckdb
import pandas as pd

DB = sys.argv[1] if len(sys.argv) > 1 else "hdb.duckdb"
OUT = pathlib.Path("site/blocks.json")
WINDOW_MONTHS = 12
RECENT_SALES = 8
MIN_SALES_FOR_CHANGE = 3  # per period, before a year-over-year change is shown


def main():
    con = duckdb.connect(DB, read_only=True)
    try:
        latest = con.execute("SELECT MAX(txn_month) FROM fct_resale").fetchone()[0]
        df = con.execute(
            f"""SELECT block, street_name, town, flat_type, txn_month, storey_range,
                       floor_area_sqm, resale_price, price_psm, lease_start_year,
                       latitude, longitude, nearest_mrt, mrt_distance_m
                FROM fct_resale
                WHERE latitude IS NOT NULL
                  AND txn_month > (SELECT MAX(txn_month) FROM fct_resale)
                                  - INTERVAL {2 * WINDOW_MONTHS} MONTH
                ORDER BY txn_month DESC""").df()
    finally:
        con.close()

    if df.empty:
        raise SystemExit("No sales with coordinates found. Run the MRT/geocoding steps and dbt build first.")

    cutoff = pd.Timestamp(latest) - pd.DateOffset(months=WINDOW_MONTHS)
    df["txn_month"] = pd.to_datetime(df["txn_month"])
    previous = df[df["txn_month"] <= cutoff]
    df = df[df["txn_month"] > cutoff]
    prev_psm = previous.groupby(["block", "street_name", "flat_type"])["price_psm"].agg(["median", "count"])

    blocks = {}
    for (block, street, ftype), g in df.groupby(["block", "street_name", "flat_type"], sort=False):
        first = g.iloc[0]
        key = (block, street)
        if key not in blocks:
            blocks[key] = {
                "b": block, "s": street, "t": first["town"],
                "la": round(float(first["latitude"]), 5), "lo": round(float(first["longitude"]), 5),
                "m": first["nearest_mrt"] or "",
                "md": int(first["mrt_distance_m"]) if first["mrt_distance_m"] == first["mrt_distance_m"] else None,
                "ly": int(first["lease_start_year"]),
                "f": {},
            }
        recent = g.head(RECENT_SALES)
        q = g["price_psm"].median()
        change = None
        if len(g) >= MIN_SALES_FOR_CHANGE and (block, street, ftype) in prev_psm.index:
            prev = prev_psm.loc[(block, street, ftype)]
            if prev["count"] >= MIN_SALES_FOR_CHANGE:
                change = round(float(q / prev["median"] - 1), 3)
        blocks[key]["f"][ftype] = {
            "n": int(len(g)),
            "p": int(round(g["resale_price"].median(), -3)),
            "q": int(round(q)),
            "y": change,
            "lo": int(g["resale_price"].min()),
            "hi": int(g["resale_price"].max()),
            "r": [[r.txn_month.strftime("%Y-%m"), r.storey_range, int(r.floor_area_sqm), int(r.resale_price)]
                  for r in recent.itertuples()],
        }

    start = pd.Timestamp(latest) - pd.DateOffset(months=WINDOW_MONTHS - 1)
    flat_types = sorted(df["flat_type"].unique(),
                        key=lambda t: (t[0] if t[0].isdigit() else "9", t))
    out = {
        "latest": pd.Timestamp(latest).strftime("%b %Y"),
        "window": f"{start:%b %Y} – {pd.Timestamp(latest):%b %Y}",
        "flat_types": flat_types,
        "blocks": list(blocks.values()),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print(f"Saved {len(out['blocks']):,} blocks ({len(df):,} sales, {out['window']}) "
          f"to {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()