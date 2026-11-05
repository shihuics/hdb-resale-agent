"""/valuation: estimate a flat's fair price from comparable recent sales.

Steps:
1. Claude extracts block, street, flat type, floor and size from free text.
2. The block is looked up in the data to find its town and lease start year.
3. Comparable sales: same town and flat type, last 24 months.
4. A small regression learns how price per sqm moves with floor, remaining lease
   and time, then predicts the price for this flat. The spread of past sales
   around that prediction gives the range.
"""
import json, re, difflib
import duckdb
import numpy as np
import pandas as pd

from sql_agent import ask_llm, DB

FLAT_TYPES = ["1 ROOM", "2 ROOM", "3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE", "MULTI-GENERATION"]
LOOKBACK_MONTHS = 24
MIN_COMPS = 15

EXTRACT_PROMPT = f"""Extract HDB flat details from the user's message.
Return only a JSON object with these keys:
- "block": the block number as a string, e.g. "406" or "123A"
- "street": the street name written the way HDB writes it (upper case, with
  abbreviations such as AVE, ST, RD, DR, CRES, NTH, STH, JLN for JALAN, BT for BUKIT),
  expanding nicknames like AMK to ANG MO KIO; null if not given
- "flat_type": one of {FLAT_TYPES}
- "storey": the floor as an integer, or null if not given
- "floor_area_sqm": the size in square metres as a number, or null if not given
Return nothing except the JSON."""


class ValuationError(Exception):
    """A problem to show the user as a plain message."""


def _fetch(sql, params=None):
    con = duckdb.connect(DB, read_only=True)
    try:
        return con.execute(sql, params or []).fetchall()
    finally:
        con.close()


def _fetch_df(sql, params=None):
    con = duckdb.connect(DB, read_only=True)
    try:
        return con.execute(sql, params or []).df()
    finally:
        con.close()


def _has_column(name):
    rows = _fetch("SELECT 1 FROM information_schema.columns "
                  "WHERE table_name = 'fct_resale' AND column_name = ?", [name])
    return bool(rows)


# ---------- 1. understand the request ----------

def parse_request(text):
    raw = ask_llm(EXTRACT_PROMPT, text, max_tokens=500)
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        raise ValuationError("Sorry, I couldn't read the flat details. Try: "
                             "/valuation 3 room, blk 406 Ang Mo Kio Ave 10, 10th floor, 67 sqm")
    d = json.loads(match.group(0))
    block = str(d.get("block") or "").strip().upper()
    flat_type = str(d.get("flat_type") or "").strip().upper()
    if not block:
        raise ValuationError("Please include the block number, e.g. blk 406.")
    if flat_type not in FLAT_TYPES:
        raise ValuationError("Please include the flat type, e.g. 3 room, 4 room, 5 room or executive.")
    street = (d.get("street") or "").strip().upper() or None
    storey = d.get("storey")
    area = d.get("floor_area_sqm")
    return {
        "block": block,
        "street": street,
        "flat_type": flat_type,
        "storey": int(storey) if storey not in (None, "") else None,
        "floor_area_sqm": float(area) if area not in (None, "") else None,
    }


# ---------- 2. find the flat ----------

def locate(block, street):
    rows = _fetch(
        """SELECT street_name, town, MAX(lease_start_year)
           FROM fct_resale WHERE block = ?
           GROUP BY 1, 2""", [block])
    if not rows:
        raise ValuationError(f"I couldn't find any resale records for block {block}.")
    options = ", ".join(f"{s} ({t.title()})" for s, t, _ in rows[:6])
    if street:
        scored = sorted(rows, key=lambda r: difflib.SequenceMatcher(None, street, r[0]).ratio(),
                        reverse=True)
        best = scored[0]
        if difflib.SequenceMatcher(None, street, best[0]).ratio() < 0.5:
            raise ValuationError(f"Block {block} exists on: {options}. Which street did you mean?")
        return best
    if len(rows) == 1:
        return rows[0]
    raise ValuationError(f"Block {block} exists on several streets: {options}. "
                         "Please add the street name.")


# ---------- 3 & 4. comparable sales and the estimate ----------

BLOCK_SHRINK = 5  # how many sales a block needs before its own pattern counts for half


MRT_CAP_M = 2000  # beyond this, extra distance from an MRT is treated as the same


def estimate(req, as_of=None, lookback_months=LOOKBACK_MONTHS, min_comps=MIN_COMPS,
             use_area=True, block_adjust=True, use_mrt=True):
    """Estimate a flat's value.

    as_of:        value the flat as at this month, using only sales before it (for backtesting).
                  None means "now", using all data up to the latest month.
    use_area:     include floor area in the formula (bigger flats tend to sell for less per sqm).
    block_adjust: nudge the estimate by how this block usually sells versus the town pattern.
    use_mrt:      include distance to the nearest MRT (needs the geocoded data; skipped if absent).
    """
    street, town, lease_start = locate(req["block"], req["street"])
    flat_type = req["flat_type"]

    if as_of is None:
        window = (f"txn_month > (SELECT MAX(txn_month) FROM fct_resale) "
                  f"- INTERVAL {lookback_months} MONTH")
        params = [town, flat_type]
    else:
        window = (f"txn_month < CAST(? AS DATE) "
                  f"AND txn_month >= CAST(? AS DATE) - INTERVAL {lookback_months} MONTH")
        params = [town, flat_type, as_of, as_of]

    mrt_available = use_mrt and _has_column("mrt_distance_m")
    mrt_cols = ", mrt_distance_m, nearest_mrt" if mrt_available else ""
    comps = _fetch_df(
        f"""SELECT txn_month, block, street_name, storey_range, storey_mid,
                   floor_area_sqm, remaining_lease_years, price_psm, resale_price{mrt_cols}
            FROM fct_resale
            WHERE town = ? AND flat_type = ? AND {window}""",
        params)
    if len(comps) < min_comps:
        raise ValuationError(
            f"Only {len(comps)} {flat_type.lower()} sales in {town.title()} in the last "
            f"{lookback_months} months, too few for a reliable estimate.")

    latest = comps["txn_month"].max() if as_of is None else pd.Timestamp(as_of)
    months_ago = ((latest.year - comps["txn_month"].dt.year) * 12
                  + (latest.month - comps["txn_month"].dt.month)).astype(float)

    # The flat's own attributes, filling gaps from sales in the same block
    in_block = (comps["block"] == req["block"]) & (comps["street_name"] == street)
    same_block = comps[in_block]
    notes = []
    storey = req["storey"]
    if storey is None:
        storey = float((same_block if len(same_block) else comps)["storey_mid"].median())
        notes.append(f"floor not given, assumed a typical floor (~{storey:.0f})")
    area = req["floor_area_sqm"]
    if area is None:
        area = float((same_block if len(same_block) else comps)["floor_area_sqm"].median())
        notes.append(f"size not given, assumed {area:.0f} sqm")
    remaining_lease = lease_start + 99 - (latest.year + (latest.month - 1) / 12)

    # Regression: price_psm ~ storey + remaining lease + months ago (+ floor area)
    columns = [np.ones(len(comps)), comps["storey_mid"], comps["remaining_lease_years"], months_ago]
    target = [1.0, storey, remaining_lease, 0.0]
    area_in_model = use_area and comps["floor_area_sqm"].std() > 1  # skip if all flats are one size
    if area_in_model:
        columns.append(comps["floor_area_sqm"])
        target.append(area)

    # MRT distance: only if this block has one and most comparable sales do too
    mrt_m, nearest_mrt, mrt_in_model = None, None, False
    if mrt_available:
        loc = _fetch("SELECT any_value(mrt_distance_m), any_value(nearest_mrt) FROM fct_resale "
                     "WHERE block = ? AND street_name = ?", [req["block"], street])
        mrt_m, nearest_mrt = loc[0] if loc else (None, None)
        coverage = comps["mrt_distance_m"].notna().mean()
        if mrt_m is not None and coverage >= 0.8 and comps["mrt_distance_m"].std() > 50:
            mrt_in_model = True
            dist = comps["mrt_distance_m"].fillna(comps["mrt_distance_m"].median())
            columns.append(dist.clip(upper=MRT_CAP_M))
            target.append(min(float(mrt_m), MRT_CAP_M))
    X = np.column_stack(columns)
    y = comps["price_psm"].to_numpy()
    X = X.astype(float)
    with np.errstate(all="ignore"):  # numpy on macOS can print false-alarm warnings here
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        psm = float(np.array(target, dtype=float) @ coef)
        residuals = pd.Series(y - X @ coef, index=comps.index)
    if not np.isfinite(psm) or not np.isfinite(residuals).all():
        raise ValuationError("Sorry, I couldn't calculate a reliable estimate for this flat.")

    # Block adjustment: how far above/below the formula does each block usually sell?
    # Shrunk towards zero when a block has few sales, so one odd sale can't swing it.
    block_adj, block_n = 0.0, int(in_block.sum())
    if block_adjust:
        keys = [comps["block"], comps["street_name"]]
        stats = residuals.groupby(keys).agg(["mean", "count"])
        shrunk = stats["mean"] * stats["count"] / (stats["count"] + BLOCK_SHRINK)
        per_sale = shrunk.reindex(pd.MultiIndex.from_arrays(keys)).to_numpy()
        residuals = residuals - per_sale  # spread left after block effects, for the range
        if block_n:
            block_adj = float(shrunk.loc[(req["block"], street)])
    psm += block_adj

    low_psm = psm + float(np.percentile(residuals, 25))
    high_psm = psm + float(np.percentile(residuals, 75))

    recent = same_block.sort_values("txn_month", ascending=False).head(5)
    return {
        "block": req["block"], "street": street, "town": town, "flat_type": flat_type,
        "storey": storey, "area": area, "remaining_lease": remaining_lease,
        "estimate": psm * area, "low": low_psm * area, "high": high_psm * area,
        "n_comps": len(comps), "per_floor": coef[1], "per_lease_year": coef[2],
        "per_month": coef[3], "per_sqm": coef[4] if area_in_model else None,
        "per_100m_mrt": coef[-1] * 100 if mrt_in_model else None,
        "mrt_m": mrt_m, "nearest_mrt": nearest_mrt,
        "block_adj": block_adj, "block_n": block_n,
        "lookback": lookback_months, "recent": recent, "notes": notes, "latest": latest,
    }


# ---------- 5. reply ----------

def _k(v):
    return f"S${round(v / 1000):,.0f}k"


def _station(name):
    """'ANG MO KIO MRT STATION' → 'Ang Mo Kio MRT'"""
    return name.upper().replace(" MRT STATION", "").title() + " MRT"


def format_reply(r):
    lines = [
        f"Estimated value: {_k(r['low'])} – {_k(r['high'])} (midpoint {_k(r['estimate'])})",
        f"{r['block']} {r['street']}, {r['town'].title()} · {r['flat_type']} · "
        f"floor ~{r['storey']:.0f} · {r['area']:.0f} sqm · ~{r['remaining_lease']:.0f} years lease left"
        + (f" · {r['mrt_m']:,.0f} m to {_station(r['nearest_mrt'])}" if r["mrt_m"] is not None else ""),
        "",
        f"Based on {r['n_comps']:,} {r['flat_type'].lower()} sales in {r['town'].title()} over the "
        f"last {r['lookback']} months, adjusted for floor, size, remaining lease"
        + (", distance to MRT" if r["per_100m_mrt"] is not None else "")
        + " and price movements over time.",
        f"In this town, each extra floor adds about S${r['per_floor']:,.0f} per sqm, and each extra year "
        f"of lease about S${r['per_lease_year']:,.0f} per sqm.",
    ]
    if r["per_100m_mrt"] is not None:
        effect = -r["per_100m_mrt"]
        word = "lowers" if effect > 0 else "raises"
        lines.append(f"Every extra 100 m from an MRT {word} the price by about "
                     f"S${abs(effect):,.0f} per sqm in this town.")
    if r["block_n"] and abs(r["block_adj"]) >= 10:
        direction = "above" if r["block_adj"] > 0 else "below"
        lines.append(f"This block has sold about S${abs(r['block_adj']):,.0f} per sqm {direction} similar "
                     f"flats in the town (based on {r['block_n']} recent sales), so the estimate "
                     f"is adjusted for that.")
    if r["notes"]:
        lines.append("Assumptions: " + "; ".join(r["notes"]) + ".")
    if len(r["recent"]):
        lines += ["", "Recent sales in this block:"]
        for _, s in r["recent"].iterrows():
            lines.append(f"• {s['txn_month']:%b %Y} · {s['storey_range']} · "
                         f"{s['floor_area_sqm']:.0f} sqm · S${s['resale_price']:,.0f}")
    lines += ["", f"Data up to {r['latest']:%b %Y}. A rough estimate from past sales, "
                  "not an official valuation."]
    return "\n".join(lines)


def valuation_reply(text):
    """Entry point for the bot: free text in, reply text out."""
    try:
        return format_reply(estimate(parse_request(text)))
    except ValuationError as e:
        return str(e)