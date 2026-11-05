import pandas as pd

df = pd.read_csv("evals/valuation_backtest.csv")
g = df.groupby("town")
table = pd.DataFrame({
    "sales": g.size(),
    "typical_error": g["error_pct"].apply(lambda e: e.abs().median()),
    "bias": g["error_pct"].median(),
    "in_range": g["inside_range"].mean(),
}).sort_values("typical_error")

print(table.to_string(formatters={
    "typical_error": "{:.1%}".format,
    "bias": "{:+.1%}".format,
    "in_range": "{:.1%}".format,
}))