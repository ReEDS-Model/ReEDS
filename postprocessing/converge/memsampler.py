"""
Sample resident memory per ReEDS run every N seconds.
Processes are assigned to a run by their cwd or a cmdline arg (or the nearest ancestor's) being inside
runs/{prefix}*. Writes one row per (time, run) plus a machine-wide row.

Usage (start right after launching a batch; it stops by itself 10 minutes after the last run ends):
    nohup setsid python postprocessing/converge/memsampler.py runs v20261021_ mem_v20261021.csv 30 &
Columns: run, rss_gb (all processes in the run), nprocs, top_proc / top_rss_gb (largest process,
e.g. julia = PRAS, gmsgenux.out = CPLEX, gamscmex.out = GAMS), plus a MACHINE_USED row each sample.
"""
import os
import sys
import time
import csv
from datetime import datetime, timezone

runs_dir, prefix, outcsv = sys.argv[1:4]
interval = int(sys.argv[4]) if len(sys.argv) > 4 else 30
runs_dir = os.path.realpath(runs_dir)
root = os.path.join(runs_dir, prefix)


def snapshot():
    procs = {}
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            with open(f'/proc/{pid}/stat') as f:
                stat = f.read()
            comm = stat[stat.index('(') + 1:stat.rindex(')')]
            ppid = int(stat[stat.rindex(')') + 2:].split()[1])
            with open(f'/proc/{pid}/statm') as f:
                rss = int(f.read().split()[1]) * os.sysconf('SC_PAGE_SIZE')
            try:
                cwd = os.readlink(f'/proc/{pid}/cwd')
            except OSError:
                cwd = ''
            ## ReEDS processes run from the repo root, so also match run paths in the cmdline
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                args = f.read().decode(errors='ignore').split('\0')
            path = cwd if cwd.startswith(root) else next(
                (a for a in args if a.startswith(root)), '')
            procs[int(pid)] = (ppid, comm, rss, path)
        except (OSError, ValueError, IndexError):
            continue
    return procs


def run_of(pid, procs, cache):
    chain = []
    while pid in procs and pid not in cache:
        chain.append(pid)
        cwd = procs[pid][3]
        if cwd.startswith(root):
            run = os.path.relpath(cwd, runs_dir).split(os.sep)[0]
            break
        pid = procs[pid][0]
    else:
        run = cache.get(pid)
    for p in chain:
        cache[p] = run
    return run


def meminfo_used_gb():
    m = {}
    with open('/proc/meminfo') as f:
        for line in f:
            k, v = line.split(':')
            m[k] = int(v.split()[0])
    return (m['MemTotal'] - m['MemAvailable']) / 1024**2


seen_any, last_seen = False, time.time()
newfile = not os.path.exists(outcsv)
with open(outcsv, 'a', newline='') as f:
    w = csv.writer(f)
    if newfile:
        w.writerow(['time_utc', 'run', 'rss_gb', 'nprocs', 'top_proc', 'top_rss_gb'])
    while True:
        procs = snapshot()
        cache = {}
        agg = {}
        for pid, (ppid, comm, rss, cwd) in procs.items():
            run = run_of(pid, procs, cache)
            if run is None:
                continue
            a = agg.setdefault(run, [0, 0, '', 0])
            a[0] += rss
            a[1] += 1
            if rss > a[3]:
                a[2], a[3] = comm, rss
        now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        for run, (rss, n, top, toprss) in sorted(agg.items()):
            w.writerow([now, run, round(rss / 1024**3, 2), n, top, round(toprss / 1024**3, 2)])
        w.writerow([now, 'MACHINE_USED', round(meminfo_used_gb(), 2), len(procs), '', ''])
        f.flush()
        if agg:
            seen_any, last_seen = True, time.time()
        elif seen_any and time.time() - last_seen > 600:
            break
        time.sleep(interval)
