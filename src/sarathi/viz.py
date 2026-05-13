from __future__ import annotations

import io
from pathlib import Path

from .scanner import ResultFile

_SKIP_VIZ_TYPES = {"image", "svg", "code"}
_BG = "#0d0d1a"
_FG = "#e0e0e0"
_ACCENT = "#4fc3f7"
_ACCENT2 = "#f48fb1"
_W, _H = 12, 6.75  # 16:9 at 100 DPI → 1200×675 px
_DPI = 100

_TIME_KEYWORDS = {"year", "month", "date", "timestamp", "time", "day", "week",
                  "quarter", "period", "dt", "datetime"}
_PART_KEYWORDS = {"share", "pct", "percent", "proportion", "ratio", "weight",
                  "fraction"}


def process(files: list[ResultFile], project_dir: Path) -> list[ResultFile]:
    """Pre-render CSV files to chart PNGs; return new ResultFiles (type=image)."""
    viz_dir = project_dir / ".sarathi" / "viz"
    viz_dir.mkdir(parents=True, exist_ok=True)

    rendered: list[ResultFile] = []
    for rf in files:
        if rf.type != "data":
            continue
        if not rf.filename.lower().endswith(".csv"):
            continue
        try:
            result = _render_csv(rf, viz_dir)
            if result:
                rendered.append(result)
        except Exception:
            pass
    return rendered


def _render_csv(rf: ResultFile, viz_dir: Path) -> ResultFile | None:
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = pd.read_csv(io.StringIO(rf.content))
    if df.empty or len(df.columns) < 1:
        return None

    chart_type, x_col, y_cols = detect_chart_type(df)

    fig, ax = plt.subplots(figsize=(_W, _H), dpi=_DPI)
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_BG)
    _style_axes(ax)

    colors = [_ACCENT, _ACCENT2, "#a5d6a7", "#ffcc80", "#ce93d8"]

    if chart_type == "line":
        for i, yc in enumerate(y_cols):
            ax.plot(df[x_col], df[yc], color=colors[i % len(colors)],
                    linewidth=2.5, label=yc, marker="o", markersize=4)
        ax.set_xlabel(x_col, color=_FG)
        if len(y_cols) > 1:
            ax.legend(facecolor=_BG, labelcolor=_FG, edgecolor="#444")
        plt.xticks(rotation=30, ha="right")

    elif chart_type == "scatter":
        ax.scatter(df[x_col], df[y_cols[0]], color=_ACCENT, alpha=0.7, s=40)
        ax.set_xlabel(x_col, color=_FG)
        ax.set_ylabel(y_cols[0], color=_FG)

    elif chart_type == "heatmap":
        import seaborn as sns
        numeric = df.select_dtypes("number")
        corr = numeric.corr()
        sns.heatmap(corr, ax=ax, cmap="coolwarm", annot=True, fmt=".2f",
                    linewidths=0.5, cbar_kws={"shrink": 0.8})
        ax.set_title("Correlation Matrix", color=_FG, pad=12)

    elif chart_type == "hbar":
        bars = ax.barh(df[x_col].astype(str), df[y_cols[0]],
                       color=_ACCENT, height=0.6)
        ax.set_xlabel(y_cols[0], color=_FG)
        ax.bar_label(bars, fmt="%.1f", padding=4, color=_FG, fontsize=9)

    elif chart_type == "stacked_bar":
        bottom = None
        for i, yc in enumerate(y_cols):
            ax.bar(df[x_col].astype(str), df[yc], bottom=bottom,
                   color=colors[i % len(colors)], label=yc)
            bottom = df[yc] if bottom is None else bottom + df[yc]
        ax.legend(facecolor=_BG, labelcolor=_FG, edgecolor="#444")
        plt.xticks(rotation=30, ha="right")

    elif chart_type == "boxplot":
        numeric_cols = df.select_dtypes("number").columns.tolist()
        data = [df[c].dropna().values for c in numeric_cols]
        bp = ax.boxplot(data, patch_artist=True, labels=numeric_cols)
        for patch in bp["boxes"]:
            patch.set_facecolor(_ACCENT)
            patch.set_alpha(0.7)
        for element in ("whiskers", "caps", "medians", "fliers"):
            plt.setp(bp[element], color=_FG)

    else:  # bar fallback
        ax.bar(df[x_col].astype(str), df[y_cols[0]], color=_ACCENT, width=0.6)
        ax.set_xlabel(x_col, color=_FG)
        ax.set_ylabel(y_cols[0], color=_FG)
        plt.xticks(rotation=30, ha="right")

    ax.set_title(rf.filename.replace(".csv", "").replace("_", " ").title(),
                 color=_FG, fontsize=14, pad=12)

    plt.tight_layout()
    out_path = viz_dir / (Path(rf.filename).stem + ".png")
    fig.savefig(out_path, dpi=_DPI, bbox_inches="tight", facecolor=_BG)
    plt.close(fig)

    import base64
    b64 = base64.b64encode(out_path.read_bytes()).decode()
    return ResultFile(
        path=str(out_path),
        filename=out_path.name,
        type="image",
        content=f"data:image/png;base64,{b64}",
    )


def detect_chart_type(df) -> tuple[str, str, list[str]]:
    """Returns (chart_type, x_col, y_cols)."""
    import pandas as pd

    cols = list(df.columns)
    numeric_cols = df.select_dtypes("number").columns.tolist()
    nrows = len(df)

    # 1. Time series detection
    for col in cols:
        col_lower = col.lower()
        if df[col].dtype == "datetime64[ns]" or any(k in col_lower for k in _TIME_KEYWORDS):
            y = [c for c in numeric_cols if c != col]
            if y:
                try:
                    df[col] = pd.to_datetime(df[col], errors="coerce")
                    df = df.sort_values(col)
                except Exception:
                    pass
                return "line", col, y[:4]

    # 2. Scatter: exactly 2 numeric columns, both high cardinality
    if len(numeric_cols) == 2:
        u0 = df[numeric_cols[0]].nunique() / max(nrows, 1)
        u1 = df[numeric_cols[1]].nunique() / max(nrows, 1)
        if u0 > 0.20 and u1 > 0.20:
            return "scatter", numeric_cols[0], [numeric_cols[1]]

    # 3. Heatmap: 3+ numeric columns
    if len(numeric_cols) >= 3:
        return "heatmap", cols[0], numeric_cols

    # 4. Part-to-whole (stacked bar)
    str_cols = df.select_dtypes(["object", "category"]).columns.tolist()
    if str_cols and len(numeric_cols) >= 2:
        col_names_lower = [c.lower() for c in numeric_cols]
        if any(k in n for k in _PART_KEYWORDS for n in col_names_lower):
            return "stacked_bar", str_cols[0], numeric_cols[:5]

    # 5. Horizontal bar: one categorical + one numeric, low cardinality
    if str_cols and numeric_cols:
        x = str_cols[0]
        uniqueness = df[x].nunique() / max(nrows, 1)
        if uniqueness < 0.15 or df[x].nunique() <= 20:
            return "hbar", x, [numeric_cols[0]]

    # 6. Distribution: single numeric, broad spread
    if len(numeric_cols) == 1:
        if nrows > 500:
            return "boxplot", numeric_cols[0], [numeric_cols[0]]
        return "boxplot", numeric_cols[0], [numeric_cols[0]]

    # 7. Fallback
    x = cols[0]
    y = numeric_cols if numeric_cols else ([cols[1]] if len(cols) > 1 else [cols[0]])
    return "bar", x, y[:1]


def _style_axes(ax) -> None:
    ax.tick_params(colors=_FG, which="both")
    ax.yaxis.label.set_color(_FG)
    ax.xaxis.label.set_color(_FG)
    for spine in ax.spines.values():
        spine.set_edgecolor("#333355")
    ax.grid(axis="y", color="#333355", linewidth=0.5, linestyle="--")
    ax.set_axisbelow(True)
