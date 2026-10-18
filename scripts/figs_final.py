#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
05_IE_demo_complexity / make_figures.py

Renders the manuscript figures from the same CSVs the text quotes.
"""
import os
import csv
import json
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
# tables produced by analysis_final.py live in a fresh sub-directory so a
# spreadsheet holding a previous run cannot block this one
TABLES = os.path.join(DATA, "analysis_out")
FIG = os.path.join(os.path.dirname(HERE), "figures")
# a viewer left open on a previous PNG holds an exclusive lock, so a run
# writes to a fresh directory instead of failing on save
FIGDIR = os.path.join(os.path.dirname(HERE), "figures_run2")
os.makedirs(FIG, exist_ok=True)
os.makedirs(FIGDIR, exist_ok=True)

plt.rcParams.update({
    "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
    "figure.dpi": 160, "savefig.dpi": 160, "savefig.bbox": "tight",
    "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False,
})
C = dict(demo="#c0504d", prod="#1f4e79", neutral="#7f7f7f",
         amber="#d9a03c", green="#4f8a4f")
LBL = {"demonstration-oriented": "demonstration-oriented",
       "production-oriented": "production-oriented",
       "not-industrial-verified": "not industrial-verified"}


def rd(n):
    p = os.path.join(TABLES, n)
    if not os.path.exists(p):
        p = os.path.join(DATA, n)
    return list(csv.DictReader(open(p, encoding="utf-8"))) if os.path.exists(p) else []


def f(v, d=float):
    try:
        return d(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------ Fig 1: grouping evidence
def fig_grouping():
    rows = rd("analysis_group_assignment.csv")
    if not rows:
        return
    for r in rows:
        for k in ("demo_share", "cc_mean", "cc_p95", "cc_p99", "cc_max",
                  "median_fn_nloc", "long_fn_share", "mean_params",
                  "mean_instability", "include_edges", "share_Cplus",
                  "cc_median", "cc_p75", "cc_p90", "cc_sd", "cc_per_kloc",
                  "comment_ratio", "p90_fn_nloc", "max_ca", "max_ce"):
            r[k] = f(r[k])
        r["instructional_hits"] = f(r["instructional_hits"], int) or 0
        r["industrial_hits"] = f(r["industrial_hits"], int) or 0
    rows.sort(key=lambda r: r["demo_share"])
    col = [C["demo"] if r["group"] == "demonstration-oriented"
           else (C["prod"] if r["group"] == "production-oriented"
                 else C["neutral"]) for r in rows]
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    y = np.arange(len(rows))
    ax.barh(y, [r["demo_share"] for r in rows], color=col, height=0.66)
    # the cut actually used by analyse.py, not a hard-coded constant
    cut = None
    rp = os.path.join(TABLES, "analysis_results.json")
    if os.path.exists(rp):
        try:
            cut = json.load(open(rp, encoding="utf-8"))["grouping"][
                "thresholds"]["demo_share_cut"]
        except Exception:
            cut = None
    if cut is not None:
        ax.axvline(cut, color="k", ls="--", lw=0.9)
        ax.text(cut * 1.12, len(rows) - 0.4,
                f" cut = {cut*100:.2f}%\n (observed median)",
                fontsize=7.2, va="top")
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r['project'][:22]}  (ins={r['instructional_hits']})"
                        for r in rows], fontsize=7.2)
    ax.xaxis.set_major_formatter(
        matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlabel("share of code files in demonstration subtrees")
    ax.set_title("Fig. 1  Measured grouping evidence\n"
                 "red = demonstration-oriented, blue = production-oriented, "
                 "grey = not industrial-verified", loc="left")
    fig.savefig(os.path.join(FIGDIR, "fig1_grouping_evidence.png"))
    plt.close(fig)
    print("[fig] fig1")


# ------------------------------------------- Fig 2: CC distribution by group
def fig_cc_dist():
    res_path = os.path.join(DATA, "analysis_results.json")
    if not os.path.exists(res_path):
        return
    res = json.load(open(res_path, encoding="utf-8"))
    per = res.get("rq1", {}).get("per_group", [])
    if not per:
        return
    rows = rd("analysis_group_assignment.csv")
    files = rd("file_metrics.csv")
    grp = {r["project"]: r["group"] for r in rows}
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.2))
    ax = axes[0]
    data, labs, cols = [], [], []
    for g, c in (("demonstration-oriented", C["demo"]),
                 ("production-oriented", C["prod"])):
        v = [f(x["cc_max"], int) or 0 for x in files
             if grp.get(x["project"]) == g]
        v = [x for x in v if x > 0]
        if v:
            data.append(v)
            labs.append(LBL[g])
            cols.append(c)
    if data:
        bp = ax.boxplot(data, vert=True, widths=0.5, patch_artist=True,
                        showfliers=False)
        for p, c in zip(bp["boxes"], cols):
            p.set_facecolor(c)
            p.set_alpha(0.65)
        for med in bp["medians"]:
            med.set_color("black")
        ax.set_xticks(range(1, len(labs) + 1))
        ax.set_xticklabels(labs, fontsize=8)
        ax.set_ylabel("per-file maximum cyclomatic complexity")
        ax.set_title("(a) per-file max CCN", loc="left", fontsize=9)
    ax = axes[1]
    labels = [r["group"] for r in per]
    xs = np.arange(len(labels))
    m = [r["median_file_cc_max"] for r in per]
    p90 = [r["p90_file_cc_max"] for r in per]
    p99 = [r["p99_file_cc_max"] for r in per]
    w = 0.26
    cc = [C["demo"] if "demon" in l else C["prod"] for l in labels]
    ax.bar(xs - w, m, w, label="median", color=cc, alpha=0.85)
    ax.bar(xs, p90, w, label="p90", color=cc, alpha=0.6)
    ax.bar(xs + w, p99, w, label="p99", color=cc, alpha=0.4)
    ax.set_xticks(xs)
    ax.set_xticklabels([LBL[l] for l in labels], fontsize=8)
    ax.set_ylabel("per-file max CCN")
    ax.legend(fontsize=7.5, frameon=False)
    ax.set_title("(b) distribution shape", loc="left", fontsize=9)
    fig.suptitle("Fig. 2  Cyclomatic-complexity distribution of industrial "
                 "software files", x=0.01, ha="left", fontsize=10)
    fig.savefig(os.path.join(FIGDIR, "fig2_cc_distribution.png"))
    plt.close(fig)
    print("[fig] fig2")


# ------------------------------------- Fig 3: project-level scatter (grouping)
def fig_scatter():
    rows = [r for r in rd("analysis_group_assignment.csv")
            if r["group"] != "not-industrial-verified"]
    if len(rows) < 4:
        return
    for r in rows:
        for k in ("cc_p95", "median_fn_nloc", "cc_mean", "long_fn_share",
                  "mean_instability", "share_Cplus", "demo_share"):
            r[k] = f(r[k])
    fig, axes = plt.subplots(1, 3, figsize=(9.6, 2.9))
    dm = [r for r in rows if r["group"] == "demonstration-oriented"]
    pr = [r for r in rows if r["group"] == "production-oriented"]
    specs = [("cc_p95", "project cc p95", "(a) tail complexity"),
             ("median_fn_nloc", "median function NLOC", "(b) function size"),
             ("long_fn_share", "share of functions > 60 NLOC",
              "(c) long functions")]
    for ax, (k, xl, title) in zip(axes, specs):
        for sel, c, lbl in ((dm, C["demo"], "demonstration"),
                            (pr, C["prod"], "production")):
            xs = [r["demo_share"] for r in sel]
            ys = [r[k] for r in sel if r[k] is not None]
            xs = xs[:len(ys)]
            if xs and ys:
                ax.scatter(xs, ys, s=34, color=c, alpha=0.85,
                           label=lbl, edgecolor="white", lw=0.5)
        ax.axvline(0.05, color="k", ls="--", lw=0.8)
        ax.set_xlabel("demo-subtree share")
        ax.set_ylabel(xl, fontsize=8)
        ax.set_title(title, loc="left", fontsize=9)
    axes[0].legend(fontsize=7.5, frameon=False)
    fig.suptitle("Fig. 3  Project-level metrics against measured "
                 "demonstration share", x=0.01, ha="left", fontsize=10)
    fig.savefig(os.path.join(FIGDIR, "fig3_project_metrics.png"))
    plt.close(fig)
    print("[fig] fig3")


# ---------------------------------------------------- Fig 4: domain profile
def fig_domain():
    rows = rd("analysis_rq4_by_domain.csv")
    if not rows:
        return
    rows = [r for r in rows if int(r["n_projects"]) >= 2]
    if not rows:
        return
    rows.sort(key=lambda r: float(r["median_cc_p95"] or 0))
    fig, ax = plt.subplots(figsize=(5.8, 0.42 * len(rows) + 1.4))
    y = np.arange(len(rows))
    vals = [float(r["median_cc_p95"] or 0) for r in rows]
    ax.barh(y, vals, color=C["prod"], height=0.62)
    for i, (r, v) in enumerate(zip(rows, vals)):
        ax.text(v + 0.2, i,
                f"n={r['n_projects']}  demo={r['n_demo']}  "
                f"cc_mean={r['mean_cc']}  longNLOC={r['median_fn_nloc']}",
                va="center", fontsize=7)
    ax.set_yticks(y)
    ax.set_yticklabels([r["domain"][:30] for r in rows], fontsize=7.8)
    ax.set_xlabel("median across projects of the project-level CCN p95")
    ax.set_title("Fig. 4  Complexity tail by industrial domain\n"
                 "industrial-verified projects only", loc="left")
    ax.set_xlim(0, max(vals) * 1.75)
    fig.savefig(os.path.join(FIGDIR, "fig4_domain_profile.png"))
    plt.close(fig)
    print("[fig] fig4")


# ------------------------------------------------- Fig 5: coupling instability
def fig_coupling():
    files = rd("file_metrics.csv")
    rows = rd("analysis_group_assignment.csv")
    if not files or not rows:
        return
    grp = {r["project"]: r["group"] for r in rows}
    fig, ax = plt.subplots(figsize=(5.6, 3.0))
    data, labs, cols = [], [], []
    for g, c in (("demonstration-oriented", C["demo"]),
                 ("production-oriented", C["prod"])):
        v = [f(x["instability"]) for x in files if grp.get(x["project"]) == g]
        v = [x for x in v if x is not None and x > 0]
        if v:
            data.append(v)
            labs.append(LBL[g])
            cols.append(c)
    if data:
        bp = ax.boxplot(data, vert=False, widths=0.5, patch_artist=True,
                        showfliers=False)
        for p, c in zip(bp["boxes"], cols):
            p.set_facecolor(c)
            p.set_alpha(0.65)
        for med in bp["medians"]:
            med.set_color("black")
        ax.set_yticks(range(1, len(labs) + 1))
        ax.set_yticklabels(labs, fontsize=8)
        ax.set_xlabel("module instability  Ce / (Ca + Ce)")
        ax.set_title("Fig. 5  Module instability from a resolved #include "
                     "graph\n(files with Ca+Ce > 0)", loc="left")
    fig.savefig(os.path.join(FIGDIR, "fig5_coupling_instability.png"))
    plt.close(fig)
    print("[fig] fig5")


if __name__ == "__main__":
    fig_grouping()
    fig_cc_dist()
    fig_scatter()
    fig_domain()
    fig_coupling()
    print("FIGURES COMPLETE ->", FIGDIR)
