"""Backtest /valuation: how close are its estimates to real sale prices?

For a random sample of recent real sales, estimate each flat's price using ONLY
sales from before that month (as if the sale hadn't happened yet), then compare
the estimate with the price it actually sold for.

Run from the repo root:
    python evals/backtest_valuation.py
    python evals/backtest_valuation.py --n 500 --months 6

No Claude API calls are made, so it costs nothing to run.
"""
import argparse, sys, time
import duckdb
import pandas as pd

sys.path.insert(0, "agent")
sys.path.insert(0, "bot")
from valuation import estimate, ValuationError, LOOKBACK_MONTHS, MIN_COMPS, DB

OUT = "evals/valuation_backtest.csv"


def load_test_sales(n, months, seed):
    con = duckdb.connect(DB, read_only=True)
    try:
        df = con.execute(
            f"""SELECT txn_month, town, flat_type, block, street_name,
                       storey_mid, floor_area_sqm, remaining_lease_years, resale_price
                FROM fct_resale
                WHERE txn_month > (SELECT MAX(txn_month) FROM fct_resale) - INTERVAL {months} MONTH""",
        ).df()
    finally:
        con.close()
    return df.sample(n=min(n, len(df)), random_state=seed).reset_index(drop=True)


def run(sales, lookback, min_comps, use_area=True, block_adjust=True, use_mrt=True, quiet=False):
    results, skipped = [], {}
    for i, s in sales.iterrows():
        req = {"block": s["block"], "street": s["street_name"], "flat_type": s["flat_type"],
               "storey": float(s["storey_mid"]), "floor_area_sqm": float(s["floor_area_sqm"])}
        try:
            r = estimate(req, as_of=s["txn_month"].date(), lookback_months=lookback,
                         min_comps=min_comps, use_area=use_area, block_adjust=block_adjust,
                         use_mrt=use_mrt)
        except ValuationError as e:
            reason = str(e).split(",")[0][:60]
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        actual = float(s["resale_price"])
        results.append({
            "txn_month": s["txn_month"].date(), "town": s["town"], "flat_type": s["flat_type"],
            "block": s["block"], "street_name": s["street_name"],
            "storey_mid": s["storey_mid"], "floor_area_sqm": s["floor_area_sqm"],
            "remaining_lease_years": s["remaining_lease_years"],
            "actual": actual, "estimate": r["estimate"], "low": r["low"], "high": r["high"],
            "n_comps": r["n_comps"],
            "error_pct": (r["estimate"] - actual) / actual,
            "inside_range": r["low"] <= actual <= r["high"],
        })
        if not quiet and (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(sales)} done")
    return pd.DataFrame(results), skipped


def headline(df):
    e = df["error_pct"]
    return {"typical_error": e.abs().median(), "within_5": (e.abs() <= 0.05).mean(),
            "within_10": (e.abs() <= 0.10).mean(), "in_range": df["inside_range"].mean(),
            "bias": e.median(), "tested": len(df)}


VARIANTS = [
    ("v1 baseline", dict(use_area=False, block_adjust=False, use_mrt=False)),
    ("v2 + floor area", dict(use_area=True, block_adjust=False, use_mrt=False)),
    ("v3 + block adjustment", dict(use_area=True, block_adjust=True, use_mrt=False)),
    ("v4 + MRT, no block adj", dict(use_area=True, block_adjust=False, use_mrt=True)),
    ("v5 + MRT + block adj", dict(use_area=True, block_adjust=True, use_mrt=True)),
]


def compare(sales, args):
    print("Comparing model versions on the same sales…")
    rows = {}
    for name, opts in VARIANTS:
        df, _ = run(sales, args.lookback, args.min_comps, quiet=True, **opts)
        rows[name] = headline(df)
        print(f"  {name} done")
    t = pd.DataFrame(rows).T
    print("\n=== Model comparison (lower typical error is better) ===")
    print(t.to_string(formatters={
        "typical_error": pct, "within_5": pct, "within_10": pct, "in_range": pct,
        "bias": lambda v: f"{v:+.1%}", "tested": lambda v: f"{int(v)}"}))


def summarise(df, by):
    g = df.groupby(by)
    out = pd.DataFrame({
        "sales": g.size(),
        "typical_error": g["error_pct"].apply(lambda e: e.abs().median()),
        "bias": g["error_pct"].median(),
        "in_range": g["inside_range"].mean(),
    })
    return out


def pct(x):
    return f"{x:.1%}"


def report(df, skipped, args):
    abs_err = df["error_pct"].abs()
    print("\n=== Valuation backtest ===")
    print(f"Tested {len(df)} sales from the last {args.months} months "
          f"(lookback {args.lookback} months, min {args.min_comps} comparable sales)")
    if skipped:
        print(f"Skipped {sum(skipped.values())}: " + "; ".join(f"{k} ({v})" for k, v in skipped.items()))
    print()
    print(f"Typical error (median):    {pct(abs_err.median())}   "
          "← half of estimates are closer than this")
    print(f"Within 5% of real price:   {pct((abs_err <= 0.05).mean())}")
    print(f"Within 10% of real price:  {pct((abs_err <= 0.10).mean())}")
    print(f"Real price inside range:   {pct(df['inside_range'].mean())}   "
          "← about 50% is expected; the range covers the middle half of sales")
    bias = df["error_pct"].median()
    if abs(bias) < 0.01:
        direction = "no clear lean either way"
    else:
        direction = "estimates tend to be " + ("too high" if bias > 0 else "too low")
    print(f"Bias (median error):       {bias:+.1%}   ← {direction}")

    fmt = {"typical_error": pct, "bias": lambda v: f"{v:+.1%}", "in_range": pct}

    print("\n--- By flat type ---")
    print(summarise(df, "flat_type").to_string(formatters=fmt))

    df = df.copy()
    df["floor_band"] = pd.cut(df["storey_mid"], [0, 6, 12, 20, 60],
                              labels=["1-6", "7-12", "13-20", "21+"])
    print("\n--- By floor ---")
    print(summarise(df, "floor_band").to_string(formatters=fmt))

    df["lease_band"] = pd.cut(df["remaining_lease_years"], [0, 60, 70, 80, 99],
                              labels=["<60 yrs", "60-70", "70-80", "80+"])
    print("\n--- By remaining lease ---")
    print(summarise(df, "lease_band").to_string(formatters=fmt))

    towns = summarise(df, "town")
    towns = towns[towns["sales"] >= 5].sort_values("typical_error")
    if len(towns) > 10:
        print("\n--- Most accurate towns (5+ sales tested) ---")
        print(towns.head(5).to_string(formatters=fmt))
        print("\n--- Least accurate towns ---")
        print(towns.tail(5).to_string(formatters=fmt))
    elif len(towns):
        print("\n--- By town (5+ sales tested) ---")
        print(towns.to_string(formatters=fmt))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n", type=int, default=200, help="how many sales to test (default 200)")
    p.add_argument("--months", type=int, default=3, help="test sales from the last N months (default 3)")
    p.add_argument("--seed", type=int, default=42, help="random seed, so runs are repeatable")
    p.add_argument("--lookback", type=int, default=LOOKBACK_MONTHS, help="months of comparable sales to use")
    p.add_argument("--min-comps", type=int, default=MIN_COMPS, help="minimum comparable sales needed")
    p.add_argument("--no-area", action="store_true", help="leave floor area out of the formula")
    p.add_argument("--no-block", action="store_true", help="turn off the block adjustment")
    p.add_argument("--no-mrt", action="store_true", help="leave MRT distance out of the formula")
    p.add_argument("--compare", action="store_true",
                   help="compare all model versions (v1 to v5) on the same sales")
    args = p.parse_args()

    start = time.time()
    sales = load_test_sales(args.n, args.months, args.seed)
    if args.compare:
        compare(sales, args)
        print(f"\n({time.time() - start:.0f}s)")
        return
    print(f"Backtesting {len(sales)} sales…")
    df, skipped = run(sales, args.lookback, args.min_comps,
                      use_area=not args.no_area, block_adjust=not args.no_block,
                      use_mrt=not args.no_mrt)
    if df.empty:
        print("No sales could be valued. Check the data has been built (dbt build).")
        return
    report(df, skipped, args)
    df.to_csv(OUT, index=False)
    print(f"\nDetails for every sale saved to {OUT} ({time.time() - start:.0f}s)")


if __name__ == "__main__":
    main()