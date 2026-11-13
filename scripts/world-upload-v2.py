"""TBA 2.0.0 cutover: upload a converted world (made by TBA2/tools/remap.py) to TBA production (Bloom.host) and swap it in.

WRITES TO PRODUCTION. Every write subcommand needs --yes-production, and is meant to be run only
with the owner's explicit approval at that moment, with the server STOPPED and a Bloom backup taken.

Steps (each a separate run, so each can be approved on its own):
  plan   <local_world>                 read-only: local size/file count, what exists remotely
  upload <local_world> --yes-production
         copies into /world-upload (staging). Resumable: files already there with the same size are
         skipped. The live /world is not touched, so an interrupted upload is harmless.
  verify <local_world>                 read-only: every local file exists in staging with the same size
  swap   --yes-production
         /world -> /world-pre-2.0.0 (kept as an extra rollback), /world-upload -> /world, then moves
         Distant Horizons' LOD database from the old world into the new one (LODs are built from terrain,
         which the conversion leaves alone, so this avoids a full server-side regeneration).
  rollback-swap --yes-production       reverses swap (only if /world-pre-2.0.0 exists)

Auth: TBA/.env + TBA/.ssh key (same as server-config.py). Run from the TBA repo: py -3 scripts/world-upload-v2.py ...
"""
from __future__ import annotations

import os, sys, time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
for _line in open(ROOT / ".env", encoding="utf-8"):
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1); os.environ.setdefault(_k.strip(), _v.strip())


def connect():
    key = os.environ.get("SFTP_KEY_FILE") or str(ROOT / ".ssh" / "tba_sftp_ed25519")
    c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw = {"key_filename": key, "look_for_keys": False, "allow_agent": False} if os.path.isfile(key) else {"password": os.environ["SFTP_PASSWORD"]}
    c.connect(os.environ["SFTP_HOST"], port=int(os.environ.get("SFTP_PORT", "2022")), username=os.environ["SFTP_USERNAME"], **kw)
    return c, c.open_sftp()

LIVE, STAGING, OLD = "world", "world-upload", "world-pre-2.0.0"
# Server-only data that never left the server (not in the snapshot); carried from the old world on swap.
CARRY = ["data/DistantHorizons.sqlite", "DistantHorizons.sqlite"]
SKIP_LOCAL = {"session.lock"}


def local_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name not in SKIP_LOCAL and not p.name.endswith(".part"):
            yield p.relative_to(root).as_posix(), p.stat().st_size


def rexists(sftp, path):
    try:
        return sftp.stat(path)
    except FileNotFoundError:
        return None


def rmkdirs(sftp, path, made):
    parts = path.split("/")
    for i in range(1, len(parts) + 1):
        d = "/".join(parts[:i])
        if d in made:
            continue
        if not rexists(sftp, d):
            sftp.mkdir(d)
        made.add(d)


def need_yes():
    if "--yes-production" not in sys.argv:
        sys.exit("refusing: this writes to PRODUCTION. Re-run with --yes-production after owner approval.")


def main():
    cmd = sys.argv[1]
    t, sftp = connect()
    try:
        if cmd == "plan":
            files = list(local_files(Path(sys.argv[2])))
            print(f"local: {len(files)} files, {sum(s for _, s in files)/1e9:.2f} GB")
            for d in (LIVE, STAGING, OLD):
                print(f"remote /{d}: {'present' if rexists(sftp, d) else 'absent'}")
            for c in CARRY:
                a = rexists(sftp, f"{LIVE}/{c}")
                if a:
                    print(f"remote {LIVE}/{c}: {a.st_size/1e9:.2f} GB (carried over on swap)")
        elif cmd == "upload":
            need_yes()
            root = Path(sys.argv[2])
            files = list(local_files(root))
            total = sum(s for _, s in files)
            made, sent, n, skipped, t0 = set(), 0, 0, 0, time.time()
            rmkdirs(sftp, STAGING, made)
            for rel, size in files:
                remote = f"{STAGING}/{rel}"
                a = rexists(sftp, remote)
                if a and a.st_size == size:
                    skipped += 1
                    continue
                rmkdirs(sftp, remote.rsplit("/", 1)[0], made)
                sftp.put(str(root / rel), remote + ".part")
                if rexists(sftp, remote):
                    sftp.remove(remote)
                sftp.rename(remote + ".part", remote)
                sent += size; n += 1
                if n % 200 == 0:
                    rate = sent / max(1, time.time() - t0)
                    print(f"  {n} files, {sent/1e9:.2f}/{total/1e9:.2f} GB, {rate/1e6:.1f} MB/s", flush=True)
            print(f"UPLOADED {n} files ({sent/1e9:.2f} GB), skipped {skipped} already present, {time.time()-t0:.0f}s")
        elif cmd == "verify":
            bad = 0
            files = list(local_files(Path(sys.argv[2])))
            for rel, size in files:
                a = rexists(sftp, f"{STAGING}/{rel}")
                if not a or a.st_size != size:
                    bad += 1
                    if bad <= 20:
                        print("  MISMATCH", rel, size, a.st_size if a else "missing")
            print(f"verify: {len(files)} files, {bad} mismatched -> {'OK' if not bad else 'NOT OK'}")
            sys.exit(1 if bad else 0)
        elif cmd == "swap":
            need_yes()
            if not rexists(sftp, STAGING):
                sys.exit(f"/{STAGING} missing: upload first")
            if rexists(sftp, OLD):
                sys.exit(f"/{OLD} already exists: resolve by hand before swapping again")
            sftp.rename(LIVE, OLD)
            sftp.rename(STAGING, LIVE)
            print(f"swapped: /{LIVE} -> /{OLD}, /{STAGING} -> /{LIVE}")
            for c in CARRY:
                if rexists(sftp, f"{OLD}/{c}") and not rexists(sftp, f"{LIVE}/{c}"):
                    sftp.rename(f"{OLD}/{c}", f"{LIVE}/{c}")
                    print(f"carried {c}")
        elif cmd == "rollback-swap":
            need_yes()
            if not rexists(sftp, OLD):
                sys.exit(f"/{OLD} missing: nothing to roll back")
            for c in CARRY:
                if rexists(sftp, f"{LIVE}/{c}") and not rexists(sftp, f"{OLD}/{c}"):
                    sftp.rename(f"{LIVE}/{c}", f"{OLD}/{c}")
            sftp.rename(LIVE, STAGING)
            sftp.rename(OLD, LIVE)
            print(f"rolled back: /{LIVE} is the pre-2.0.0 world again; converted world back in /{STAGING}")
        else:
            sys.exit(__doc__)
    finally:
        t.close()


if __name__ == "__main__":
    main()
