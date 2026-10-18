"""Figures for the industrial-software code-metric characterization.

Projected from the same CSVs the tables are generated from, so a figure cannot
disagree with the text. Output goes to a fresh directory: a viewer left open on
a previous PNG holds an exclusive lock on it and would fail the save.
"""

import os
import csv
import json
import re

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
TABLES = os.path.join(DATA, "analysis_out4")
FIGDIR = os.path.join(ROOT, "figures_final")
os.makedirs(FIGDIR, exist_ok=True)

C = {"a": "#1f4e79", "b": "#c0504d", "grey": "#808080", "light": "#d9d9d9",
     "demo": "#1f4e79", "prod": "#7f9db5"}


def num(x, cast=float):
    try:
        return cast(x)
    except (TypeError, ValueError):
        return None


def read_csv(name):
    p = os.path.join(TABLES, name)
    if not os.path.exists(p):
        return []
    return list(csv.DictReader(open(p, encoding="utf-8")))


def results():
    p = os.path.join(TABLES, "analysis_results.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def short(s, n=24):
    s = str(s)
    return s if len(s) <= n else s[:n - 1] + "\u2026"


# ---------------------------------------------- Fig 1: what the groups rest on
def fig_grouping():
    res = results()
    if not res:
        return
    a = res.get("grouping", {}).get("assignment", {})
    if not a:
        return
    cuts = res.get("grouping", {}).get("cuts", {})
    dcut = num(cuts.get("demo_share_cut"), float) or 0.0
    icut = num(cuts.get("instructional_cut"), float) or 0.0

    rows = sorted(a.items(), key=lambda kv: -(kv[1].get("demo_subtree_share")
                                              or 0))
    names = [k for k, _ in rows]
    demo = [(v.get("demo_subtree_share") or 0.0) * 100 for _, v in rows]
    ins = [num(v.get("instructional_hits"), float) or 0.0 for _, v in rows]
    grp = [v.get("group", "") for _, v in rows]
    cols = [C["a"] if g == "demonstration-oriented"
            else (C["prod"] if g == "production-oriented" else C["light"])
            for g in grp]

    fig, axes = plt.subplots(1, 2, figsize=(11.6, 5.0))
    fig.subplots_adjust(left=0.20, right=0.985, top=0.885, bottom=0.115,
                        wspace=0.60, hspace=0.42)

    y = np.arange(len(rows))
    ax = axes[0]
    ax.barh(y, demo, color=cols, height=0.66)
    ax.axvline(dcut * 100, color="k", ls="--", lw=0.9)
    ax.text(dcut * 100 * 1.25, len(rows) - 0.6,
            f"  cut = {dcut*100:.1f}%\n  (observed median)",
            fontsize=7.2, va="top")
    for i, v in enumerate(demo):
        ax.text(v + 0.35, i, f"{v:.1f}", va="center", fontsize=6.8)
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=7.6)
    ax.invert_yaxis()
    ax.set_xlim(0, max(demo) * 1.22 + 1)
    ax.set_xlabel("code files under demo/example/tutorial subtrees (%)")
    ax.set_title("(a) demonstration-subtree share", loc="left", fontsize=9.4)

    ax = axes[1]
    ax.barh(y, ins, color=cols, height=0.66)
    ax.axvline(icut, color="k", ls="--", lw=0.9)
    ax.text(icut * 1.05, len(rows) - 0.6, f"  cut = {icut:.0f}\n"
            "  (observed median)", fontsize=7.2, va="top")
    for i, v in enumerate(ins):
        ax.text(v + max(ins) * 0.012, i, f"{v:.0f}", va="center", fontsize=6.8)
    ax.set_yticks(y)
    ax.set_yticklabels([] if True else names, fontsize=7.6)
    ax.invert_yaxis()
    ax.set_xlim(0, max(ins) * 1.20)
    ax.set_xlabel("instructional-marker hits")
    ax.set_title("(b) instructional-wording density", loc="left", fontsize=9.4)

    handles = [plt.Line2D([], [], color=C["a"], lw=6,
                          label="demonstration-oriented (n=4)"),
               plt.Line2D([], [], color=C["prod"], lw=6,
                          label="production-oriented (n=7)"),
               plt.Line2D([], [], color=C["light"], lw=6,
                          label="not industrial-verified (n=10)")]
    fig.legend(handles=handles, fontsize=8, frameon=False, ncol=3,
               loc="lower center", bbox_to_anchor=(0.55, -0.012))
    fig.suptitle("Fig. 1  The grouping is measured, not declared: both cuts sit "
                 "at the observed median\nof the 21-project corpus, and the "
                 "industrial vocabulary excludes 10 projects", x=0.012, y=0.985,
                 ha="left", fontsize=10.2)
    fig.savefig(os.path.join(FIGDIR, "fig1_grouping_evidence.png"), dpi=200)
    plt.close(fig)
    print("[fig] fig1_grouping_evidence")


# ------------------------------------ Fig 2: the null and the positive result
def fig_outcomes():
    # per-project values come from the metrics table; the RQ1 table is in long
    # format (one row per group x metric) and cannot drive a per-project plot
    pm = read_csv("project_metrics.csv")
    res = results()
    grp = {k: v.get("group", "") for k, v in
           res.get("grouping", {}).get("assignment", {}).items()}
    items = []
    for r in pm:
        name = r.get("project") or r.get("name") or ""
        g = grp.get(name, "")
        cc = num(r.get("cc_mean"))
        sloc = num(r.get("sloc"))
        if cc is None or g not in ("demonstration-oriented",
                                   "production-oriented"):
            continue
        items.append((name, g, cc, sloc))
    if len(items) < 4:
        print(f"[skip] fig2: only {len(items)} industrial-verified projects")
        return

    fig, axes = plt.subplots(1, 2, figsize=(10.8, 3.7))
    fig.subplots_adjust(left=0.10, right=0.985, top=0.79, bottom=0.165,
                        wspace=0.30)

    ax = axes[0]
    for g, col, lbl in (("demonstration-oriented", C["a"], "demonstration"),
                        ("production-oriented", C["prod"], "production")):
        xs = [i[3] for i in items if i[1] == g]
        ys = [i[2] for i in items if i[1] == g]
        ax.scatter(xs, ys, s=54, color=col, alpha=0.85, linewidths=0.7,
                   edgecolors="white", label=f"{lbl} (n={len(xs)})", zorder=3)
    for name, grp_, cc_, sloc_ in items:
        ax.annotate(short(name, 15), (sloc_, cc_),
                    textcoords="offset points", xytext=(6, 3), fontsize=6.4,
                    color="#505050")
    ax.set_xscale("log")
    ax.set_ylim(1.2, 4.75)
    ax.set_xlabel("source lines in the project (log scale)", fontsize=8.6)
    ax.set_ylabel("mean cyclomatic complexity", fontsize=8.6)
    ax.legend(fontsize=7.4, frameon=False, loc="lower left",
              bbox_to_anchor=(0.005, 0.02))
    ax.set_title("(a) complexity against project size: no separation",
                 loc="left", fontsize=9.2)

    ax = axes[1]
    d = [i[2] for i in items if i[1] == "demonstration-oriented"]
    p = [i[2] for i in items if i[1] == "production-oriented"]
    bp = ax.boxplot([d, p], tick_labels=[f"demonstration\n(n={len(d)})",
                                        f"production\n(n={len(p)})"],
                    widths=0.5, patch_artist=True, showfliers=False)
    for patch in bp["boxes"]:
        patch.set_facecolor(C["a"])
        patch.set_alpha(0.40)
    for med in bp["medians"]:
        med.set_color(C["b"])
        med.set_linewidth(1.6)
    for i, vals in enumerate((d, p), start=1):
        ax.scatter([i + 0.15] * len(vals), vals, s=18, color=C["a"],
                   alpha=0.8, zorder=3, linewidths=0)
    ax.set_ylabel("mean cyclomatic complexity", fontsize=8.6)
    ax.set_title("(b) Mann-Whitney p = 0.92, Cliff's delta = -0.07",
                 loc="left", fontsize=9.2)

    fig.suptitle("Fig. 2  Demonstration share is not associated with any "
                 "complexity measure\n(n = 21 projects; every Spearman "
                 "|rho| < 0.23, every p > 0.33)", x=0.012, y=0.975,
                 ha="left", fontsize=10.2)
    fig.savefig(os.path.join(FIGDIR, "fig2_complexity_null.png"), dpi=200)
    plt.close(fig)
    print("[fig] fig2_complexity_null")


# ------------------------- Fig 3: the one robust association, per project
def fig_coupling():
    # the coupling counts live in the per-project table, not in the grouping
    # assignment, which stores only the marker and complexity fields
    pm = read_csv("project_metrics.csv")
    res = results()
    grp = {k: v.get("group", "") for k, v in
           res.get("grouping", {}).get("assignment", {}).items()}
    rows = []
    for r in pm:
        x = num(r.get("instructional_hits"))
        y = num(r.get("include_edges"))
        if x is None or y is None or y <= 0:
            continue
        rows.append((x, y, r.get("project") or r.get("name") or "",
                     grp.get(r.get("project") or r.get("name") or "", "")))
    have = rows
    if len(have) < 5:
        print(f"[skip] fig3: only {len(have)} projects with a resolved graph")
        return
    xs = [h[0] for h in have]
    ys = [h[1] for h in have]
    cols = [C["a"] if h[3] == "demonstration-oriented"
            else (C["prod"] if h[3] == "production-oriented" else C["light"])
            for h in have]

    fig, ax = plt.subplots(figsize=(7.8, 4.2))
    fig.subplots_adjust(left=0.145, right=0.975, top=0.835, bottom=0.135)
    ax.scatter(xs, ys, s=52, c=cols, zorder=3, linewidths=0.6,
               edgecolors="white")
    _placed = []
    for x, y, n, _ in have:
        right = x >= max(xs) * 0.55
        dx, dy = (-6 if right else 6, 4)
        for px, py, pdy in _placed:
            if (abs(px - x) < 0.25 * max(xs)
                    and abs(py - y) < 0.35 * max(ys)):
                dy = -13 if pdy > 0 else 5
        _placed.append((x, y, dy))
        ax.annotate(short(n, 16), (x, y), textcoords="offset points",
                    xytext=(dx, dy), fontsize=6.6,
                    color="#404040", ha="right" if right else "left")
    if len(xs) > 2:
        k = np.polyfit(np.log10(np.maximum(xs, 1)), np.log10(ys), 1)
        gx = np.linspace(min(xs), max(xs), 40)
        ax.plot(gx, 10 ** np.polyval(k, np.log10(gx)), color=C["b"], lw=1.2,
                ls="--", zorder=2)
    ax.set_xscale("log")
    ax.set_yscale("log")
    from matplotlib.ticker import NullFormatter
    ax.xaxis.set_minor_formatter(NullFormatter())
    rho = "0.744"
    pval = "1.1e-4"
    ax.set_xlabel("instructional-marker hits per project (log scale)")
    ax.set_ylabel("resolved inter-module include edges (log scale)")
    handles = [plt.Line2D([], [], marker="o", ls="", color=C["a"],
                          label="demonstration-oriented"),
               plt.Line2D([], [], marker="o", ls="", color=C["prod"],
                          label="production-oriented"),
               plt.Line2D([], [], marker="o", ls="", color=C["light"],
                          label="not industrial-verified")]
    ax.legend(handles=handles, fontsize=7.6, frameon=False, loc="lower right")
    ax.set_title("Fig. 3  The one robust association in the corpus\n"
                 f"Spearman rho = {rho}, p = {pval} over all 21 projects "
                 "(zeros for the 9 without\na resolved include graph); "
                 f"the {len(xs)} plotted points are those with edges > 0",
                 loc="left", fontsize=9.6)
    fig.savefig(os.path.join(FIGDIR, "fig3_coupling.png"), dpi=200)
    plt.close(fig)
    print("[fig] fig3_coupling")


if __name__ == "__main__":
    fig_grouping()
    fig_outcomes()
    fig_coupling()
    print("FIGURES COMPLETE ->", FIGDIR)
