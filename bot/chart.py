"""Turn a query result into a clean, minimal chart image when the result suits one."""
import io
import matplotlib
matplotlib.use("Agg")  # draw to an image file; no screen needed (works on servers too)
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter, MaxNLocator
import pandas as pd

TIME_NAMES = {"txn_month", "month", "txn_year", "year", "yr", "txn_quarter", "quarter"}
COUNT_NAMES = {"txns", "count", "n", "transactions", "num_transactions", "count_star()"}

# Look and feel
INK = "#1f2933"        # main text
MUTED = "#8a94a0"      # axis labels, secondary text
FAINT = "#e6e9ed"      # gridlines
ACCENT = "#2563eb"     # highlight colour
BAR = "#c7d2fe"        # other bars
SERIES = ["#2563eb", "#f97316", "#10b981", "#a855f7", "#ef4444", "#0ea5e9", "#eab308", "#64748b"]

FRIENDLY = {
    "median_psm": "Median price per sqm",
    "med_psm": "Median price per sqm",
    "price_psm": "Price per sqm",
    "median_price": "Median resale price",
    "resale_price": "Resale price",
    "avg_price": "Average resale price",
    "yoy": "Year-over-year change",
    "yoy_change": "Year-over-year change",
    "txns": "Transactions",
    "txn_year": "Year",
    "txn_month": "Month",
    "txn_quarter": "Quarter",
}

plt.rcParams.update({
    "font.size": 10,
    "text.color": INK,
    "axes.labelcolor": MUTED,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.edgecolor": FAINT,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})


def _is_numeric(s):
    return pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)


def _is_text(s):
    return not _is_numeric(s) and not pd.api.types.is_datetime64_any_dtype(s)


def _friendly(col):
    return FRIENDLY.get(col.lower(), col.replace("_", " ").capitalize())


def _is_money(col):
    c = col.lower()
    return "price" in c or "psm" in c


def _is_ratio(col, values):
    return ("yoy" in col.lower() or "share" in col.lower() or "pct" in col.lower()) \
        and values.abs().max() <= 1.5


def _pick_columns(df):
    """Return (x, y, series) column names, or None if the result isn't chartable."""
    cols = list(df.columns)
    time_col = next((c for c in cols if c.lower() in TIME_NAMES
                     or pd.api.types.is_datetime64_any_dtype(df[c])), None)
    text_cols = [c for c in cols if _is_text(df[c]) and c != time_col]
    measures = [c for c in cols if _is_numeric(df[c]) and c != time_col
                and c.lower() not in COUNT_NAMES]
    if not measures:  # fall back to a count column if that's all there is
        measures = [c for c in cols if _is_numeric(df[c]) and c != time_col]
    if not measures:
        return None
    y = measures[0]

    if time_col:
        series = next((c for c in text_cols if df[c].nunique() <= 8), None)
        return time_col, y, series
    if text_cols and df[text_cols[0]].is_unique and len(df) <= 30:
        return text_cols[0], y, None
    return None


def _formatters(col, values):
    """Return (full, compact) number formatters for this measure."""
    money = _is_money(col)
    prefix = "S$" if money else ""
    if _is_ratio(col, values):
        full = lambda v: f"{v:+.1%}"
        return full, (lambda v, _p=None: f"{v:.0%}")

    def full(v):
        return f"{prefix}{v:,.0f}" if abs(v) >= 100 or v == 0 else f"{prefix}{v:,.2f}"

    def compact(v, _p=None):
        if abs(v) >= 1e6:
            return f"{prefix}{v/1e6:.1f}M"
        if abs(v) >= 1e3:
            return f"{prefix}{v/1e3:.0f}k"
        return f"{prefix}{v:,.0f}"
    return full, compact


def _label(name):
    """'KALLANG/WHAMPOA' → 'Kallang/Whampoa' for nicer labels."""
    s = str(name)
    return s.title() if s.isupper() else s


def _titles(fig, title, subtitle):
    h = fig.get_figheight()  # place text in fixed inches so short charts don't crowd
    fig.text(0.04, 1 - 0.22 / h, title[:80], fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.04, 1 - 0.55 / h, subtitle, fontsize=10, color=MUTED, va="top")
    fig.text(0.04, 0.12 / h, "Source: HDB resale data, data.gov.sg", fontsize=8, color=MUTED)


def _bars(df, x, y):
    d = df.sort_values(y)
    full, _ = _formatters(y, d[y])
    fig, ax = plt.subplots(figsize=(8, max(3.2, 0.45 * len(d) + 1.8)), dpi=170)
    colours = [BAR] * (len(d) - 1) + [ACCENT]  # highlight the top value
    ax.barh([_label(v) for v in d[x]], d[y], color=colours, height=0.65)

    span = d[y].abs().max()
    for i, v in enumerate(d[y]):
        ax.text(v + span * 0.015, i, full(v), va="center", fontsize=9,
                color=INK if i == len(d) - 1 else MUTED)

    ax.set_xlim(0, span * 1.15)
    ax.xaxis.set_visible(False)
    for side in ["top", "right", "bottom", "left"]:
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="y", length=0, labelcolor=INK)
    return fig, ax


def _lines(df, x, y, series):
    d = df.sort_values(x)
    full, compact = _formatters(y, d[y])
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=170)

    groups = list(d.groupby(series)) if series else [(None, d)]
    for i, (name, g) in enumerate(groups):
        colour = SERIES[i % len(SERIES)] if series else ACCENT
        ax.plot(g[x], g[y], color=colour, linewidth=2.2, solid_capstyle="round")
        last_x, last_y = g[x].iloc[-1], g[y].iloc[-1]
        ax.scatter([last_x], [last_y], color=colour, s=22, zorder=3)
        text = f"{_label(name)}  {full(last_y)}" if series else full(last_y)
        ax.annotate(text, (last_x, last_y), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=9, color=colour, fontweight="bold")

    ax.yaxis.set_major_formatter(FuncFormatter(compact))
    ax.yaxis.set_major_locator(MaxNLocator(5))
    if pd.api.types.is_datetime64_any_dtype(d[x]):
        loc = mdates.AutoDateLocator(maxticks=6)
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
    elif _is_numeric(d[x]):
        ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))

    ax.grid(axis="y", color=FAINT, linewidth=1)
    ax.set_axisbelow(True)
    for side in ["top", "right", "left"]:
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)
    ax.margins(x=0.12 if series else 0.08, y=0.08)
    return fig, ax


def make_chart(df, title=""):
    """Return a PNG as bytes, or None when a chart wouldn't help."""
    if df is None or len(df) < 2 or len(df) > 200:
        return None
    picked = _pick_columns(df)
    if not picked:
        return None
    x, y, series = picked
    df = df.dropna(subset=[x, y])
    if len(df) < 2:
        return None

    if _is_text(df[x]):
        fig, _ = _bars(df, x, y)
        subtitle = _friendly(y)
    else:
        fig, _ = _lines(df, x, y, series)
        subtitle = f"{_friendly(y)} by {_friendly(x).lower()}"

    h = fig.get_figheight()
    bars = _is_text(df[x])
    fig.subplots_adjust(top=1 - 1.0 / h, bottom=(0.45 if bars else 0.75) / h,
                        left=0.22 if bars else 0.10, right=0.86)
    _titles(fig, title, subtitle)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()