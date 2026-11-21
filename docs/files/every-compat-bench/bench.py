"""Every Compat A/B bench orchestrator (all game processes run on the laptop).
    py -3 bench.py warm            first boot of both servers (installs mods, makes the world)
    py -3 bench.py cycle <n> <b1,b2>   per build: server boot -> idle measure -> client session -> in-world measure -> stop
"""
import json, subprocess, sys, threading, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
sys.path.insert(0, r"C:\Users\slash\Projects\LocalServer\scripts")
import testkit as t
LAPTOP = "slash@100.111.19.52"
OUT = Path(__file__).resolve().parent / "results"  # run1-full / run2-slim hold the 2026-11-20 runs
OUT.mkdir(exist_ok=True)
t.TBA_ROOT = Path(r"C:\Users\slash\Projects\ec-bench")
CUR = {"b": "base"}

def rssh(cmd, timeout=90):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", LAPTOP, cmd], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)

def logpath(b): return rf"C:\Users\slash\bench-srv-{b}\logs\latest.log"

def read_log(b, offset=0):
    r = rssh(f'py -3 -c "f=open(r\'{logpath(b)}\',\'rb\');f.seek({int(offset)});import sys;'
             f'sys.stdout.buffer.write(f.read())"')
    return r.stdout

class RemoteLog:
    def stat(self):
        r = rssh(f'py -3 -c "import os;print(os.path.getsize(r\'{logpath(CUR["b"])}\'))"')
        return type("S", (), {"st_size": int(r.stdout.strip() or 0)})()

t._tba_server_log = lambda: RemoteLog()
t._tba_new_server_text = lambda off: read_log(CUR["b"], off)
t._lan_ip_towards = lambda node: "127.0.0.1"

def _rcon_slow(cmd, port=t.TBA_RCON, pw=t.TBA_RCON_PW):
    """testkit's RCON client with a 90 s timeout (the server can be >10 s behind right after the tp)."""
    import socket, struct
    def pkt(i, kind, body):
        b = struct.pack("<ii", i, kind) + body.encode("utf-8") + b"\x00\x00"
        return struct.pack("<i", len(b)) + b
    def read(s):
        n = struct.unpack("<i", s.recv(4))[0]
        data = b""
        while len(data) < n:
            data += s.recv(n - len(data))
        i, _ = struct.unpack("<ii", data[:8])
        return i, data[8:-2].decode("utf-8", "replace")
    with socket.create_connection(("127.0.0.1", port), timeout=90) as s:
        s.sendall(pkt(1, 3, pw)); read(s)
        s.sendall(pkt(2, 2, cmd)); return read(s)[1]
t._rcon = _rcon_slow

def lag_spikes(b, off=0):
    out = []
    for l in read_log(b, off).splitlines():
        if "Can't keep up" in l:
            try: out.append(int(l.split("Running ")[1].split("ms")[0]))
            except (IndexError, ValueError): pass
    return out

def server_java():
    r = rssh('powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \\"name=\'java.exe\'\\" | '
             'Where-Object { $_.CommandLine -like \'*-Dbench=*\' } | Select-Object -ExpandProperty ProcessId"')
    return r.stdout.split()

def start_server(b, timeout=1200):
    CUR["b"] = b
    if server_java(): raise SystemExit("a bench server is already running")
    t0 = time.time()
    rssh(f"schtasks /Run /TN TKSRV{b}")
    time.sleep(10)
    while time.time() - t0 < timeout:
        txt = read_log(b)
        if "Done (" in txt:
            wall = time.time() - t0; time.sleep(6); txt = read_log(b)
            mf = [l for l in txt.splitlines() if "took" in l and ("ModernFix" in l or "modernfix" in l.lower())]
            first = txt.splitlines()[0][:24] if txt else ""
            done = next(l for l in txt.splitlines() if "Done (" in l)[:24]
            return {"wall_s": round(wall, 1), "log_first": first, "log_done": done, "modernfix": mf }
        if "---- Minecraft Crash Report" in txt or "Failed to start the minecraft server" in txt:
            stop_server(); raise SystemExit("server failed:\n" + txt[-3000:])
        time.sleep(10)
    raise SystemExit("server boot timeout")

def stop_server():
    try: print("  rcon stop:", t._rcon("stop").strip()[:80])
    except Exception as e: print("  rcon stop failed", e)
    for _ in range(60):
        if not server_java(): return
        time.sleep(5)
    raise SystemExit("server did not stop")

def measure(tag, timeout=240):
    rssh(r"type nul > C:\Users\slash\tk\bench\measure-" + tag + ".txt")
    for _ in range(timeout // 5):
        time.sleep(5)
        r = rssh("type C:\\Users\\slash\\tk\\bench\\" + tag + ".json")
        if r.returncode == 0 and r.stdout.strip().startswith("{"):
            d = json.loads(r.stdout); (OUT / f"{tag}.json").write_text(r.stdout); return d
    return {"error": "measure timeout"}

def tunnel():
    p = subprocess.Popen(["ssh", "-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                          "-L", "25576:127.0.0.1:25576", LAPTOP])
    time.sleep(4); return p

def save(name, obj):
    (OUT / f"{name}.json").write_text(json.dumps(obj, indent=1, default=str))

def main():
    tn = tunnel()
    try:
        if sys.argv[1] == "warm":
            for b in sys.argv[2].split(","):
                r = start_server(b); print(b, "first boot", r); save(f"warm-{b}", r)
                time.sleep(20); stop_server()
        elif sys.argv[1] == "cycle":
            n = sys.argv[2]
            for b in sys.argv[3].split(","):
                tag = f"{b}-{n}"
                r = start_server(b); print(tag, "boot", r)
                time.sleep(45)
                r["idle"] = measure(f"srvidle-{tag}")
                res = {"boot": r}
                # in-world measurement 75 s after the join, while tba_run holds the session
                joined = {}
                def watcher():
                    off = RemoteLog().stat().st_size
                    for _ in range(200):
                        time.sleep(5)
                        if "joined the game" in read_log(b, off):
                            joined["t"] = time.time(); time.sleep(75)
                            joined["m"] = measure(f"inworld-{tag}"); return
                th = threading.Thread(target=watcher, daemon=True); th.start()
                t0 = time.time()
                try:
                    code = t.tba_run(f"2.0.12-{b}", "laptop", 150, False)
                except SystemExit as e:
                    code = e.code
                res["client_rc"] = code; res["client_wall_s"] = round(time.time() - t0, 1)
                th.join(timeout=300)
                res["inworld"] = joined.get("m"); res["join_seen_s"] = round(joined["t"] - t0, 1) if "t" in joined else None
                res["lag_spikes_ms"] = lag_spikes(b)
                save(f"cycle-{tag}", res); print(tag, json.dumps(res, default=str)[:1500])
                stop_server()
    finally:
        tn.terminate()

main()
