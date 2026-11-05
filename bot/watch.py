"""/watch alerts: tell a chat when new resale sales appear for a block it follows.

Watches are saved in bot/watches.json. After each daily data refresh, the bot calls
check_new(), which compares each watched block's sales with the ones already seen
and returns the messages to send.
"""
import json, os, re, threading
from collections import Counter
import duckdb

from valuation import locate, ValuationError, DB

WATCH_FILE = os.environ.get("WATCH_FILE", "bot/watches.json")
MAX_WATCHES = 10
_lock = threading.Lock()

FLAT_TYPES = [
    (r"\b(?:1|one)[\s-]?(?:room|rm)\b", "1 ROOM"), (r"\b(?:2|two)[\s-]?(?:room|rm)\b", "2 ROOM"),
    (r"\b(?:3|three)[\s-]?(?:room|rm)\b", "3 ROOM"), (r"\b(?:4|four)[\s-]?(?:room|rm)\b", "4 ROOM"),
    (r"\b(?:5|five)[\s-]?(?:room|rm)\b", "5 ROOM"), (r"\b(?:executive|exec)\b", "EXECUTIVE"),
    (r"\bmulti[\s-]?gen(?:eration)?\b", "MULTI-GENERATION"),
]

USAGE = ("Usage: /watch <block> <street> <flat type>\n"
         "Example: /watch 540 Ang Mo Kio Ave 10 3 room\n"
         "The street is only needed if the block number exists on more than one street.")


def _load():
    try:
        with open(WATCH_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data):
    os.makedirs(os.path.dirname(WATCH_FILE) or ".", exist_ok=True)
    tmp = WATCH_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, WATCH_FILE)


def parse(text):
    """'540 Ang Mo Kio Ave 10 3 room' -> ('540', 'ANG MO KIO AVE 10', '3 ROOM')"""
    t = " " + text.lower() + " "
    flat_type = None
    for pattern, name in FLAT_TYPES:
        m = re.search(pattern, t)
        if m:
            flat_type = name
            t = t[:m.start()] + " " + t[m.end():]
            break
    t = re.sub(r"\b(?:blk|block)\b", " ", t)
    m = re.search(r"\b(\d{1,4}[a-z]?)\b", t)
    if not m or not flat_type:
        return None
    block = m.group(1).upper()
    street = " ".join((t[:m.start()] + " " + t[m.end():]).split()).upper() or None
    return block, street, flat_type


def _sales(block, street, flat_type):
    con = duckdb.connect(DB, read_only=True)
    try:
        return con.execute(
            """SELECT strftime(txn_month, '%Y-%m'), storey_range, floor_area_sqm, resale_price
               FROM fct_resale
               WHERE block = ? AND street_name = ? AND flat_type = ?
               ORDER BY txn_month DESC""", [block, street, flat_type]).fetchall()
    finally:
        con.close()


def _sig(row):
    month, storey, area, price = row
    return f"{month}|{storey}|{float(area):g}|{float(price):.0f}"


def add(chat_id, text):
    parsed = parse(text or "")
    if not parsed:
        return USAGE
    block, street, flat_type = parsed
    try:
        street, town, _ = locate(block, street)
    except ValuationError as e:
        return str(e)
    rows = _sales(block, street, flat_type)
    with _lock:
        data = _load()
        mine = data.setdefault(str(chat_id), [])
        if any(w["block"] == block and w["street"] == street and w["flat_type"] == flat_type for w in mine):
            return f"You're already watching {flat_type.lower()} sales at Blk {block} {street.title()}."
        if len(mine) >= MAX_WATCHES:
            return f"You can watch up to {MAX_WATCHES} blocks. Remove one with /unwatch first."
        mine.append({"block": block, "street": street, "town": town, "flat_type": flat_type,
                     "seen": [_sig(r) for r in rows]})
        _save(data)
    last = f" The last one was {rows[0][0]} at S${float(rows[0][3]):,.0f}." if rows else ""
    return (f"👀 Watching {flat_type.lower()} sales at Blk {block} {street.title()}, {town.title()}. "
            f"I'll message you when new ones appear in HDB's data (usually updated monthly).{last}")


def listing(chat_id):
    mine = _load().get(str(chat_id), [])
    if not mine:
        return "You're not watching any blocks. Try: /watch 540 Ang Mo Kio Ave 10 3 room"
    lines = ["You're watching:"]
    for n, w in enumerate(mine, 1):
        lines.append(f"{n}. Blk {w['block']} {w['street'].title()} · {w['flat_type'].lower()}")
    lines.append("\nRemove one with /unwatch <number>, e.g. /unwatch 1")
    return "\n".join(lines)


def remove(chat_id, arg):
    with _lock:
        data = _load()
        mine = data.get(str(chat_id), [])
        if not arg or not arg.strip().isdigit() or not (1 <= int(arg) <= len(mine)):
            return "Send /watching to see the list, then /unwatch <number>, e.g. /unwatch 1"
        w = mine.pop(int(arg) - 1)
        _save(data)
    return f"Stopped watching Blk {w['block']} {w['street'].title()} · {w['flat_type'].lower()}."


def check_new():
    """Return [(chat_id, message)] for watched blocks with sales not seen before."""
    out = []
    with _lock:
        data = _load()
        changed = False
        for chat_id, mine in data.items():
            for w in mine:
                rows = _sales(w["block"], w["street"], w["flat_type"])
                current = Counter(_sig(r) for r in rows)
                new = current - Counter(w["seen"])
                if not new:
                    continue
                new_rows = []
                for r in rows:                      # keep only the unseen copies
                    if new[_sig(r)] > 0:
                        new[_sig(r)] -= 1
                        new_rows.append(r)
                lines = [f"🏠 New {w['flat_type'].lower()} sale{'s' if len(new_rows) > 1 else ''} "
                         f"at Blk {w['block']} {w['street'].title()}:"]
                for month, storey, area, price in new_rows[:10]:
                    lines.append(f"• {month} · {storey} · {float(area):.0f} sqm · S${float(price):,.0f}")
                out.append((int(chat_id), "\n".join(lines)))
                w["seen"] = [_sig(r) for r in rows]
                changed = True
        if changed:
            _save(data)
    return out