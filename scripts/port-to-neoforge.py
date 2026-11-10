#!/usr/bin/env python3
"""One-time port of the TBA mod list from Fabric to NeoForge 1.21.1 (TBA 2.0.0).

Reads the audit from ../TBA2/out/audit.csv (same project ships NeoForge 1.21.1 -> reinstall it) plus
the EQUIVALENT / DROP / ADD tables below. Removes every old mods/*.pw.toml, then installs NeoForge
builds with packwiz (CurseForge first, Modrinth only where noted). Keeps each mod's original `side`.
Guard: Modrinth installs may silently replace existing CurseForge entries (packwiz gotcha), so the
mods/ dir is snapshotted before each Modrinth install and pre-existing entries are restored.

Usage: py -3 scripts/port-to-neoforge.py   (run from the TBA repo root, pack.toml already NeoForge)
Writes scripts/port-to-neoforge.log
"""
from __future__ import annotations

import csv, re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PW = str(ROOT / "packwiz.exe")
AUDIT = ROOT.parent / "TBA2" / "out" / "audit.csv"
MODS = ROOT / "mods"
LOG = ROOT / "scripts" / "port-to-neoforge.log"

# old slug -> ("cf"|"mr", project) : different project ships the NeoForge build
EQUIVALENT = {
    "balm-fabric": ("cf", "balm"),
    "beautify-refabricated": ("mr", "beautify"),
    "chunky-pregenerator": ("mr", "chunky"),
    "falling-leaves-fabric": ("mr", "fallingleavesforge"),
    "farmers-delight-refabricated": ("cf", "farmers-delight"),
    "fastquit": ("mr", "fastquit-forge"),
    "ferritecore-fabric": ("mr", "ferrite-core"),
    "flan": ("mr", "flan"),
    "friends-and-foes": ("cf", "friends-and-foes-forge"),
    "adorn": ("mr", "adorn"),
    "language-reload": ("mr", "neo-language-reload"),
    "lootr-fabric": ("cf", "slashloot"),
    "more-delight-fabric": ("mr", "more-delight"),
    "presence-footsteps": ("mr", "pf-neoforge"),
    "sit-fabric": ("cf", "sit"),
    "stack-to-nearby-chests": ("mr", "stack-to-nearby-chests-neoforge"),
    "status-effect-bars": ("mr", "status-effect-bars-reforged"),
    "travelers-backpack-fabric": ("cf", "travelers-backpack"),
    "visuality": ("mr", "visuality-forge"),
    "windchime-unofficial-continued": ("mr", "windchime"),
    "wthit": ("mr", "wthit"),
    "fabric-seasons": ("cf", "serene-seasons"),
    "ledger": ("cf", "grieflogger"),
    # Effortless Structure's universal jar NPEs on the NeoForge client tick; use the maintained original
    "effortless": ("cf", "302113"),
}

# no NeoForge build and no equivalent we want (reason recorded in the log / CHANGELOG)
DROP = {
    "fabric-api": "Fabric library", "fabric-language-kotlin": "Fabric library (Kotlin for Forge comes in as a dependency)",
    "cardinal-components-api": "Fabric library", "trinkets": "Fabric library", "malilib": "Fabric library",
    "polymer": "Fabric library", "text-placeholder-api": "Fabric library", "cicada": "Fabric library",
    "konkrete-fabric": "library (pulled back in only if a NeoForge mod needs it)",
    "modmenu": "NeoForge has a built-in mods screen",
    "luckperms-placeholders": "Fabric-only", "essential-permissions": "Fabric-only (NeoForge permission API, op levels)",
    "gamemode-unrestrictor": "Fabric-only", "voice-chat-interaction": "Fabric-only",
    "fabric-seasons-extras": "Fabric Seasons add-on (Serene Seasons replaces it)",
    "fabric-seasons-delight-compat": "Fabric Seasons add-on (Serene Seasons replaces it)",
    "reframed": "converted to Create: Copycats+", "clutter": "Fabric-only; placed blocks remapped",
    "verdantvibes-unofficial-port": "Fabric-only; placed plants remapped", "connectiblechains": "Fabric-only",
    "niftycarts": "Fabric-only", "itemswapper": "Fabric-only", "mouse-wheelie": "Fabric-only (Mouse Tweaks + Client Sort cover it)",
    "paginated-advancements": "Fabric-only", "accurate-block-placement-reborn": "Fabric-only", "krypton": "Fabric-only",
    "debugify": "Fabric-only", "atmosfera": "Fabric-only (AmbientSounds stays)", "better-mount-hud": "Fabric-only",
    "eating-animation-fabric": "Fabric-only", "morechathistory": "Fabric-only", "optigui": "Fabric-only",
    "skyboxify": "Fabric-only", "axiomtool": "Fabric-only (WorldEdit covers building tools)", "litematica": "Fabric-only",
    "camera-utils": "only an unofficial NeoForge port", "enhanced-block-entities": "only an unofficial NeoForge port",
    "replay-mod-fabric-and-forge": "no NeoForge build", "flashback": "only an unofficial NeoForge port",
    "core-curriculum": "our mod; NeoForge port later", "scenecraft": "our mod; NeoForge port later",
    "synthcraft-live": "our mod; NeoForge port later",
    "stable-cam": "Fabric-only (the 'NeoForge' listing is a Fabric jar)",
    "continuity": "NeoForge build is a Sinytra Connector port (needs connector + fabric_api)",
    "rrls": "crashes Controlify init on NeoForge (config fetched before ready)",
    # LuckPerms NeoForge 5.4.140 (last 1.21.1 build) initialises players on PlayerLoggedInEvent, after the
    # command tree is sent; any mod checking PermissionAPI in a command requirement (Voice Chat, Balm) then
    # throws -> "Invalid player data" on join. Prod LuckPerms held no data, so ops levels cover permissions.
    "luckperms": "LuckPerms NeoForge 1.21.1 kicks players on join (see note above)",
    "styled-chat": "Fabric-only; LuckPerms prefix mod dropped with LuckPerms",
    "simple-voice-chat": "owner: StreamCraft covers voice",
}

ADD = [("cf", "create"), ("cf", "copycats"), ("cf", "woodworks")]  # WorldEdit deferred: OOMs on Diagonal Blocks state map

# version pins carried from the proof of concept
PINS = {"waterframes": ("cf", "834607", "8056721"), "watermedia": ("cf", "869524", "7281929"),
        # CF's newest 1.21.1 file is the Spigot plugin; this is the NeoForge 1.21/1.21.1 jar
        "advanced-backups": ("cf", "876284", "6148234")}
# Sodium 0.8.x line: Supplementaries/More Culling refuse Sodium < 0.8; Iris 1.8.14, Reese's 2.x, Sodium Extra 0.9 follow it
CLIENT_ONLY = {"watermedia", "watermedia-platform-extension", "sodium", "irisshaders",
               "reeses-sodium-options", "sodium-extra"}
# Distant Horizons hooks Chunky on the client when it is present, and Chunky only initialises on servers
SERVER_ONLY = {"chunky", "advanced-backups"}


def run(args):
    r = subprocess.run([PW, *args, "-y"], cwd=ROOT, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    ok = r.returncode == 0 and "successfully" in out
    return ok, out


def snapshot():
    return {p.name: p.read_bytes() for p in MODS.glob("*.pw.toml")}


def install(src, proj, file_id=None, log=None):
    if src == "cf":
        args = ["cf", "install"]
        args += ["--addon-id", proj] if proj.isdigit() else [proj]
        if file_id:
            args += ["--file-id", file_id]
        return run(args)
    before = snapshot()
    ok, out = run(["mr", "install", proj])
    after = snapshot()
    # restore pre-existing entries a Modrinth install replaced or removed
    for name, data in before.items():
        if after.get(name) != data:
            (MODS / name).write_bytes(data)
            log.append(f"    guard: restored {name} after mr install {proj}")
    return ok, out


def set_side(slug_files_before, side_by_name, log):
    pass


def main() -> int:
    rows = {r["slug"]: r for r in csv.DictReader(open(AUDIT, encoding="utf-8"))}
    old = {p.name.removesuffix(".pw.toml"): p.read_text(encoding="utf-8") for p in MODS.glob("*.pw.toml")}
    old_side = {s: (re.search(r'^side = "(\w+)"', t, re.M) or [None, "both"])[1] for s, t in old.items()}
    backup = ROOT / "scripts" / ".fabric-mods-backup"
    if backup.exists():
        shutil.rmtree(backup)
    shutil.copytree(MODS, backup)
    for p in MODS.glob("*.pw.toml"):
        p.unlink()

    log, plan = [], []
    for slug in sorted(old):
        if slug in PINS:
            plan.append((slug, *PINS[slug]))
        elif slug in EQUIVALENT:
            plan.append((slug, *EQUIVALENT[slug], None))
        elif slug in DROP:
            log.append(f"DROP {slug}: {DROP[slug]}")
        elif slug in rows and rows[slug]["neoforge_1211"] == "yes":
            r = rows[slug]
            plan.append((slug, "cf" if r["source"] == "curseforge" else "mr", r["project_id"], None))
        elif slug == "streamcraft-live":
            plan.append((slug, "cf", "1451729", None))
        else:
            log.append(f"DROP {slug}: no NeoForge 1.21.1 build found in audit (review)")
    plan += [(f"+{p}", s, p, None) for s, p in ADD]

    # CurseForge first, then Modrinth (guarded)
    for slug, src, proj, fid in sorted(plan, key=lambda x: x[1] != "cf"):
        before = set(p.name for p in MODS.glob("*.pw.toml"))
        ok, out = install(src, proj, fid, log)
        new = sorted(set(p.name for p in MODS.glob("*.pw.toml")) - before)
        log.append(f"{'OK  ' if ok else 'FAIL'} {slug} <- {src}:{proj}{' file ' + fid if fid else ''} -> {', '.join(new) or '(nothing new)'}")
        if not ok:
            log.append("     " + out.splitlines()[-1][:200] if out else "     (no output)")
        # keep the original side for the primary file of this mod
        side = old_side.get(slug)
        if side and new:
            primary = new[-1] if len(new) == 1 else next((n for n in new if slug.split("-")[0] in n), new[0])
            p = MODS / primary
            t = p.read_text(encoding="utf-8")
            p.write_text(re.sub(r'^side = "\w+"', f'side = "{side}"', t, count=1, flags=re.M), encoding="utf-8")

    for name in CLIENT_ONLY:
        p = MODS / f"{name}.pw.toml"
        if p.exists():
            p.write_text(re.sub(r'^side = "\w+"', 'side = "client"', p.read_text(encoding="utf-8"), count=1, flags=re.M), encoding="utf-8")

    for name in SERVER_ONLY:
        p = MODS / f"{name}.pw.toml"
        if p.exists():
            p.write_text(re.sub(r'^side = "\w+"', 'side = "server"', p.read_text(encoding="utf-8"), count=1, flags=re.M), encoding="utf-8")

    subprocess.run([PW, "refresh"], cwd=ROOT, capture_output=True)
    LOG.write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))
    print(f"\n{len(list(MODS.glob('*.pw.toml')))} mod entries now; Fabric originals in {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
