import sys, yaml, pandas as pd
sys.path.insert(0, "agent")
from sql_agent import ask_llm, extract_sql, validate, run, SQL_PROMPT

THRESHOLD = 0.8

def signatures(df):
    sigs = []
    for c in df.columns:
        s = df[c].round(2) if pd.api.types.is_numeric_dtype(df[c]) else df[c]
        sigs.append(sorted(s.astype(str)))
    return sigs

def matches(agent_df, gold_df):
    if len(agent_df) != len(gold_df):
        return False
    agent_sigs = signatures(agent_df)
    return all(sig in agent_sigs for sig in signatures(gold_df))

cases = yaml.safe_load(open("evals/cases.yaml"))
rows = []
for c in cases:
    try:
        sql = extract_sql(ask_llm(SQL_PROMPT, c["question"]))
        validate(sql)
        ok = matches(run(sql), run(c["gold_sql"]))
    except Exception as e:
        sql, ok = f"ERROR: {e}", False
    rows.append({"id": c["id"], "difficulty": c["difficulty"], "pass": ok, "sql": sql})

report = pd.DataFrame(rows)
print(report.groupby("difficulty")["pass"].mean().round(2))
print("Failures:", report.loc[~report["pass"], "id"].tolist())
score = report["pass"].mean()
print(f"Overall: {score:.0%}")
report.to_csv("evals/last_run.csv", index=False)
sys.exit(0 if score >= THRESHOLD else 1)