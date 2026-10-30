import re, sys, threading, pathlib
import duckdb, anthropic
from dotenv import load_dotenv

load_dotenv()
MODEL = "claude-sonnet-5-5"
DB = "hdb.duckdb"
SCHEMA = pathlib.Path("semantic/schema.md").read_text()
client = anthropic.Anthropic()

SQL_PROMPT = f"""You write DuckDB SQL for questions about Singapore HDB resale transactions.
Use only the table and columns described below. Return one SELECT query in a ```sql block and nothing else.
If the question is ambiguous, pick the most reasonable reading and state it in a SQL comment on the first line.

{SCHEMA}"""

SUMMARY_PROMPT = ("Answer the question in 2-4 plain sentences using only the query result. "
                  "Show money as S$ with thousands separators. Never add facts that are not in the result.")

def ask_llm(system, user, max_tokens=4000):
    resp = client.messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                  messages=[{"role": "user", "content": user}])
    # Keep only text blocks; the model may also return a thinking block first
    return "".join(b.text for b in resp.content if b.type == "text")

def extract_sql(text):
    m = re.search(r"```sql\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip().rstrip(";")

def validate(sql):
    body = re.sub(r"--.*", "", sql).strip().lower()
    if not body.startswith(("select", "with")):
        raise ValueError("Only SELECT queries are allowed")
    if ";" in body:
        raise ValueError("Only one statement is allowed")

def run(sql, timeout_s=10):
    con = duckdb.connect(DB, read_only=True, config={"enable_external_access": False})
    timer = threading.Timer(timeout_s, con.interrupt)
    timer.start()
    try:
        return con.execute(f"SELECT * FROM (\n{sql}\n) LIMIT 200").df()
    finally:
        timer.cancel()
        con.close()

def data_as_of():
    return run("SELECT strftime(MAX(txn_month), '%b %Y') AS m FROM fct_resale").iloc[0, 0]

def answer(question):
    sql = extract_sql(ask_llm(SQL_PROMPT, question))
    df = None
    for attempt in range(2):
        try:
            validate(sql)
            df = run(sql)
            break
        except Exception as e:
            if attempt == 1:
                return f"Sorry, I couldn't answer that ({e}).", sql, None
            fix = f"{question}\n\nYour previous SQL:\n{sql}\n\nfailed with: {e}\nReturn a corrected query."
            sql = extract_sql(ask_llm(SQL_PROMPT, fix))
    result = df.head(30).to_string(index=False)
    text = ask_llm(SUMMARY_PROMPT, f"Question: {question}\n\nSQL:\n{sql}\n\nResult:\n{result}", 400)
    return f"{text}\n\nData: registrations up to {data_as_of()}.", sql, df

if __name__ == "__main__":
    text, sql, _ = answer(" ".join(sys.argv[1:]))
    print(sql, "\n")
    print(text)