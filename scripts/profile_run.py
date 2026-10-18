#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
05_IE_demo_complexity / complexity_profile.py

Static code-metric profiling of open-source industrial-software repositories,
with a measured grouping into demonstration-oriented and production-oriented
industrial software.

Tooling note (this determined the design): `radon` parses Python only -- its
`code2ast` raises SyntaxError on C, so a radon-based profiler silently yields
zero functions on a C/C++ corpus. This profiler therefore uses `lizard`, whose
CLikeReader handles C, C++, Java, C#, JavaScript, Rust, Go and Python, and
combines it with:
  * `radon`'s language-agnostic `raw.analyze` for SLOC/LOC/comment ratios
    (it tokenises C correctly even though it cannot build a Python AST), and
  * a purpose-built coupling metric computed from the include graph and the
    per-directory fan-in/fan-out, which no off-the-shelf tool provides for a
    mixed C/C++/Java/Go corpus.

Every metric is computed from real checked-out source. No value is imputed.

Group assignment is *derived*, not declared: each project is measured on
    - instructional-marker density (tutorial/teaching/lab/exercise wording),
    - demonstration-subtree code volume (example/demo/sample/tutorial trees),
    - industrial-marker density (PLC/Modbus/CAN/RTOS/HMI wording),
and the derived label is what appears in project_metrics.csv.
"""
import os
import re
import io
import sys
import json
import math
import csv
import subprocess
import collections
from collections import Counter, defaultdict

import lizard
from radon.raw import analyze

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))       # D:/workbuddy/papers4
sys.path.insert(0, os.path.join(ROOT, "00_shared"))
try:
    import stats_core as ST  # noqa: E402  (retrying writer)
except ImportError:  # pragma: no cover
    import stats_tools as ST  # noqa: E402
REPO_DIRS = [os.path.join(ROOT, "_repos2"), os.path.join(ROOT, "_repos")]
OUT = os.path.join(os.path.dirname(HERE), "data")
os.makedirs(OUT, exist_ok=True)

# extensions and the lizard language name to use
EXT_LANG = {
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".ino": "cpp",
    ".java": "java", ".cs": "cs", ".js": "javascript", ".ts": "typescript",
    ".py": "python", ".go": "go", ".rs": "rust", ".m": "objectivec",
}
# headers are analysed as C but must not be counted as translation units
HEADER = {".h", ".hpp", ".hh"}

SKIP_FILE = re.compile(
    r"\.(min\.js|map|lock|svg|png|jpg|jpeg|gif|pdf|ico|woff2?|ttf|eot|so|"
    r"a|dll|exe|bin|hex|elf|o|obj|lib|jar|class|pyc|mod|sum)$", re.I)
SKIP_DIR = re.compile(
    r"(^|/)(node_modules|\.git|third_party|3rdparty|vendor|external|"
    r"build|dist|target|out|\.github|docs?/(_build|_static)|locale|"
    r"unittests?)(/|$)", re.I)
# third-party / generated trees are excluded from coupling and metric stats
FOREIGN = re.compile(
    r"(^|/)(third_party|3rdparty|vendor|external|deps|extern|"
    r"contrib|libdeps|packages/(?!node_modules)|"
    r"Godeps|vendor_?(rubygems|bundler))(/|$)", re.I)
BIG_FILE = 800_000
# Per-project ceilings.  A metric census does not need every file of a
# 60,000-file C++ repository; the applied bound is recorded per project so the
# truncation is visible in the artefact.
MAX_FILES = int(os.environ.get("MAX_FILES", "12000"))
MAX_FILE_BYTES = 400_000

INDUSTRIAL_MARKERS = [
    ("plc", re.compile(r"\bplc\b|programmable logic|ladder logic|"
                       r"structured text|iec\s*61131", re.I)),
    ("fieldbus", re.compile(r"modbus|profibus|profinet|ethercat|canopen|"
                            r"\bcan\s?(bus|open|fd)\b|fieldbus", re.I)),
    ("serial", re.compile(r"rs-?485|rs-?232|serial|uart|rs485|modbus rtu", re.I)),
    ("ethernet", re.compile(r"ethernet|opc\s*ua|modbus tcp|opcua|"
                            r"industrial ethernet", re.I)),
    ("sensor-actuator", re.compile(r"sensor|actuator|\badc\b|\bdac\b|\bpwm\b|"
                                  r"\bgpio\b|thermistor|transducer|relay|"
                                  r"valve|\bmotor\b|servo|encoder", re.I)),
    ("rtos", re.compile(r"\brtos\b|freertos|threadx|zephyr|riot os|contiki|"
                        r"task schedul|interrupt service|isr\b", re.I)),
    ("embedded-hal", re.compile(r"\bregister\b|\bmmio\b|\bvolatile\b|"
                                r"watchdog|firmware|bootloader|device tree|"
                                r"datasheet|\bcortex\b|\bavr\b", re.I)),
    ("scada-hmi", re.compile(r"scada|\bhmi\b|historian|supervisory|"
                             r"industrial control|process control", re.I)),
    ("control-algo", re.compile(r"\bpid\b|setpoint|control loop|"
                                r"\bplc logic\b|feedback|"
                                r"\binterlock\b|\bdeadband\b", re.I)),
]
INSTRUCTIONAL_MARKERS = [
    ("tutorial-word", re.compile(r"\btutorial\b|\bwalkthrough\b|"
                                 r"\bhow[- ]to\b|\bguide\b|\blearning\b|"
                                 r"\bbeginner\b|\bgetting started\b", re.I)),
    ("teaching-word", re.compile(r"\bteaching\b|\bteacher\b|\bstudent\b|"
                                 r"\bcourse\b|\bcurriculum\b|\bclassroom\b|"
                                 r"\bpedagog|\binstructor\b", re.I)),
    ("exercise", re.compile(r"\bexercise\b|\bassignment\b|\blab\s*\d|"
                            r"\bpractice\b|\bworkshop\b|\bsolution\b|"
                            r"\bhomework\b", re.I)),
    ("demo-name", re.compile(r"\bdemo\b|\bexample\b|\bsample\b|"
                             r"\bquickstart\b|\bhello.?world\b|\bdemo\b", re.I)),
]
DEMO_DIR = re.compile(r"(^|/)(example|examples|demo|demos|sample|samples|"
                      r"tutorial|tutorials|exercise|exercises|lab|labs|"
                      r"training|demo_apps)(/|$)", re.I)

rows_files = []


def _isfloat(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def locate_all(key):
    """Every clone of this project, blob-materialised ones first.

    A project can exist in both trees: `_repos2` carries blobs (fast local
    reads) while `_repos` is blobless, so a checkout from the latter has to
    fetch every blob over the network and regularly times out on a large
    repository. Trying the clones in turn makes the run resilient to one of
    them failing.
    """
    out = []
    for base in REPO_DIRS:
        p = os.path.join(base, key)
        if os.path.isdir(os.path.join(p, ".git")):
            out.append(p)
    return out


def locate(key):
    a = locate_all(key)
    return a[0] if a else None


def checkout(repo_key, sha, dest):
    """Materialise the project at `sha`, trying each available clone in turn."""
    if os.path.exists(os.path.join(dest, ".git")):
        return dest
    for src in locate_all(repo_key):
        if os.path.isdir(dest):
            # a previous attempt left a partial worktree: clear it first
            subprocess.run(["git", "-C", src, "worktree", "remove",
                            "--force", dest], capture_output=True)
            if os.path.isdir(dest):
                continue
        try:
            r = subprocess.run(
                ["git", "-C", src, "worktree", "add", "--detach", dest, sha],
                capture_output=True, timeout=2400)
        except subprocess.TimeoutExpired:
            continue
        if r.returncode == 0 and os.path.isdir(dest) and os.listdir(dest):
            return dest
    return None


def walk_sources(root):
    """Yield (abs_path, rel_path, ext, is_header)."""
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".")
                       and d not in ("node_modules", "build", "dist",
                                     "target", "out", "vendor", "bin", "obj")]
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        if SKIP_DIR.search(rel_dir + "/"):
            continue
        for fn in filenames:
            if SKIP_FILE.search(fn):
                continue
            ext = os.path.splitext(fn)[1]
            if ext not in EXT_LANG:
                continue
            full = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(full) > BIG_FILE:
                    continue
            except OSError:
                continue
            rel = os.path.relpath(full, root).replace("\\", "/")
            yield full, rel, ext, ext in HEADER
            n += 1
            if n >= MAX_FILES:
                return


def read_text(path, limit=MAX_FILE_BYTES):
    try:
        with open(path, "rb") as f:
            data = f.read(limit)
    except OSError:
        return None
    return data.decode("utf-8", "ignore")


# --------------------------------------------------------------- coupling
def include_edges(text):
    return re.findall(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', text, re.M)


def coupling_metrics(per_file_includes, rel_of):
    """Afferent/efferent coupling over the project include graph.

    For every translation unit we resolve each `#include "x.h"` to the project
    file that provides it, and count a directed edge unit -> provider.  The
    result is a real module graph, not a directory guess.
    """
    # index basenames and relative paths -> rel path
    index = defaultdict(list)
    for rel in rel_of.values():
        index[os.path.basename(rel)].append(rel)
        index[rel].append(rel)

    incoming = Counter()
    outgoing = Counter()
    edges = 0
    unresolved = 0
    for rel, incs in per_file_includes.items():
        if rel_of.get(rel) in (None,):
            continue
        src_dir = os.path.dirname(rel)
        for inc in incs:
            if inc.startswith(("std", "sys", "linux", "windows", "pthread",
                                "net", "arpa", "netinet")):
                continue
            cands = index.get(os.path.basename(inc)) or []
            cands = [c for c in cands if c != rel]
            if not cands:
                unresolved += 1
                continue
            # prefer a header in the same or an ancestor directory
            best = None
            for c in cands:
                cd = os.path.dirname(c)
                if cd == src_dir or src_dir.startswith(cd) or cd.startswith(src_dir):
                    best = c
                    break
            best = best or cands[0]
            if best == rel:
                continue
            edges += 1
            outgoing[rel] += 1
            incoming[best] += 1
    return incoming, outgoing, edges, unresolved


def afferent_efferent(incoming, outgoing):
    """Return per-file (afferent, efferent, instability = Ce/(Ca+Ce))."""
    res = {}
    for rel in set(list(incoming) + list(outgoing)):
        ca = incoming.get(rel, 0)
        ce = outgoing.get(rel, 0)
        tot = ca + ce
        res[rel] = dict(ca=ca, ce=ce,
                        instability=round(ce / tot, 4) if tot else 0.0)
    return res


# --------------------------------------------------------------- markers
def project_markers(root, sample=600, max_files=20000):
    """Marker counts and demo-subtree share.

    Bounded by `max_files`: a marker census does not benefit from reading
    60,000 files of a large C++ repository, and the count is recorded in the
    output so the bound is visible.
    """
    ind, ins = Counter(), Counter()
    sample_text = []
    nf = 0
    demo_code_files = 0
    total_code_files = 0
    lang_files = Counter()
    for full, rel, ext, is_hdr in walk_sources(root):
        total_code_files += 1
        lang_files[ext] += 1
        if DEMO_DIR.search(rel):
            demo_code_files += 1
        if nf < 2500:
            txt = read_text(full, 60_000)
            if txt is None:
                continue
            nf += 1
            if len(sample_text) < sample:
                sample_text.append(txt[:4000])
            for k, rx in INDUSTRIAL_MARKERS:
                if rx.search(txt):
                    ind[k] += 1
            for k, rx in INSTRUCTIONAL_MARKERS:
                if rx.search(txt):
                    ins[k] += 1
        if total_code_files >= max_files:
            break
    blob = "\n".join(sample_text)
    return dict(industrial=dict(ind), instructional=dict(ins),
                demo_code_files=demo_code_files,
                total_code_files=total_code_files,
                files_scanned=nf, langs=dict(lang_files),
                text_sample_chars=len(blob),
                census_bounded=total_code_files >= max_files)


# --------------------------------------------------------------- per project
def analyse_project(name, root):
    ccn = []
    nloc_all = []
    sloc_all = []
    loc_all = []
    comment_all = []
    inc_index = defaultdict(list)
    file_cc = {}
    per_file_includes = {}
    n_tus = 0
    long_fn = 0
    param_counts = []
    nesting_max = []

    for full, rel, ext, is_hdr in walk_sources(root):
        txt = read_text(full)
        if txt is None:
            continue
        # ---- cyclomatic complexity via lizard
        # `lizard.analyze_file` is a FileAnalyzer instance whose __call__
        # takes exactly one argument (the path); passing (path, data) raises
        # TypeError and the file is then silently counted as "no functions".
        try:
            res = lizard.analyze_file(full)
        except Exception:
            res = None
        local_cc = []
        if res is not None:
            for fn in res.function_list:
                c = fn.cyclomatic_complexity
                ccn.append(c)
                local_cc.append(c)
                nloc_all.append(fn.nloc)
                if fn.nloc > 60:
                    long_fn += 1
                try:
                    param_counts.append(fn.parameter_count)
                except Exception:
                    pass
        if local_cc:
            file_cc[rel] = dict(
                n_func=len(local_cc), cc_max=max(local_cc),
                cc_mean=round(sum(local_cc) / len(local_cc), 3),
                cc_total=sum(local_cc))
        # ---- sloc / loc / comments via radon raw
        try:
            raw = analyze(txt)
            sloc_all.append(raw.sloc)
            loc_all.append(raw.loc)
            comment_all.append(raw.comments)
        except Exception:
            pass
        # ---- includes for the coupling graph
        incs = include_edges(txt)
        if incs:
            per_file_includes[rel] = incs

    if not ccn:
        return None

    inc_map = {rel: rel for rel in file_cc}
    incoming, outgoing, edges, unresolved = coupling_metrics(
        per_file_includes, inc_map)
    ae = afferent_efferent(incoming, outgoing)
    for rel, d in file_cc.items():
        x = ae.get(rel, dict(ca=0, ce=0, instability=0.0))
        rows_files.append(dict(
            project=name, file=rel, ca=x["ca"], ce=x["ce"],
            instability=x["instability"],
            n_func=d["n_func"], cc_max=d["cc_max"], cc_mean=d["cc_mean"],
            cc_total=d["cc_total"]))

    s = sorted(ccn)
    q = lambda p: ST.quantile(s, p)
    inst = [v["instability"] for v in ae.values()] or [0.0]
    sloc_sum = sum(sloc_all) or 1
    return dict(
        project=name,
        n_translation_units=n_tus,
        n_files_with_functions=len(file_cc),
        n_functions=len(ccn),
        sloc=int(sum(sloc_all)), loc=int(sum(loc_all)),
        comments=int(sum(comment_all)),
        comment_ratio=round(sum(comment_all) / max(1, sum(loc_all)), 4),
        cc_mean=round(sum(ccn) / len(ccn), 3),
        cc_median=q(.5), cc_p25=q(.25), cc_p75=q(.75),
        cc_p90=q(.90), cc_p95=q(.95), cc_p99=q(.99), cc_max=max(ccn),
        cc_sd=round(math.sqrt(
            sum((c - sum(ccn) / len(ccn)) ** 2 for c in ccn) / len(ccn)), 3),
        cc_per_kloc=round(len(ccn) / sloc_sum * 1000, 3),
        median_fn_nloc=ST.quantile(sorted(nloc_all), .5),
        p90_fn_nloc=ST.quantile(sorted(nloc_all), .9),
        long_fn_gt60_loc=long_fn,
        long_fn_share=round(long_fn / len(ccn), 4),
        mean_params=round(sum(param_counts) / len(param_counts), 3)
        if param_counts else "",
        max_params=max(param_counts) if param_counts else "",
        # coupling
        include_edges=edges, unresolved_includes=unresolved,
        mean_instability=round(sum(inst) / len(inst), 4),
        files_with_ca_gt0=sum(1 for v in ae.values() if v["ca"] > 0),
        max_ca=max((v["ca"] for v in ae.values()), default=0),
        max_ce=max((v["ce"] for v in ae.values()), default=0),
        rank_A=sum(1 for c in ccn if c <= 5),
        rank_B=sum(1 for c in ccn if 6 <= c <= 10),
        rank_C=sum(1 for c in ccn if 11 <= c <= 20),
        rank_D=sum(1 for c in ccn if 21 <= c <= 30),
        rank_E=sum(1 for c in ccn if 31 <= c <= 40),
        rank_F=sum(1 for c in ccn if c > 40),
        share_Cplus=round(sum(1 for c in ccn if c > 10) / len(ccn), 4),
        share_DEplus=round(sum(1 for c in ccn if c > 20) / len(ccn), 4),
        max_files_scanned=MAX_FILES,
    )


def main():
    blob = json.load(open(os.path.join(os.path.dirname(HERE), "targets.json"),
                          encoding="utf-8"))
    targets = blob["targets"] if isinstance(blob, dict) else blob
    workroot = os.path.join(os.path.dirname(HERE), "_worktrees")
    os.makedirs(workroot, exist_ok=True)

    rows, marker_rows, group_rows = [], [], []
    # resume support: a project already present in the output CSVs is skipped,
    # so a long run over 26 repositories can be restarted after an interruption
    done = set()
    pm = os.path.join(OUT, "project_metrics.csv")
    if os.path.exists(pm):
        done = {r["project"] for r in
                csv.DictReader(open(pm, encoding="utf-8"))}
    me = os.path.join(OUT, "marker_evidence.csv")
    prior_markers = []
    if os.path.exists(me):
        prior_markers = list(csv.DictReader(open(me, encoding="utf-8")))
        done |= {r["project"] for r in prior_markers}
    if done:
        print(f"[resume] {len(done)} projects already profiled", flush=True)
        # The field set can grow between runs (metrics added in a later
        # revision), so a resumed run re-derives the union of columns instead
        # of reusing the previous header verbatim.
        prior = list(csv.DictReader(open(pm, encoding="utf-8"))) \
            if os.path.exists(pm) else []
        cols = ["project"] + [k for k in prior[0] if k != "project"] \
            if prior else ["project"]
        for extra in ("max_files_scanned", "census_bounded"):
            if extra not in cols:
                cols.append(extra)
        rows = []
        for r in prior:
            d = {}
            for k in cols:
                v = r.get(k, "")
                if v == "":
                    d[k] = ""
                elif _isfloat(v) and ("." in v or "e" in v.lower()):
                    try:
                        d[k] = float(v)
                        continue
                    except ValueError:
                        pass
                try:
                    d[k] = int(v)
                except ValueError:
                    d[k] = v
            rows.append(d)
        marker_rows = [dict(r) for r in prior_markers]

    for t in targets:
        if t["name"] in done:
            print(f"[skip] {t['name']}: already profiled", flush=True)
            continue
        dest = os.path.join(workroot, f"{t['repo_key']}__{t.get('tag','x')}")
        wt = checkout(t["repo_key"], t["sha"], dest)
        if not wt or not os.path.isdir(wt):
            print(f"[skip] {t['name']}: checkout failed", flush=True)
            continue
        mk = project_markers(wt)
        tot = max(1, mk["total_code_files"])
        demo_share = round(mk["demo_code_files"] / tot, 4)
        ins_score = sum(mk["instructional"].values())
        ind_score = sum(mk["industrial"].values())
        marker_rows.append(dict(
            project=t["name"], domain=t.get("domain", ""),
            files_scanned=mk["files_scanned"],
            total_code_files=mk["total_code_files"],
            demo_code_files=mk["demo_code_files"],
            demo_subtree_share=demo_share,
            industrial_marker_hits=ind_score,
            industrial_kinds=";".join(f"{k}:{v}" for k, v in
                                      sorted(mk["industrial"].items(),
                                             key=lambda x: -x[1])),
            instructional_marker_hits=ins_score,
            instructional_kinds=";".join(f"{k}:{v}" for k, v in
                                        sorted(mk["instructional"].items(),
                                               key=lambda x: -x[1])),
            langs=";".join(f"{k}:{v}" for k, v in
                           sorted(mk["langs"].items(), key=lambda x: -x[1])),
        ))
        print(f"[marker] {t['name']}: demo_share={demo_share:.3f} "
              f"ins={ins_score} ind={ind_score}", flush=True)

        r = analyse_project(t["name"], wt)
        if not r:
            print(f"[warn] {t['name']}: no functions parsed", flush=True)
            continue
        rows.append(r)
        # incremental write so a long run keeps its results if interrupted;
        # the union of columns is used so rows produced by different revisions
        # of this script (different metric sets) still serialise
        allcols = ["project"]
        for x in rows:
            for k in x:
                if k not in allcols:
                    allcols.append(k)
        ST.write_csv(rows, os.path.join(OUT, "project_metrics.csv"), allcols)
        ST.write_csv(marker_rows, os.path.join(OUT, "marker_evidence.csv"))
        print(f"[ok] {t['name']}: {r['n_functions']} fns, cc_mean={r['cc_mean']}, "
              f"p95={r['cc_p95']}, sloc={r['sloc']}, edges={r['include_edges']}",
              flush=True)

    if rows:
        p = os.path.join(OUT, "project_metrics.csv")
        allcols = ["project"]
        for x in rows:
            for k in x:
                if k not in allcols:
                    allcols.append(k)
        ST.write_csv(rows, p, allcols)
    if rows_files:
        p = os.path.join(OUT, "file_metrics.csv")
        fcols = []
        for x in rows_files:
            for k in x:
                if k not in fcols:
                    fcols.append(k)
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fcols, restval="",
                               extrasaction="ignore")
            w.writeheader()
            w.writerows(rows_files)
        print(f"[write] {p} n={len(rows_files)}")
    if marker_rows:
        p = os.path.join(OUT, "marker_evidence.csv")
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(marker_rows[0].keys()))
            w.writeheader()
            w.writerows(marker_rows)
        print(f"[write] {p} n={len(marker_rows)}")
    print("PROFILE COMPLETE")


if __name__ == "__main__":
    main()
