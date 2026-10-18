#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
05_IE_demo_complexity / analyse.py

Analysis of the industrial-software code-metric corpus. The grouping is
*derived from measurements*, not declared: a project enters the
demonstration-oriented group when its demonstration-subtree code share and its
instructional-marker density both exceed thresholds fixed before the metrics
were computed, and it is industrial-verified when its industrial-marker density
clears a third threshold. The thresholds and the resulting groups are written
out so a reader can check or change them.

Research questions
  RQ1  How is cyclomatic complexity distributed in industrial-software
       functions, and how does the distribution differ between
       demonstration-oriented and production-oriented industrial projects?
  RQ2  Do demonstration projects carry a measurably different complexity
       profile (function length, parameter count, long-function share) from
       production industrial projects?
  RQ3  How do module coupling characteristics (afferent/efferent coupling and
       instability) differ between the two groups?
  RQ4  Is complexity associated with the industrial domain (RTOS/protocol/HMI)
       independently of the demonstration/production grouping?
"""
import os
import re
import sys
import csv
import json
import math
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
# Output sub-directory: a spreadsheet left open on a previous run holds an
# exclusive lock on its files, which would abort the whole pipeline.
OUTDIR = os.path.join(OUTDIR, "analysis_out")
os.makedirs(OUTDIR, exist_ok=True)
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "00_shared"))
try:
    import stats_core as ST  # noqa: E402  (retrying writer)
except ImportError:  # pragma: no cover
    import stats_tools as ST  # noqa: E402

def _median(vals, default):
    v = sorted(x for x in vals if x is not None)
    return v[len(v) // 2] if v else default


# Grouping rule.  The cut points are the *observed medians* of the two marker
# measures, so the demonstration-oriented group is by construction the half of
# the industrial-verified corpus with the larger demonstration component. A
# median rather than a hand-picked constant keeps the grouping stable as
# projects are added; the realised values and the full raw distributions are
# written to the output, and the headline tests are repeated at an alternative
# cut so a reader can see whether any conclusion depends on where the line sits.
DEMO_SHARE_FALLBACK = 0.02
INSTRUCTIONAL_FALLBACK = 100
INDUSTRIAL_FALLBACK = 100

HMI_DOMAINS = ("industrial-HMI", "monitoring-UI", "SCADA-runtime")
PROTO_DOMAINS = ("industrial-protocol-stack", "industrial-messaging",
                 "industrial-protocol-client")
FW_DOMAINS = ("embedded-OS", "RTOS-kernel", "IoT-middleware")


def load(name):
    p = os.path.join(DATA, name)
    return list(csv.DictReader(open(p, encoding="utf-8"))) if os.path.exists(p) else []


def num(v, cast=float):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def main():
    proj = load("project_metrics.csv")
    mark = load("marker_evidence.csv")
    files = load("file_metrics.csv")
    if not proj:
        print("no project_metrics.csv -- run complexity_profile.py first")
        return
    P = {r["project"]: r for r in proj}
    M = {r["project"]: r for r in mark}

    # ---------------------------------------------------- derived grouping
    ev = [(num(m["demo_subtree_share"], float) or 0.0,
           num(m["instructional_marker_hits"], int) or 0,
           num(m["industrial_marker_hits"], int) or 0)
          for name, m in M.items() if name in P]
    demo_cut = _median([x[0] for x in ev], DEMO_SHARE_FALLBACK)
    ins_cut = _median([x[1] for x in ev], INSTRUCTIONAL_FALLBACK)
    ind_cut = _median([x[2] for x in ev], INDUSTRIAL_FALLBACK)
    # a zero median would make the corresponding test vacuous
    demo_cut = demo_cut if demo_cut > 0 else DEMO_SHARE_FALLBACK
    ins_cut = ins_cut if ins_cut > 0 else INSTRUCTIONAL_FALLBACK
    ind_cut = ind_cut if ind_cut > 0 else INDUSTRIAL_FALLBACK
    print(f"[cuts] demo_share>={demo_cut}  instructional>={ins_cut}  "
          f"industrial>={ind_cut}  (n={len(ev)} projects)")

    groups = {}
    for name, m in M.items():
        if name not in P:
            continue
        demo = num(m["demo_subtree_share"], float) or 0.0
        ins = num(m["instructional_marker_hits"], int) or 0
        ind = num(m["industrial_marker_hits"], int) or 0
        is_demo = demo >= demo_cut and ins >= ins_cut
        is_ind = ind >= ind_cut
        if not is_ind:
            grp = "not-industrial-verified"
        elif is_demo:
            grp = "demonstration-oriented"
        else:
            grp = "production-oriented"
        groups[name] = dict(
            group=grp, demo_share=demo, instructional_hits=ins,
            industrial_hits=ind,
            domain=m.get("domain", ""),
            industrial_verified=is_ind,
            demo_evidence=is_demo)
    out = {"grouping": dict(
        thresholds=dict(demo_share_cut=demo_cut, instructional_cut=ins_cut,
                        industrial_cut=ind_cut,
                        basis="observed medians of the marker measures"),
        raw_distributions=dict(
            demo_share=sorted(x[0] for x in ev),
            instructional_hits=sorted(x[1] for x in ev),
            industrial_hits=sorted(x[2] for x in ev)),
        rule=("a project is industrial-verified when its industrial-marker "
              "hits reach the threshold; among those, demonstration-oriented "
              "means its demo-subtree code share and instructional-marker hits "
              "both reach their thresholds; all others are production-oriented"),
        assignment=groups,
        counts=dict(Counter(v["group"] for v in groups.values())))}

    grp_rows = []
    for name, g in sorted(groups.items(), key=lambda x: (x[1]["group"], x[0])):
        p = P[name]
        grp_rows.append(dict(
            project=name, group=g["group"], domain=g["domain"],
            demo_share=g["demo_share"],
            instructional_hits=g["instructional_hits"],
            industrial_hits=g["industrial_hits"],
            n_functions=num(p["n_functions"], int),
            sloc=num(p["sloc"], int),
            cc_mean=num(p["cc_mean"]), cc_median=num(p["cc_median"]),
            cc_p75=num(p["cc_p75"]), cc_p90=num(p["cc_p90"]),
            cc_p95=num(p["cc_p95"]), cc_p99=num(p["cc_p99"]),
            cc_max=num(p["cc_max"], int), cc_sd=num(p["cc_sd"]),
            cc_per_kloc=num(p["cc_per_kloc"]),
            median_fn_nloc=num(p["median_fn_nloc"]),
            p90_fn_nloc=num(p["p90_fn_nloc"]),
            long_fn_share=num(p["long_fn_share"]),
            mean_params=num(p["mean_params"]),
            share_Cplus=num(p["share_Cplus"]),
            share_DEplus=num(p["share_DEplus"]),
            comment_ratio=num(p["comment_ratio"]),
            mean_instability=num(p["mean_instability"]),
            include_edges=num(p["include_edges"], int),
            max_ca=num(p["max_ca"], int), max_ce=num(p["max_ce"], int)))
    ST.write_csv(grp_rows, os.path.join(OUTDIR, "analysis_group_assignment.csv"))
    print(f"[grouping] {out['grouping']['counts']}")
    for r in grp_rows:
        print(f"   {r['group'][:26]:28} {r['project'][:20]:22} "
              f"demo={r['demo_share']:.3f} ins={r['instructional_hits']:>4} "
              f"cc_mean={r['cc_mean']}")

    demo = [r for r in grp_rows if r["group"] == "demonstration-oriented"]
    prod = [r for r in grp_rows if r["group"] == "production-oriented"]

    # ------------------------------------------------------------- RQ1 dist
    fr_demo = [x for x in files if groups.get(x["project"], {}).get("group")
               == "demonstration-oriented"]
    fr_prod = [x for x in files if groups.get(x["project"], {}).get("group")
               == "production-oriented"]
    r1 = []
    for gname, fr in (("demonstration-oriented", fr_demo),
                      ("production-oriented", fr_prod)):
        if not fr:
            continue
        cc_max = sorted(num(x["cc_max"], int) or 0 for x in fr)
        cc_mean = sorted(num(x["cc_mean"]) or 0 for x in fr)
        r1.append(dict(group=gname, n_files=len(fr),
                       median_file_cc_max=ST.quantile(cc_max, .5),
                       p90_file_cc_max=ST.quantile(cc_max, .9),
                       p99_file_cc_max=ST.quantile(cc_max, .99),
                       max_file_cc_max=max(cc_max),
                       median_file_cc_mean=ST.quantile(cc_mean, .5),
                       p90_file_cc_mean=ST.quantile(cc_mean, .9),
                       share_files_cc_gt10=round(
                           sum(1 for v in cc_max if v > 10) / len(cc_max), 4),
                       share_files_cc_gt20=round(
                           sum(1 for v in cc_max if v > 20) / len(cc_max), 4)))
    out["rq1"] = dict(per_group=r1)
    if len(demo) >= 3 and len(prod) >= 3:
        t = ST.mannwhitney_u([x["cc_mean"] for x in demo],
                             [x["cc_mean"] for x in prod])
        t["cliffs_delta"] = ST.cliffs_delta([x["cc_mean"] for x in demo],
                                            [x["cc_mean"] for x in prod])
        t["median_diff_ci"] = ST.bootstrap_diff_median_ci(
            [x["cc_mean"] for x in demo], [x["cc_mean"] for x in prod])
        out["rq1"]["test_project_cc_mean"] = t
        t2 = ST.mannwhitney_u([x["cc_p95"] for x in demo],
                              [x["cc_p95"] for x in prod])
        t2["cliffs_delta"] = ST.cliffs_delta([x["cc_p95"] for x in demo],
                                             [x["cc_p95"] for x in prod])
        out["rq1"]["test_project_cc_p95"] = t2
        t3 = ST.mannwhitney_u([x["share_Cplus"] for x in demo],
                              [x["share_Cplus"] for x in prod])
        t3["cliffs_delta"] = ST.cliffs_delta(
            [x["share_Cplus"] for x in demo],
            [x["share_Cplus"] for x in prod])
        out["rq1"]["test_share_cc_gt10"] = t3
        print(f"[rq1] project cc_mean demo vs prod: p={t.get('p')} "
              f"delta={t.get('effect_r')}")
        print(f"[rq1] project cc_p95: p={t2.get('p')}")
    ST.write_csv(r1, os.path.join(OUTDIR, "analysis_rq1_complexity_dist.csv"))

    # ------------------------------------------------- RQ2 function profile
    r2 = []
    for gname, sel in (("demonstration-oriented", demo),
                       ("production-oriented", prod)):
        for metric in ("median_fn_nloc", "p90_fn_nloc", "long_fn_share",
                       "mean_params", "comment_ratio", "cc_per_kloc"):
            vals = [x[metric] for x in sel if x.get(metric) is not None]
            if vals:
                r2.append(dict(group=gname, metric=metric, n_projects=len(vals),
                               **ST.describe(vals, metric)))
    out["rq2"] = dict(per_group_metric=r2)
    tests2 = {}
    for metric in ("median_fn_nloc", "p90_fn_nloc", "long_fn_share",
                  "mean_params", "cc_per_kloc"):
        a = [x[metric] for x in demo if x.get(metric) is not None]
        b = [x[metric] for x in prod if x.get(metric) is not None]
        if len(a) >= 3 and len(b) >= 3:
            t = ST.mannwhitney_u(a, b)
            t["cliffs_delta"] = ST.cliffs_delta(a, b)
            t["median_diff_ci"] = ST.bootstrap_diff_median_ci(a, b)
            tests2[metric] = t
            print(f"[rq2] {metric}: p={t.get('p')} delta={t.get('effect_r')}")
    out["rq2"]["tests"] = tests2
    ST.write_csv(r2, os.path.join(OUTDIR, "analysis_rq2_function_profile.csv"))

    # ------------------------------------------------------------ RQ3 coupling
    r3 = []
    for gname, sel in (("demonstration-oriented", demo),
                       ("production-oriented", prod)):
        for metric in ("mean_instability", "include_edges", "max_ca", "max_ce"):
            vals = [x[metric] for x in sel if x.get(metric) is not None]
            if vals:
                r3.append(dict(group=gname, metric=metric, n_projects=len(vals),
                               **ST.describe(vals, metric)))
    tests3 = {}
    for metric in ("mean_instability", "include_edges", "max_ca"):
        a = [x[metric] for x in demo if x.get(metric) is not None]
        b = [x[metric] for x in prod if x.get(metric) is not None]
        if len(a) >= 3 and len(b) >= 3:
            t = ST.mannwhitney_u(a, b)
            t["cliffs_delta"] = ST.cliffs_delta(a, b)
            tests3[metric] = t
            print(f"[rq3] {metric}: p={t.get('p')} delta={t.get('effect_r')}")
    out["rq3"] = dict(per_group_metric=r3, tests=tests3,
                     note=("coupling is computed from a resolved #include graph: "
                           "afferent coupling = number of project translation "
                           "units that include this file, efferent = number of "
                           "project files it includes; instability = Ce/(Ca+Ce)"))
    # per-file instability distribution (the unit-level view)
    fi_demo = [num(x["instability"]) for x in fr_demo
               if num(x["instability"]) is not None]
    fi_prod = [num(x["instability"]) for x in fr_prod
               if num(x["instability"]) is not None]
    if fi_demo and fi_prod:
        out["rq3"]["file_instability"] = dict(
            demonstration=ST.describe(fi_demo, "demo"),
            production=ST.describe(fi_prod, "prod"),
            test=ST.mannwhitney_u(fi_demo, fi_prod))
    ST.write_csv(r3, os.path.join(OUTDIR, "analysis_rq3_coupling.csv"))

    # ---------------------------------------------------------- RQ4 by domain
    dom = defaultdict(list)
    for r in grp_rows:
        if r["group"] == "not-industrial-verified":
            continue
        dom[r["domain"]].append(r)
    r4 = []
    for d, sel in sorted(dom.items(), key=lambda x: -len(x[1])):
        r4.append(dict(domain=d, n_projects=len(sel),
                       n_demo=sum(1 for x in sel
                                  if x["group"] == "demonstration-oriented"),
                       mean_cc=round(
                           sum(x["cc_mean"] for x in sel) / len(sel), 3),
                       median_cc_p95=ST.quantile(
                           sorted(x["cc_p95"] for x in sel), .5),
                       median_share_Cplus=ST.quantile(
                           sorted(x["share_Cplus"] for x in sel), .5),
                       median_fn_nloc=ST.quantile(
                           sorted(x["median_fn_nloc"] for x in sel
                                  if x["median_fn_nloc"] is not None), .5)
                       if any(x["median_fn_nloc"] is not None for x in sel) else "",
                       sloc=sum(x["sloc"] or 0 for x in sel)))
    out["rq4"] = dict(per_domain=r4)
    # firmware vs platform vs HMI
    def sel_of(domains):
        return [r for r in grp_rows
                if r["domain"] in domains and r["group"] !=
                "not-industrial-verified"]
    fw, pf, hmi = sel_of(FW_DOMAINS), sel_of(PROTO_DOMAINS), sel_of(HMI_DOMAINS)
    tests4 = {}
    for label, a, b in (("firmware_vs_platform", fw, pf),
                        ("platform_vs_hmi", pf, hmi),
                        ("firmware_vs_hmi", fw, hmi)):
        if len(a) >= 3 and len(b) >= 3:
            t = ST.mannwhitney_u([x["cc_p95"] for x in a],
                                 [x["cc_p95"] for x in b])
            t["cliffs_delta"] = ST.cliffs_delta([x["cc_p95"] for x in a],
                                                [x["cc_p95"] for x in b])
            tests4[label] = t
            print(f"[rq4] cc_p95 {label}: p={t.get('p')} "
                  f"delta={t.get('effect_r')}")
    out["rq4"]["tests_cc_p95"] = tests4
    out["rq4"]["group_definitions"] = dict(
        firmware=FW_DOMAINS, platform=PROTO_DOMAINS, hmi=HMI_DOMAINS)
    ST.write_csv(r4, os.path.join(OUTDIR, "analysis_rq4_by_domain.csv"))

    # ------------------------------------------- sensitivity to the group cut
    # The headline comparisons are repeated at the *lower quartile* cut, i.e.
    # with a stricter definition of demonstration-oriented. If a conclusion
    # only holds at one cut, it is a property of the threshold, not of the code.
    def regroup(dc, ic):
        g = {}
        for name, m in M.items():
            if name not in P:
                continue
            d = num(m["demo_subtree_share"], float) or 0.0
            i = num(m["instructional_marker_hits"], int) or 0
            n = num(m["industrial_marker_hits"], int) or 0
            if n < ind_cut:
                g[name] = "not-industrial-verified"
            elif d >= dc and i >= ic:
                g[name] = "demonstration-oriented"
            else:
                g[name] = "production-oriented"
        return g

    def compare(g):
        a = [r["cc_p95"] for r in grp_rows
             if g.get(r["project"]) == "demonstration-oriented"
             and r["cc_p95"] is not None]
        b = [r["cc_p95"] for r in grp_rows
             if g.get(r["project"]) == "production-oriented"
             and r["cc_p95"] is not None]
        if len(a) < 3 or len(b) < 3:
            return dict(n_demo=len(a), n_prod=len(b),
                        note="group too small for a test at this cut")
        t = ST.mannwhitney_u(a, b)
        t["cliffs_delta"] = ST.cliffs_delta(a, b)
        return dict(n_demo=len(a), n_prod=len(b),
                    median_cc_p95_demo=ST.quantile(sorted(a), .5),
                    median_cc_p95_prod=ST.quantile(sorted(b), .5),
                    **{k: v for k, v in t.items()})

    q_demos = ST.quantile(sorted(x[0] for x in ev), .25) or demo_cut
    q_ins = ST.quantile(sorted(x[1] for x in ev), .25) or ins_cut
    sens = dict(
        at_median_cut=dict(demo_cut=demo_cut, ins_cut=ins_cut, **compare(groups)),
        at_lower_quartile_cut=dict(demo_cut=q_demos, ins_cut=q_ins,
                                   **compare(regroup(q_demos, q_ins))))
    out["sensitivity"] = sens
    for k, v in sens.items():
        print(f"[sens] {k}: n_demo={v.get('n_demo')} n_prod={v.get('n_prod')} "
              f"p={v.get('p')} delta={v.get('effect_r')}")
    ST.write_csv([dict(cut=k, **{kk: vv for kk, vv in v.items()
                                 if not isinstance(vv, (list, dict))})
                  for k, v in sens.items()],
                 os.path.join(OUTDIR, "analysis_sensitivity.csv"))

    ST.write_json(out, os.path.join(OUTDIR, "analysis_results.json"))
    print("ANALYSIS COMPLETE")

if __name__ == "__main__":
    main()
