"""Bench sampler (runs in the laptop's interactive session).
    pythonw sampler.py <dir> <max_seconds>
Every 5 s: private/working set + CPU of the TBA client (javaw, TBA-2.0.12-*) and the bench server
(java, -Dbench=). When <dir>/measure-<tag>.txt appears: jcmd GC.run then GC.heap_info on both,
written to <dir>/<tag>.json. Safety: kills all java if available RAM < 1500 MB for 3 samples.
Stops on <dir>/stop.txt or after max_seconds."""
import json, os, re, subprocess, sys, time, csv
import psutil
d, max_s = sys.argv[1], float(sys.argv[2])
os.makedirs(d, exist_ok=True)
JCMD = r"C:\Users\slash\AppData\Roaming\PrismLauncher\java\java-runtime-delta\bin\jcmd.exe"
NOWIN = 0x08000000
psutil.Process().nice(psutil.HIGH_PRIORITY_CLASS)
def log(m):
    open(os.path.join(d, "sampler.log"), "a").write(time.strftime("%H:%M:%S ") + m + "\n")
def procs():
    out = {}
    for p in psutil.process_iter(["name", "cmdline"]):
        n = (p.info["name"] or "").lower()
        if n not in ("java.exe", "javaw.exe"): continue
        cl = " ".join(p.info["cmdline"] or [])
        m = re.search(r"-Dbench=(\w+)", cl)
        if m: out["server"] = p; continue
        try: cwd = p.cwd()
        except psutil.Error: cwd = ""
        if "TBA-2.0.12-" in cl or "TBA-2.0.12-" in cwd:
            try:
                if "client" not in out or p.memory_info().private > out["client"].memory_info().private: out["client"] = p
            except psutil.Error: pass
    return out
def heap(pid):
    r = subprocess.run([JCMD, str(pid), "GC.heap_info"], capture_output=True, text=True, timeout=60, creationflags=NOWIN)
    m = re.search(r"total (\d+)K, used (\d+)K", r.stdout)
    mm = re.search(r"Metaspace\s+used (\d+)K", r.stdout)
    return {"heap_total_mb": int(m.group(1))//1024 if m else None, "heap_used_mb": int(m.group(2))//1024 if m else None,
            "metaspace_mb": int(mm.group(1))//1024 if mm else None, "raw": r.stdout[-600:] if not m else ""}
f = open(os.path.join(d, "samples.csv"), "a", newline=""); w = csv.writer(f)
w.writerow(["t", "role", "pid", "private_mb", "ws_mb", "cpu_pct", "avail_mb"])
t0 = time.time(); low = 0; cpu = {}
log("start")
while time.time() - t0 < max_s and not os.path.exists(os.path.join(d, "stop.txt")):
    time.sleep(5)
    vm = psutil.virtual_memory(); av = vm.available // 2**20
    low = low + 1 if av < 1500 else 0
    if low >= 3:
        log("KILL low memory")
        for p in psutil.process_iter(["name"]):
            if (p.info["name"] or "").lower() in ("java.exe", "javaw.exe"):
                try: p.kill()
                except psutil.Error: pass
        low = 0
    ps = procs()
    for role, p in ps.items():
        try:
            if p.pid not in cpu: cpu[p.pid] = p; p.cpu_percent(); c = ""
            else: c = round(cpu[p.pid].cpu_percent(), 1)
            mi = p.memory_info()
            w.writerow([round(time.time(), 1), role, p.pid, mi.private // 2**20, mi.wset // 2**20, c, av])
        except psutil.Error: pass
    f.flush()
    for fn in os.listdir(d):
        if fn.startswith("measure-") and fn.endswith(".txt"):
            tag = fn[8:-4]; os.remove(os.path.join(d, fn))
            res = {"t": time.time(), "avail_mb": av}
            for role, p in ps.items():
                try:
                    subprocess.run([JCMD, str(p.pid), "GC.run"], capture_output=True, timeout=120, creationflags=NOWIN)
                    time.sleep(3)
                    h = heap(p.pid); mi = p.memory_info()
                    h.update(private_mb=mi.private // 2**20, ws_mb=mi.wset // 2**20, pid=p.pid)
                    res[role] = h
                except Exception as e:
                    res[role] = {"error": repr(e)}
            json.dump(res, open(os.path.join(d, tag + ".json"), "w"), indent=1)
            log("measured " + tag)
log("stop")
