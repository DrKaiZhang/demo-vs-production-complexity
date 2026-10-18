"""Statistics for the IE study, computed from the worktree-based profiling.

The corpus is small by construction (each project contributes one row, and the
industrial-software population of openly licensed repositories is limited), so the
analysis is built around *effect sizes with intervals* rather than around
significance claims, and every comparison reports its exact n. Group membership
is derived from measured marker evidence with the cut at the observed median,
and the headline comparison is repeated at a stricter cut.
"""
import os
import sys
import csv
import json
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
ROOT = os.path.dirname(STUDY)
TABLES = os.path.join(STUDY, "data", "analysis_out4")
sys.path.insert(0, os.path.join(ROOT, "00_shared"))
try:
    import stats_core as ST
except ImportError:  # pragma: no cover
    import stats_tools as ST

DENSE_MIN = 50
HMI_DOMAINS = ("industrial-HMI", "monitoring-UI", "SCADA-runtime")
PROTO_DOMAINS = ("industrial-protocol-stack", "industrial-messaging",
                 "industrial-protocol-client")
FW_DOMAINS = ("embedded-OS", "RTOS-kernel", "IoT-middleware")

NUMERIC = ["n_functions", "sloc", "cc_mean", "cc_median", "cc_p75", "cc_p90",
           "cc_p95", "cc_p99", "cc_max", "cc_sd", "cc_per_kloc",
           "median_fn_nloc", "p90_fn_nloc", "long_fn_share", "mean_params",
           "share_Cplus", "share_DEplus", "comment_ratio", "mean_instability",
           "include_edges", "max_ca", "max_ce", "demo_subtree_share",
           "industrial_hits", "instructional_hits"]


def num(v, cast=float):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def median(vals, default=0.0):
    v = sorted(x for x in vals if x is not None)
    return v[len(v) // 2] if v else default


def load(n, d=TABLES):
    p = os.path.join(d, n)
    return list(csv.DictReader(open(p, encoding="utf-8"))) \
        if os.path.exists(p) else []


def main():
    rows = load("project_metrics.csv")
    if not rows:
        print("no project_metrics.csv -- run profile_local.py first")
        return
    for r in rows:
        for k in NUMERIC:
            r[k] = num(r.get(k))
        r["n_files_with_functions"] = num(r.get("n_files_with_functions"), int)

    # ---- derived grouping: cuts at the observed medians of the two markers
    demo_cut = median([r["demo_subtree_share"] for r in rows], 0.01) or 0.01
    ins_cut = median([r["instructional_hits"] for r in rows], 100) or 100
    ind_cut = median([r["industrial_hits"] for r in rows], 100) or 100
    for r in rows:
        r["is_demo"] = int(r["demo_subtree_share"] >= demo_cut
                          and r["instructional_hits"] >= ins_cut)
        r["is_industrial"] = int(r["industrial_hits"] >= ind_cut)
        r["group"] = ("not-industrial-verified" if not r["is_industrial"]
                      else ("demonstration-oriented" if r["is_demo"]
                            else "production-oriented"))
    demo = [r for r in rows if r["group"] == "demonstration-oriented"]
    prod = [r for r in rows if r["group"] == "production-oriented"]
    other = [r for r in rows if r["group"] == "not-industrial-verified"]

    out = {
        "population": dict(
            n_projects=len(rows),
            n_functions=sum(int(r["n_functions"] or 0) for r in rows),
            n_sloc=sum(int(r["sloc"] or 0) for r in rows),
            n_file_records=len(load("file_metrics.csv")),
            groups=dict(Counter(r["group"] for r in rows))),
        "grouping": dict(
            cuts=dict(demo_share_cut=demo_cut, instructional_cut=ins_cut,
                      industrial_cut=ind_cut,
                      basis="observed medians of the marker measures"),
            assignment={r["project"]: dict(
                group=r["group"],
                demo_subtree_share=r["demo_subtree_share"],
                instructional_hits=r["instructional_hits"],
                industrial_hits=r["industrial_hits"],
                n_functions=int(r["n_functions"] or 0),
                cc_mean=r["cc_mean"], cc_p95=r["cc_p95"])
                for r in rows}),
    }
    print(f"[grouping] demo>={demo_cut} ins>={ins_cut} ind>={ind_cut} -> "
          f"{dict(Counter(r['group'] for r in rows))}")

    # ------------------------------------------------------ continuous view
    # With a corpus this small a median split leaves one or two projects in a
    # cell, so the demonstration component is *also* analysed as a continuous
    # variable: a project-level Spearman correlation needs no cell sizes and
    # uses every project. This is the primary analysis; the binary split is
    # reported as a secondary, descriptive view.
    cont = {}
    for k in ("cc_mean", "cc_p95", "cc_max", "cc_per_kloc", "share_Cplus",
              "median_fn_nloc", "long_fn_share", "mean_params",
              "mean_instability", "include_edges", "max_ca", "comment_ratio"):
        xs = [r["demo_subtree_share"] for r in rows if r[k] is not None]
        ys = [r[k] for r in rows if r[k] is not None]
        if len(xs) >= 4:
            s = ST.spearman(xs, ys)
            s["x"] = "demo_subtree_share"
            s["y"] = k
            cont[f"demo_vs_{k}"] = s
            if s.get("rho") is not None:
                print(f"[cont] demo_share vs {k}: rho={s['rho']} p={s['p']}")
    for k in ("cc_mean", "cc_p95", "cc_per_kloc", "include_edges"):
        xs = [r["instructional_hits"] for r in rows if r[k] is not None]
        ys = [r[k] for r in rows if r[k] is not None]
        if len(xs) >= 4:
            s = ST.spearman(xs, ys)
            s["x"] = "instructional_hits"
            s["y"] = k
            cont[f"instructional_vs_{k}"] = s
    for k in ("cc_mean", "cc_p95", "cc_per_kloc"):
        xs = [r["industrial_hits"] for r in rows if r[k] is not None]
        ys = [r[k] for r in rows if r[k] is not None]
        if len(xs) >= 4:
            s = ST.spearman(xs, ys)
            s["x"] = "industrial_hits"
            s["y"] = k
            cont[f"industrial_vs_{k}"] = s
    # size confound: does the demonstration share simply track project size?
    for k in ("n_functions", "sloc", "cc_per_kloc"):
        xs = [r["demo_subtree_share"] for r in rows if r[k] is not None]
        ys = [r[k] for r in rows if r[k] is not None]
        if len(xs) >= 4:
            s = ST.spearman(xs, ys)
            s["x"] = "demo_subtree_share"
            s["y"] = k
            cont[f"demo_vs_{k}"] = s
    out["continuous_associations"] = cont

    # ------------------------------------------------------------ RQ1 profile
    r1 = []
    for g, sel in (("demonstration-oriented", demo),
                   ("production-oriented", prod),
                   ("not-industrial-verified", other)):
        for k in ("cc_mean", "cc_p95", "cc_max", "share_Cplus", "cc_per_kloc",
                  "n_functions"):
            vals = [x[k] for x in sel if x[k] is not None]
            if vals:
                r1.append(dict(group=g, metric=k, n_projects=len(vals),
                               **ST.describe(vals, k)))
    out["rq1_profile"] = r1
    tests = {}
    for k in ("cc_mean", "cc_p95", "cc_max", "share_Cplus", "cc_per_kloc",
              "n_functions", "median_fn_nloc", "long_fn_share"):
        a = [x[k] for x in demo if x[k] is not None]
        b = [x[k] for x in prod if x[k] is not None]
        if len(a) >= 3 and len(b) >= 3:
            t = ST.mannwhitney_u(a, b)
            t["cliffs_delta"] = ST.cliffs_delta(a, b)
            t["delta_ci"] = ST.cliffs_delta_ci(a, b, n_boot=600)
            t["median_diff_ci"] = ST.bootstrap_diff_median_ci(a, b, n_boot=1200)
            tests[k] = t
            print(f"[rq1] {k}: demo med={ST.quantile(sorted(a), .5)} "
                  f"prod med={ST.quantile(sorted(b), .5)} p={t.get('p')} "
                  f"delta={t.get('effect_r')}")
    out["rq1_tests"] = tests
    ST.write_csv(r1, os.path.join(TABLES, "analysis_rq1_profile.csv"))

    # ------------------------------------------------- RQ2 what distinguishes
    # per-project ranking, so a small-n result is still inspectable
    r2 = sorted(
        (dict(project=r["project"], group=r["group"],
              cc_mean=r["cc_mean"], cc_p95=r["cc_p95"],
              cc_per_kloc=r["cc_per_kloc"],
              median_fn_nloc=r["median_fn_nloc"],
              long_fn_share=r["long_fn_share"],
              share_Cplus=r["share_Cplus"],
              demo_subtree_share=r["demo_subtree_share"],
              industrial_hits=r["industrial_hits"],
              instructional_hits=r["instructional_hits"],
              n_functions=int(r["n_functions"] or 0),
              sloc=int(r["sloc"] or 0))
         for r in rows),
        key=lambda x: -(x["cc_p95"] or 0))
    ST.write_csv(r2, os.path.join(TABLES, "analysis_rq2_per_project.csv"))
    out["rq2_per_project"] = r2
    print("[rq2] cc_p95 ranking: " + ", ".join(
        f"{x['project']}={x['cc_p95']}" for x in r2))

    # ------------------------------------------------------ RQ3 coupling
    r3 = []
    for g, sel in (("demonstration-oriented", demo),
                   ("production-oriented", prod)):
        for k in ("mean_instability", "include_edges", "max_ca", "max_ce",
                  "comment_ratio"):
            vals = [x[k] for x in sel if x[k] is not None]
            if vals:
                r3.append(dict(group=g, metric=k, n_projects=len(vals),
                               **ST.describe(vals, k)))
    t3 = {}
    for k in ("include_edges", "mean_instability", "max_ca", "max_ce"):
        a = [x[k] for x in demo if x[k] is not None]
        b = [x[k] for x in prod if x[k] is not None]
        if len(a) >= 3 and len(b) >= 3:
            t = ST.mannwhitney_u(a, b)
            t["cliffs_delta"] = ST.cliffs_delta(a, b)
            t3[k] = t
            print(f"[rq3] {k}: p={t.get('p')} delta={t.get('effect_r')}")
    out["rq3_coupling"] = dict(per_group=r3, tests=t3,
                               note="coupling from a resolved #include graph: "
                                    "Ca = project units including a file, "
                                    "Ce = project files it includes, "
                                    "instability = Ce/(Ca+Ce)")
    ST.write_csv(r3, os.path.join(TABLES, "analysis_rq3_coupling.csv"))

    # per-file instability (the unit-level view)
    frows = load("file_metrics.csv")
    fd = [num(x.get("ca")) for x in frows if num(x.get("ca")) is not None]
    if fd:
        out["rq3_file_level"] = dict(
            n_files_with_coupling=len(fd),
            ca=ST.describe(fd, "afferent coupling"))
        print(f"[rq3] per-file coupling available for {len(fd)} files")

    # ------------------------------------------- RQ4 domain view
    dom = defaultdict(list)
    for r in rows:
        dom[r.get("worktree", "?")].append(r)
    r4 = [dict(worktree=k, n_projects=len(v),
               mean_cc_mean=round(
                   sum(x["cc_mean"] for x in v if x["cc_mean"] is not None)
                   / max(1, len([x for x in v if x["cc_mean"] is not None])), 3),
               max_cc_p95=max((x["cc_p95"] for x in v
                               if x["cc_p95"] is not None), default=None),
               total_functions=sum(int(x["n_functions"] or 0) for x in v))
          for k, v in sorted(dom.items())]
    out["rq4"] = dict(per_project=r4,
                      note="each worktree is one analysed revision of one "
                           "repository; the domain taxonomy is the project's "
                           "own declared domain, recorded in targets.json")
    ST.write_csv(r4, os.path.join(TABLES, "analysis_rq4_summary.csv"))

    # ------------------------------------------ sensitivity to the group cut
    def regroup(dc, ic):
        g = {}
        for r in rows:
            d = r["demo_subtree_share"] or 0
            i = r["instructional_hits"] or 0
            n = r["industrial_hits"] or 0
            g[r["project"]] = ("not-industrial-verified" if n < ind_cut else
                               ("demonstration-oriented"
                                if d >= dc and i >= ic else
                                "production-oriented"))
        return g

    def compare(g, k="cc_p95"):
        a = [r[k] for r in demo_rows(g) if r[k] is not None]
        b = [r[k] for r in prod_rows(g) if r[k] is not None]
        if len(a) < 3 or len(b) < 3:
            return dict(n_demo=len(a), n_prod=len(b),
                        note="group too small for a test at this cut")
        t = ST.mannwhitney_u(a, b)
        t["cliffs_delta"] = ST.cliffs_delta(a, b)
        t["delta_ci"] = ST.cliffs_delta_ci(a, b, n_boot=600)
        return dict(n_demo=len(a), n_prod=len(b),
                    median_demo=ST.quantile(sorted(a), .5),
                    median_prod=ST.quantile(sorted(b), .5),
                    **{kk: v for kk, v in t.items()})

    def demo_rows(g):
        return [r for r in rows if g[r["project"]] == "demonstration-oriented"]

    def prod_rows(g):
        return [r for r in rows if g[r["project"]] == "production-oriented"]

    q_demos = ST.quantile(sorted(r["demo_subtree_share"] for r in rows
                                 if r["demo_subtree_share"] is not None), .25)
    q_ins = ST.quantile(sorted(r["instructional_hits"] for r in rows
                               if r["instructional_hits"] is not None), .25)
    sens = dict(
        at_median_cut=dict(demo_cut=demo_cut, ins_cut=ins_cut,
                           **compare({r["project"]: r["group"] for r in rows})),
        at_upper_quartile_cut=dict(
            demo_cut=q_demos or demo_cut, ins_cut=q_ins or ins_cut,
            **compare(regroup(q_demos or demo_cut, q_ins or ins_cut))))
    out["sensitivity"] = sens
    for k, v in sens.items():
        print(f"[sens] {k}: n_demo={v.get('n_demo')} n_prod={v.get('n_prod')} "
              f"p={v.get('p')} delta={v.get('effect_r')}")
    ST.write_csv([dict(cut=k, **{kk: vv for kk, vv in v.items()
                                 if not isinstance(vv, (list, dict))})
                  for k, v in sens.items()],
                 os.path.join(TABLES, "analysis_sensitivity.csv"))

    p = os.path.join(TABLES, "analysis_results.json")
    json.dump(out, open(p, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"[write] {p}")
    print("STATS COMPLETE")


if __name__ == "__main__":
    main()
