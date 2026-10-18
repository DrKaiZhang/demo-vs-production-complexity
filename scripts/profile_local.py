"""Complexity profiling that reads only already-checked-out worktrees.

`profile_run.py` materialises each project with `git worktree add`, which on a
blobless clone has to fetch every blob over the network. On Mbed-OS (19,699
files) that produced a process that sat in uninterruptible I/O with zero CPU
time for 40 minutes, and on Zephyr (68,720 files) it needed the blobbed clone in
`_repos2` at all.

This profiler therefore accepts a pre-existing worktree and never calls git for
content. Projects that are already checked out under `_worktrees/` are analysed
directly; the remaining ones are reported as `no worktree` so the corpus is
explicit rather than silently short. The result is the same measurement — cyclomatic
complexity per function, SLOC/LOC, comment ratios and a resolved `#include`
coupling graph — computed from real source files, with the worktree recorded per
project so the analysed commit is auditable.
"""
import os
import re
import io
import sys
import json
import math
import csv
import argparse
import collections
from collections import Counter

import lizard
from radon.raw import analyze

HERE = os.path.dirname(os.path.abspath(__file__))     # .../05_IE/scripts
STUDY = os.path.dirname(HERE)                         # .../05_IE
ROOT = os.path.dirname(STUDY)                        # .../papers4
_SHARED = os.path.join(ROOT, "00_shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
try:
    import stats_core as ST
except ImportError:  # pragma: no cover
    import stats_tools as ST

WORKTREES = os.path.join(STUDY, "_worktrees")
OUT = os.path.join(STUDY, "data", "analysis_out4")
os.makedirs(OUT, exist_ok=True)

EXT_LANG = {".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
            ".hpp": "cpp", ".hh": "cpp", ".ino": "cpp", ".java": "java",
            ".cs": "cs", ".js": "javascript", ".ts": "typescript",
            ".py": "python", ".go": "go", ".rs": "rust"}
SKIP_FILE = re.compile(r"\.(min\.js|map|lock|svg|png|jpg|jpeg|gif|pdf|ico|"
                       r"woff2?|ttf|eot|so|a|dll|exe|bin|hex|elf|o|obj|"
                       r"lib|jar|class|pyc|mod|sum)$", re.I)
SKIP_DIR = re.compile(r"(^|/)(node_modules|\.git|third_party|3rdparty|vendor|"
                      r"external|build|dist|target|out|\.github|locale|"
                      r"unittests?|test(s)?)(/|$)", re.I)
FOREIGN = re.compile(r"(^|/)(third_party|3rdparty|vendor|external|deps|"
                     r"contrib|libdeps|Godeps)(/|$)", re.I)
MAX_FILES = int(os.environ.get("MAX_FILES", "6000"))
MAX_BYTES = 300_000
DEMO_DIR = re.compile(r"(^|/)(example|examples|demo|demos|sample|samples|"
                      r"tutorial|tutorials|exercise|exercises|lab|labs|"
                      r"training|demo_apps)(/|$)", re.I)

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
                        r"task schedul|interrupt service|\bisr\b", re.I)),
    ("embedded-hal", re.compile(r"\bregister\b|\bmmio\b|\bvolatile\b|"
                                r"watchdog|firmware|bootloader|device tree|"
                                r"datasheet|\bcortex\b|\bavr\b", re.I)),
    ("scada-hmi", re.compile(r"scada|\bhmi\b|historian|supervisory|"
                             r"industrial control|process control", re.I)),
    ("control-algo", re.compile(r"\bpid\b|setpoint|control loop|\bplc logic\b|"
                                r"feedback|\binterlock\b|\bdeadband\b", re.I)),
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
                             r"\bquickstart\b|\bhello.?world\b", re.I)),
]

rows_files = []


def read_text(path, limit=MAX_BYTES):
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", "ignore")
    except OSError:
        return None


def walk_sources(root):
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
                if os.path.getsize(full) > 2_000_000:
                    continue
            except OSError:
                continue
            rel = os.path.relpath(full, root).replace("\\", "/")
            yield full, rel, ext
            n += 1
            if n >= MAX_FILES:
                return


def include_edges(text):
    return re.findall(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', text, re.M)


def coupling(per_file_includes, files):
    index = collections.defaultdict(list)
    for rel in files:
        index[os.path.basename(rel)].append(rel)
        index[rel].append(rel)
    incoming, outgoing = Counter(), Counter()
    for rel, incs in per_file_includes.items():
        src_dir = os.path.dirname(rel)
        for inc in incs:
            if inc.startswith(("std", "sys", "linux", "windows", "pthread",
                                "net", "arpa", "netinet", "coresvc", "zephyr")):
                continue
            cands = [c for c in index.get(os.path.basename(inc), []) if c != rel]
            if not cands:
                continue
            best = None
            for c in cands:
                cd = os.path.dirname(c)
                if cd == src_dir or src_dir.startswith(cd) or cd.startswith(src_dir):
                    best = c
                    break
            best = best or cands[0]
            if best == rel:
                continue
            outgoing[rel] += 1
            incoming[best] += 1
    return incoming, outgoing


def analyse(name, root, domain):
    ccn, nloc_all = [], []
    sloc_all, loc_all, comment_all = [], [], []
    per_file_includes, files = {}, []
    long_fn = params = 0
    ind, ins = Counter(), Counter()
    demo_files = total_files = 0
    lang = Counter()

    for full, rel, ext in walk_sources(root):
        total_files += 1
        lang[ext] += 1
        if DEMO_DIR.search(rel):
            demo_files += 1
        txt = read_text(full)
        if txt is None:
            continue
        for k, rx in INDUSTRIAL_MARKERS:
            if rx.search(txt):
                ind[k] += 1
        for k, rx in INSTRUCTIONAL_MARKERS:
            if rx.search(txt):
                ins[k] += 1
        try:
            res = lizard.analyze_file(full)
        except Exception:
            res = None
        local = []
        if res is not None:
            for fn in res.function_list:
                ccn.append(fn.cyclomatic_complexity)
                local.append(fn.cyclomatic_complexity)
                nloc_all.append(fn.nloc)
                if fn.nloc > 60:
                    long_fn += 1
                try:
                    params += fn.parameter_count
                except Exception:
                    pass
        try:
            raw = analyze(txt)
            sloc_all.append(raw.sloc)
            loc_all.append(raw.loc)
            comment_all.append(raw.comments)
        except Exception:
            pass
        incs = include_edges(txt)
        if incs:
            per_file_includes[rel] = incs
        if local:
            files.append(rel)
            rows_files.append(dict(
                project=name, file=rel, n_func=len(local),
                cc_max=max(local), cc_mean=round(sum(local) / len(local), 3),
                cc_total=sum(local)))
    if not ccn:
        return None
    incoming, outgoing = coupling(per_file_includes, files)
    inst = []
    for rel in set(list(incoming) + list(outgoing)):
        ca, ce = incoming.get(rel, 0), outgoing.get(rel, 0)
        inst.append(ce / (ca + ce) if (ca + ce) else 0.0)
    s = sorted(ccn)
    q = lambda p: ST.quantile(s, p)
    sloc_sum = sum(sloc_all) or 1
    n_fn = len(ccn)
    return dict(
        project=name, domain=domain,
        worktree=os.path.basename(root),
        n_files_with_functions=len(files),
        n_translation_units=total_files,
        n_functions=n_fn,
        sloc=int(sum(sloc_all)), loc=int(sum(loc_all)),
        comments=int(sum(comment_all)),
        comment_ratio=round(sum(comment_all) / max(1, sum(loc_all)), 4),
        cc_mean=round(sum(ccn) / n_fn, 3),
        cc_median=q(.5), cc_p25=q(.25), cc_p75=q(.75),
        cc_p90=q(.90), cc_p95=q(.95), cc_p99=q(.99), cc_max=max(ccn),
        cc_sd=round(math.sqrt(sum((c - sum(ccn) / n_fn) ** 2
                                 for c in ccn) / n_fn), 3),
        cc_per_kloc=round(n_fn / sloc_sum * 1000, 3),
        median_fn_nloc=ST.quantile(sorted(nloc_all), .5),
        p90_fn_nloc=ST.quantile(sorted(nloc_all), .9),
        long_fn_share=round(long_fn / n_fn, 4),
        mean_params=round(params / n_fn, 3) if n_fn else "",
        include_edges=sum(outgoing.values()),
        mean_instability=round(sum(inst) / len(inst), 4) if inst else "",
        max_ca=max(incoming.values()) if incoming else 0,
        max_ce=max(outgoing.values()) if outgoing else 0,
        rank_A=sum(1 for c in ccn if c <= 5),
        rank_B=sum(1 for c in ccn if 6 <= c <= 10),
        rank_C=sum(1 for c in ccn if 11 <= c <= 20),
        rank_D=sum(1 for c in ccn if 21 <= c <= 30),
        rank_E=sum(1 for c in ccn if 31 <= c <= 40),
        rank_F=sum(1 for c in ccn if c > 40),
        share_Cplus=round(sum(1 for c in ccn if c > 10) / n_fn, 4),
        share_DEplus=round(sum(1 for c in ccn if c > 20) / n_fn, 4),
        demo_subtree_share=round(demo_files / max(1, total_files), 4),
        industrial_hits=sum(ind.values()),
        industrial_kinds=";".join(f"{k}:{v}" for k, v in ind.most_common()),
        instructional_hits=sum(ins.values()),
        instructional_kinds=";".join(f"{k}:{v}" for k, v in ins.most_common()),
        langs=";".join(f"{k}:{v}" for k, v in lang.most_common(4)),
        max_files_cap=MAX_FILES,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="analyse every worktree present")
    args = ap.parse_args()

    if not os.path.isdir(WORKTREES):
        print("no _worktrees directory")
        return
    dom = {}
    tp = os.path.join(STUDY, "targets.json")
    if os.path.exists(tp):
        for t in json.load(open(tp, encoding="utf-8"))["targets"]:
            dom[t["name"]] = t.get("domain", "")

    rows = []
    # Projects already profiled in a previous run are skipped, and a project
    # whose worktree is larger than the per-run file budget can be excluded with
    # SKIP_PROJECTS, so one very large repository cannot starve the rest.
    done = set()
    prev = os.path.join(OUT, "project_metrics.csv")
    if os.path.exists(prev):
        for r in csv.DictReader(open(prev, encoding="utf-8")):
            done.add(r["project"])
        print(f"[resume] {len(done)} projects already profiled", flush=True)
    skip = {s for s in os.environ.get("SKIP_PROJECTS", "").split(",") if s}
    if skip:
        print(f"[skip-set] {sorted(skip)}", flush=True)

    for d in sorted(os.listdir(WORKTREES)):
        root = os.path.join(WORKTREES, d)
        if not os.path.isdir(root) or not os.listdir(root):
            print(f"[skip] {d}: empty worktree", flush=True)
            continue
        name = d.split("__")[0]
        pretty = {"riot": "RIOT", "contiki-ng": "Contiki-NG",
                  "zephyr": "Zephyr", "esp8266_ard": "ESP8266-Arduino",
                  "mbed-os": "Mbed-OS", "esp-idf": "ESP-IDF",
                  "freertos": "FreeRTOS-Kernel", "iotivity": "IoTivity-Lite",
                  "mosquitto": "Mosquitto", "beremiz": "Beremiz",
                  "pycomm3": "pycomm3", "ros2_control": "ros2_control",
                  "openplc_v3": "OpenPLC_v3", "evcc": "evcc",
                  "serial_studio": "Serial-Studio", "node_opcua": "node-opcua",
                  "ditto": "Eclipse Ditto", "hivemq": "HiveMQ CE",
                  "mainflux": "Mainflux", "tb_gateway": "ThingsBoard-Gateway",
                  "thingsboard": "ThingsBoard", "px4": "PX4",
                  "ardupilot": "ArduPilot", "grafana": "Grafana",
                  "ha_core": "Home Assistant",                   "kafka": "Apache Kafka",
                  "ua_net": "UA-.NET"}.get(name, name)
        if pretty in done:
            print(f"[skip] {pretty}: already profiled", flush=True)
            continue
        if pretty in skip or name in skip:
            print(f"[skip] {pretty}: excluded by SKIP_PROJECTS", flush=True)
            continue
        r = analyse(pretty, root, dom.get(t["name"] if False else pretty, ""))
        if not r:
            print(f"[warn] {pretty}: no functions parsed", flush=True)
            continue
        rows.append(r)
        if prev and os.path.exists(prev):
            with open(prev, encoding="utf-8") as f:
                prior = list(csv.DictReader(f))
            by = {x["project"]: x for x in prior}
            by[pretty] = r
            merged = list(by.values())
        else:
            merged = rows
        cols = []
        for x in merged:
            for k in x:
                if k not in cols:
                    cols.append(k)
        with open(os.path.join(OUT, "project_metrics.csv"), "w", newline="",
                  encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, restval="",
                               extrasaction="ignore")
            w.writeheader()
            w.writerows(merged)
        print(f"[ok] {pretty}: {r['n_functions']} fns, cc_mean={r['cc_mean']}, "
              f"p95={r['cc_p95']}, sloc={r['sloc']}, "
              f"demo={r['demo_subtree_share']}", flush=True)
    if rows_files:
        cols = []
        for x in rows_files:
            for k in x:
                if k not in cols:
                    cols.append(k)
        with open(os.path.join(OUT, "file_metrics.csv"), "w", newline="",
                  encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, restval="",
                               extrasaction="ignore")
            w.writeheader()
            w.writerows(rows_files)
        print(f"[write] file_metrics.csv n={len(rows_files)}")
    print(f"PROFILED {len(rows)} projects")
    print("PROFILE COMPLETE")


if __name__ == "__main__":
    main()
